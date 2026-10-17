from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser, get_current_user
from app.api.routes.users import get_profile_for_current_user
from app.db.models import (
    AgentAttachment,
    AgentEvent,
    AgentMatch,
    AgentMessage,
    AgentRequest,
    AgentSession,
    UserProfile,
)
from app.db.session import get_db
from app.rag.indexer import index_request
from app.rag.retriever import retrieve_similar_requests
from app.schemas.broker import (
    BrokerAttachmentGrantCreate,
    BrokerAttachmentPatch,
    BrokerAttachmentRead,
    BrokerConnectOfferRead,
    BrokerEventRead,
    BrokerIntroductionAction,
    BrokerLinkCreate,
    BrokerMatchLaneRead,
    BrokerMatchRead,
    BrokerMessageCreate,
    BrokerMessageRead,
    BrokerRequestMatch,
    BrokerRequestRead,
    BrokerSessionCreate,
    BrokerSessionDetail,
    BrokerSessionRead,
    BrokerSuggestionAction,
    BrokerSuggestionRead,
    ConnectionSummaryRead,
)
from app.services.attachments import (
    SHARE_PERSONAL,
    SHARE_PUBLIC,
    AttachmentError,
    blurred_attachment_bytes,
    classify_attachment,
    create_file_attachment,
    create_link_attachment,
    delete_attachment,
    is_image_type,
    list_pending_upload_requests,
    load_attachment_bytes,
    record_grant,
    sanitize_filename,
    serialize_messages,
    serialize_session_attachments,
    serialize_upload_requests,
    share_attachment_to_match,
    to_attachment_read,
    viewer_can_access,
)
from app.services.connections import fanout_connection_created, to_connection_summary
from app.services.contact import create_party_connection, share_match_contacts
from app.services.introduction import (
    IntroductionError,
    dismiss_connect_offer,
    pending_offers_for_session,
    record_party_go_ahead,
)
from app.services.match_lanes import (
    MatchLaneError,
    mark_match_read,
    serialize_match_lanes,
    serialize_session_list,
    serialize_session_read,
)
from app.services.notify import mail_jobs_for_contacts, schedule_mail
from app.services.orchestrator import (
    create_session_with_agent,
    handle_session_message,
)
from app.services.outreach import schedule_match_kickoff, schedule_outreach
from app.services.session_delete import SESSION_DELETED, delete_session_cascade
from app.services.storage import StorageNotConfiguredError
from app.services.suggestions import (
    SuggestionError,
    get_owned_suggestion,
    list_suggestions,
    mark_interested,
    packet_snapshot,
    skip_suggestion,
)
from app.services.workflow import get_session_request, load_pair_requests

logger = logging.getLogger(__name__)

router = APIRouter()


async def _require_profile(db: AsyncSession, current_user: CurrentUser) -> UserProfile:
    profile = await get_profile_for_current_user(db, current_user)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail="Create your user profile before starting a broker request.",
        )
    return profile


async def _get_owned_session(
    session_id: str,
    db: AsyncSession,
    profile: UserProfile,
) -> AgentSession:
    session = await db.get(AgentSession, session_id)
    if session is None or session.user_id != profile.id or session.status == SESSION_DELETED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Broker session not found")
    return session


async def _get_owned_match(
    match_id: str,
    db: AsyncSession,
    profile: UserProfile,
) -> AgentMatch:
    match = await db.get(AgentMatch, match_id)
    if match is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Broker match not found")
    result = await db.execute(
        select(AgentRequest)
        .join(AgentSession, AgentRequest.session_id == AgentSession.id)
        .where(
            AgentRequest.id.in_([match.source_request_id, match.candidate_request_id]),
            AgentRequest.user_id == profile.id,
            AgentSession.status != SESSION_DELETED,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Broker match not found")
    return match


async def _session_detail(
    db: AsyncSession,
    session: AgentSession,
    profile: UserProfile,
    messages: list[AgentMessage] | None = None,
    request: AgentRequest | None = None,
) -> BrokerSessionDetail:
    if messages is None:
        result = await db.execute(
            select(AgentMessage)
            .where(AgentMessage.session_id == session.id)
            .order_by(
                AgentMessage.created_at,
                AgentMessage.role.desc(),
                AgentMessage.id,
            )
        )
        messages = list(result.scalars().all())
    if request is None:
        request = await get_session_request(db, session.id)
    offers = await pending_offers_for_session(db, session.id)
    offers_by_match = {offer.match_id: offer for offer in offers}
    lanes: list[BrokerMatchLaneRead] = []
    if request is not None:
        lanes = await serialize_match_lanes(
            db,
            request=request,
            profile=profile,
            offers_by_match=offers_by_match,
        )
    offer = offers[0] if offers else None
    suggestion_rows = []
    if request is not None:
        suggestion_rows = await list_suggestions(db, request.id)
    session_read = await serialize_session_read(
        db, session, profile, request=request, lanes=lanes
    )
    return BrokerSessionDetail(
        session=session_read,
        messages=await serialize_messages(db, messages, viewer_user_id=profile.id),
        request=BrokerRequestRead.from_request(request) if request else None,
        attachments=await serialize_session_attachments(
            db, session.id, viewer_user_id=profile.id
        ),
        pending_upload_requests=serialize_upload_requests(
            await list_pending_upload_requests(db, session.id)
        ),
        connect_offer=(
            BrokerConnectOfferRead.model_validate(offer) if offer else None
        ),
        matches=lanes,
        connect_offers=[BrokerConnectOfferRead.model_validate(item) for item in offers],
        suggestions=_suggestion_reads(suggestion_rows),
    )


def _suggestion_reads(rows) -> list[BrokerSuggestionRead]:
    reads: list[BrokerSuggestionRead] = []
    for row in rows:
        snap = packet_snapshot(row)
        reads.append(
            BrokerSuggestionRead(
                id=row.id,
                candidate_id=row.candidate_request_id,
                status=str(snap.get("status") or row.status),
                verdict=str(snap.get("verdict") or ""),
                recommended_action=str(snap.get("recommended_action") or ""),
                pending_clarify=snap.get("pending_clarify"),
                clarifying_question=str(snap.get("clarifying_question") or ""),
                pending_questions=list(snap.get("pending_questions") or []),
                missing_info=list(snap.get("missing_info") or []),
                card_message_id=row.card_message_id,
            )
        )
    return reads


def _attachment_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, StorageNotConfiguredError):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    if isinstance(exc, AttachmentError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/sessions", response_model=list[BrokerSessionRead])
async def list_sessions(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BrokerSessionRead]:
    profile = await _require_profile(db, current_user)
    result = await db.execute(
        select(AgentSession)
        .where(
            AgentSession.user_id == profile.id,
            AgentSession.status != SESSION_DELETED,
        )
        .order_by(desc(AgentSession.updated_at))
    )
    return await serialize_session_list(db, profile, list(result.scalars().all()))


@router.get("/requests", response_model=list[BrokerRequestRead])
async def list_requests(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BrokerRequestRead]:
    profile = await _require_profile(db, current_user)
    result = await db.execute(
        select(AgentRequest)
        .join(AgentSession, AgentRequest.session_id == AgentSession.id)
        .where(
            AgentRequest.user_id == profile.id,
            AgentSession.status != SESSION_DELETED,
        )
        .order_by(desc(AgentRequest.updated_at))
    )
    return [BrokerRequestRead.from_request(request) for request in result.scalars().all()]


@router.get("/requests/{request_id}/matches", response_model=list[BrokerRequestMatch])
async def get_request_matches(
    request_id: str,
    limit: int = 10,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BrokerRequestMatch]:
    profile = await _require_profile(db, current_user)
    request = await db.get(AgentRequest, request_id)
    if request is None or request.user_id != profile.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Broker request not found")
    if request.indexed_at is None:
        try:
            await index_request(request)
            await db.commit()
            await db.refresh(request)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Semantic indexing is not available for this request right now.",
            ) from exc
    if request.indexed_at is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Semantic indexing is not available for this request right now.",
        )
    try:
        matches = await retrieve_similar_requests(db, request, min(max(limit, 1), 50))
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return [
        BrokerRequestMatch(
            request_id=candidate.id,
            title=candidate.title,
            summary=candidate.summary,
            status=candidate.status,
            distance=distance,
        )
        for candidate, distance in matches
    ]


@router.get("/requests/{request_id}/mediations", response_model=list[BrokerMatchRead])
async def list_request_matches(
    request_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AgentMatch]:
    profile = await _require_profile(db, current_user)
    request = await db.get(AgentRequest, request_id)
    if request is None or request.user_id != profile.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Broker request not found")
    result = await db.execute(
        select(AgentMatch)
        .where(
            or_(
                AgentMatch.source_request_id == request_id,
                AgentMatch.candidate_request_id == request_id,
            )
        )
        .order_by(desc(AgentMatch.updated_at))
    )
    return list(result.scalars().all())


@router.get("/matches/{match_id}", response_model=BrokerMatchRead)
async def get_match(
    match_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentMatch:
    profile = await _require_profile(db, current_user)
    return await _get_owned_match(match_id, db, profile)


@router.post("/matches/{match_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_match_lane_read(
    match_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    profile = await _require_profile(db, current_user)
    await _get_owned_match(match_id, db, profile)
    await mark_match_read(db, match_id=match_id, user_id=profile.id)
    await db.commit()


@router.get("/matches/{match_id}/events", response_model=list[BrokerEventRead])
async def list_match_events(
    match_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AgentEvent]:
    profile = await _require_profile(db, current_user)
    await _get_owned_match(match_id, db, profile)
    result = await db.execute(
        select(AgentEvent).where(AgentEvent.match_id == match_id).order_by(AgentEvent.created_at)
    )
    return list(result.scalars().all())


@router.post("/matches/{match_id}/introduction", response_model=BrokerSessionDetail)
async def act_on_introduction(
    match_id: str,
    payload: BrokerIntroductionAction,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BrokerSessionDetail:
    profile = await _require_profile(db, current_user)
    match = await _get_owned_match(match_id, db, profile)
    source, candidate = await load_pair_requests(db, match)
    if source is None or candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Broker match not found")
    current = source if source.user_id == profile.id else candidate
    other = candidate if current.id == source.id else source
    session = await db.get(AgentSession, current.session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Broker session not found")
    outreach = None
    contact_messages = []
    try:
        if payload.action == "dismiss":
            await dismiss_connect_offer(db, match, profile.id)
        else:
            result = await record_party_go_ahead(
                db,
                match=match,
                current=current,
                other=other,
                session_id=session.id,
            )
            outreach = result.outreach
            contact_messages = result.contact_messages
    except IntroductionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    if outreach is not None:
        schedule_outreach([outreach])
    if contact_messages:
        schedule_mail(await mail_jobs_for_contacts(db, match, contact_messages))
    return await _session_detail(db, session, profile)


@router.post(
    "/sessions/{session_id}/suggestions/{suggestion_id}",
    response_model=BrokerSessionDetail,
)
async def act_on_suggestion(
    session_id: str,
    suggestion_id: str,
    payload: BrokerSuggestionAction,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BrokerSessionDetail:
    profile = await _require_profile(db, current_user)
    session = await _get_owned_session(session_id, db, profile)
    request = await get_session_request(db, session.id)
    if request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Broker request not found")
    try:
        row = await get_owned_suggestion(db, suggestion_id, request.id)
        kickoff_match_id = None
        kickoff_context = (
            "This person marked Interested on a suggested pair. Write the pair "
            "kickoff on this match lane and reach the other person with "
            "message_party."
        )
        if payload.action == "skip":
            await skip_suggestion(db, row)
        else:
            match, _reused, photo_id = await mark_interested(
                db,
                row=row,
                source=request,
                session_id=session.id,
                user_id=profile.id,
                requested_attachment_id=payload.attachment_id,
            )
            kickoff_match_id = match.id
            if photo_id:
                kickoff_context = (
                    "This person marked Interested and asked to see a personal "
                    f"photo ({photo_id}). Write the pair kickoff on this match "
                    "lane, reach the other person with message_party, and follow "
                    "the personal-file grant path for that photo."
                )
    except SuggestionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    if kickoff_match_id:
        schedule_match_kickoff(
            match_id=kickoff_match_id,
            session_id=session.id,
            request_id=request.id,
            user_id=profile.id,
            context=kickoff_context,
        )
    return await _session_detail(db, session, profile)


@router.get("/sessions/{session_id}/suggestions/{suggestion_id}/attachments/{attachment_id}/content")
async def suggestion_attachment_content(
    session_id: str,
    suggestion_id: str,
    attachment_id: str,
    variant: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    profile = await _require_profile(db, current_user)
    session = await _get_owned_session(session_id, db, profile)
    request = await get_session_request(db, session.id)
    if request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    try:
        row = await get_owned_suggestion(db, suggestion_id, request.id)
    except SuggestionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found") from exc
    if row.status not in {"presented", "interested"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    candidate = await db.get(AgentRequest, row.candidate_request_id)
    attachment = await db.get(AgentAttachment, attachment_id)
    if (
        candidate is None
        or attachment is None
        or attachment.status != "ready"
        or attachment.session_id != candidate.session_id
        or not is_image_type(attachment.content_type)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    kind = (variant or "").strip().lower()
    try:
        if kind == "blur":
            if attachment.share_class != SHARE_PERSONAL:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
            data, content_type = await blurred_attachment_bytes(attachment)
        else:
            if attachment.share_class != SHARE_PUBLIC:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
            data, content_type = await load_attachment_bytes(attachment)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found") from exc
    except StorageNotConfiguredError as exc:
        raise _attachment_http_error(exc) from exc
    filename = sanitize_filename(attachment.original_filename or attachment.label or "file")
    return Response(
        content=data,
        media_type=content_type or attachment.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "private, max-age=300",
        },
    )


@router.post("/matches/{match_id}/share-contacts", response_model=list[BrokerMessageRead])
async def share_contacts(
    match_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BrokerMessageRead]:
    profile = await _require_profile(db, current_user)
    match = await _get_owned_match(match_id, db, profile)
    if match.status != "accepted":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Both parties must accept before contact details can be shared.",
        )
    try:
        messages = await share_match_contacts(db, match)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    if messages:
        schedule_mail(await mail_jobs_for_contacts(db, match, messages))
    for message in messages:
        await db.refresh(message)
    return await serialize_messages(db, messages, viewer_user_id=profile.id)


@router.post("/matches/{match_id}/connect", response_model=ConnectionSummaryRead)
async def connect_parties(
    match_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConnectionSummaryRead:
    profile = await _require_profile(db, current_user)
    match = await _get_owned_match(match_id, db, profile)
    if match.status not in {"accepted", "connected"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Both parties must accept before a direct connection can be created.",
        )
    try:
        connection = await create_party_connection(db, match)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    summary = await to_connection_summary(db, connection, profile.id)
    await db.commit()
    await fanout_connection_created(db, connection)
    return summary


@router.post("/sessions", response_model=BrokerSessionDetail, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: BrokerSessionCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BrokerSessionDetail:
    profile = await _require_profile(db, current_user)
    result = await create_session_with_agent(
        db=db,
        profile=profile,
        initial_message=payload.initial_message,
    )
    await db.commit()
    schedule_outreach(result.outreach)
    schedule_mail(result.mail)
    await db.refresh(result.session)
    return await _session_detail(
        db,
        result.session,
        profile,
        messages=result.messages,
        request=result.request,
    )


@router.get("/sessions/{session_id}", response_model=BrokerSessionDetail)
async def get_session(
    session_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BrokerSessionDetail:
    profile = await _require_profile(db, current_user)
    session = await _get_owned_session(session_id, db, profile)
    return await _session_detail(db, session, profile)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    profile = await _require_profile(db, current_user)
    session = await _get_owned_session(session_id, db, profile)
    await delete_session_cascade(db, session)
    await db.commit()


@router.get("/sessions/{session_id}/request", response_model=BrokerRequestRead)
async def get_session_request_route(
    session_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BrokerRequestRead:
    profile = await _require_profile(db, current_user)
    session = await _get_owned_session(session_id, db, profile)
    request = await get_session_request(db, session.id)
    if request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="A brief has not been saved for this session yet.",
        )
    return BrokerRequestRead.from_request(request)


@router.post("/sessions/{session_id}/messages", response_model=list[BrokerMessageRead])
async def add_message(
    session_id: str,
    payload: BrokerMessageCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BrokerMessageRead]:
    profile = await _require_profile(db, current_user)
    session = await _get_owned_session(session_id, db, profile)
    try:
        turn = await handle_session_message(
            db=db,
            profile=profile,
            session=session,
            content=payload.content,
            attachment_ids=payload.attachment_ids,
            match_id=payload.match_id,
        )
    except MatchLaneError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AttachmentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    payload = await serialize_messages(db, turn.messages, viewer_user_id=profile.id)
    await db.commit()
    schedule_outreach(turn.outreach)
    schedule_mail(turn.mail)
    return payload


@router.get("/sessions/{session_id}/attachments", response_model=list[BrokerAttachmentRead])
async def list_attachments(
    session_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BrokerAttachmentRead]:
    profile = await _require_profile(db, current_user)
    await _get_owned_session(session_id, db, profile)
    return await serialize_session_attachments(db, session_id, viewer_user_id=profile.id)


@router.post(
    "/sessions/{session_id}/attachments",
    response_model=BrokerAttachmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment(
    session_id: str,
    file: UploadFile = File(...),
    caption: str | None = Form(default=None),
    request_id: str | None = Form(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BrokerAttachmentRead:
    profile = await _require_profile(db, current_user)
    session = await _get_owned_session(session_id, db, profile)
    data = await file.read()
    brief = await get_session_request(db, session.id)
    try:
        attachment = await create_file_attachment(
            db,
            user_id=profile.id,
            session_id=session.id,
            request_id=brief.id if brief else None,
            filename=file.filename or "upload",
            content_type=file.content_type,
            data=data,
            caption=caption,
            upload_request_id=request_id,
        )
    except (AttachmentError, StorageNotConfiguredError) as exc:
        raise _attachment_http_error(exc) from exc
    await db.commit()
    await db.refresh(attachment)
    return await to_attachment_read(attachment, include_secrets=True)


@router.post(
    "/sessions/{session_id}/links",
    response_model=BrokerAttachmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_link(
    session_id: str,
    payload: BrokerLinkCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BrokerAttachmentRead:
    profile = await _require_profile(db, current_user)
    session = await _get_owned_session(session_id, db, profile)
    brief = await get_session_request(db, session.id)
    try:
        attachment = await create_link_attachment(
            db,
            user_id=profile.id,
            session_id=session.id,
            request_id=brief.id if brief else None,
            url=payload.url,
            caption=payload.caption,
            upload_request_id=payload.request_id,
        )
    except AttachmentError as exc:
        raise _attachment_http_error(exc) from exc
    await db.commit()
    await db.refresh(attachment)
    return await to_attachment_read(attachment, include_secrets=True)


@router.patch("/attachments/{attachment_id}", response_model=BrokerAttachmentRead)
async def patch_attachment(
    attachment_id: str,
    payload: BrokerAttachmentPatch,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BrokerAttachmentRead:
    profile = await _require_profile(db, current_user)
    attachment = await db.get(AgentAttachment, attachment_id)
    if attachment is None or attachment.status != "ready" or attachment.user_id != profile.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    try:
        if payload.share_class:
            await classify_attachment(
                db,
                attachment,
                share_class=payload.share_class,
                label=payload.label,
                purpose=payload.purpose,
            )
        else:
            if payload.label:
                attachment.label = payload.label
            if payload.purpose:
                attachment.purpose = payload.purpose
            await db.flush()
    except AttachmentError as exc:
        raise _attachment_http_error(exc) from exc
    await db.commit()
    await db.refresh(attachment)
    return await to_attachment_read(attachment, include_secrets=True)


@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_attachment(
    attachment_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    profile = await _require_profile(db, current_user)
    attachment = await db.get(AgentAttachment, attachment_id)
    if attachment is None or attachment.status != "ready" or attachment.user_id != profile.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    await delete_attachment(db, attachment)
    await db.commit()


@router.get("/attachments/{attachment_id}/content")
async def download_attachment(
    attachment_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    profile = await _require_profile(db, current_user)
    attachment = await db.get(AgentAttachment, attachment_id)
    if attachment is None or attachment.status != "ready":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    if not await viewer_can_access(db, attachment, profile.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    if attachment.kind == "url" and attachment.url:
        return RedirectResponse(attachment.url)
    try:
        data, content_type = await load_attachment_bytes(attachment)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found") from exc
    except StorageNotConfiguredError as exc:
        raise _attachment_http_error(exc) from exc
    filename = sanitize_filename(attachment.original_filename or attachment.label or "file")
    return Response(
        content=data,
        media_type=content_type or attachment.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "private, max-age=300",
        },
    )


@router.post("/attachments/{attachment_id}/grants", response_model=BrokerAttachmentRead)
async def grant_attachment_share(
    attachment_id: str,
    payload: BrokerAttachmentGrantCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BrokerAttachmentRead:
    profile = await _require_profile(db, current_user)
    attachment = await db.get(AgentAttachment, attachment_id)
    if attachment is None or attachment.status != "ready" or attachment.user_id != profile.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    match = await _get_owned_match(payload.match_id, db, profile)
    try:
        await record_grant(
            db,
            attachment=attachment,
            match=match,
            user_id=profile.id,
            granted=payload.granted,
            source="ui",
        )
        await db.commit()
    except AttachmentError as exc:
        raise _attachment_http_error(exc) from exc
    await db.refresh(attachment)
    if payload.granted:
        try:
            brief = await get_session_request(db, attachment.session_id)
            if brief is None:
                source, candidate = await load_pair_requests(db, match)
                brief = source if source and source.user_id == profile.id else candidate
            if brief is not None:
                await share_attachment_to_match(
                    db,
                    match=match,
                    attachment=attachment,
                    from_request=brief,
                )
                await db.commit()
        except Exception:
            logger.exception(
                "share after grant failed attachment=%s match=%s",
                attachment_id,
                payload.match_id,
            )
            await db.rollback()
    return await to_attachment_read(attachment, include_secrets=True)
