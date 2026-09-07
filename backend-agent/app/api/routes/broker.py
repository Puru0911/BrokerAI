from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import RedirectResponse
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
    BrokerEventRead,
    BrokerLinkCreate,
    BrokerMatchRead,
    BrokerMessageCreate,
    BrokerMessageRead,
    BrokerPartyConnectionRead,
    BrokerRequestMatch,
    BrokerRequestRead,
    BrokerSessionCreate,
    BrokerSessionDetail,
    BrokerSessionRead,
)
from app.services.attachments import (
    AttachmentError,
    classify_attachment,
    create_file_attachment,
    create_link_attachment,
    delete_attachment,
    list_pending_upload_requests,
    record_grant,
    serialize_messages,
    serialize_session_attachments,
    serialize_upload_requests,
    share_attachment_to_match,
    signed_content_url,
    to_attachment_read,
    viewer_can_access,
)
from app.services.contact import create_party_connection, share_match_contacts
from app.services.orchestrator import (
    create_session_with_agent,
    handle_session_message,
    process_stale_matches,
)
from app.services.session_delete import delete_session_cascade
from app.services.storage import StorageNotConfiguredError
from app.services.workflow import get_session_request, load_pair_requests

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
    if session is None or session.user_id != profile.id:
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
        select(AgentRequest).where(
            AgentRequest.id.in_([match.source_request_id, match.candidate_request_id]),
            AgentRequest.user_id == profile.id,
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
            .order_by(AgentMessage.created_at)
        )
        messages = list(result.scalars().all())
    if request is None:
        request = await get_session_request(db, session.id)
    return BrokerSessionDetail(
        session=BrokerSessionRead.model_validate(session),
        messages=await serialize_messages(db, messages, viewer_user_id=profile.id),
        request=BrokerRequestRead.from_request(request) if request else None,
        attachments=await serialize_session_attachments(
            db, session.id, viewer_user_id=profile.id
        ),
        pending_upload_requests=serialize_upload_requests(
            await list_pending_upload_requests(db, session.id)
        ),
    )


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
) -> list[AgentSession]:
    profile = await _require_profile(db, current_user)
    result = await db.execute(
        select(AgentSession)
        .where(AgentSession.user_id == profile.id)
        .order_by(desc(AgentSession.updated_at))
    )
    return list(result.scalars().all())


@router.get("/requests", response_model=list[BrokerRequestRead])
async def list_requests(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BrokerRequestRead]:
    profile = await _require_profile(db, current_user)
    result = await db.execute(
        select(AgentRequest)
        .where(AgentRequest.user_id == profile.id)
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
    for message in messages:
        await db.refresh(message)
    return await serialize_messages(db, messages, viewer_user_id=profile.id)


@router.post("/matches/{match_id}/connect", response_model=BrokerPartyConnectionRead)
async def connect_parties(
    match_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BrokerPartyConnectionRead:
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
    await db.commit()
    await db.refresh(connection)
    return connection


@router.post("/mediations/process-stale", response_model=list[BrokerMatchRead])
async def process_stale_route(
    limit: int = 50,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AgentMatch]:
    await _require_profile(db, current_user)
    stale = await process_stale_matches(db, min(max(limit, 1), 100))
    await db.commit()
    for match in stale:
        await db.refresh(match)
    return stale


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
        messages = await handle_session_message(
            db=db,
            profile=profile,
            session=session,
            content=payload.content,
            attachment_ids=payload.attachment_ids,
        )
    except AttachmentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    for message in messages:
        await db.refresh(message)
    return await serialize_messages(db, messages, viewer_user_id=profile.id)


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
) -> RedirectResponse:
    profile = await _require_profile(db, current_user)
    attachment = await db.get(AgentAttachment, attachment_id)
    if attachment is None or attachment.status != "ready":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    if not await viewer_can_access(db, attachment, profile.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    if attachment.kind == "url" and attachment.url:
        return RedirectResponse(attachment.url)
    content_url = await signed_content_url(attachment)
    if not content_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="File storage is not available right now.",
        )
    return RedirectResponse(content_url)


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
    await record_grant(
        db,
        attachment=attachment,
        match=match,
        user_id=profile.id,
        granted=payload.granted,
        source="ui",
    )
    if payload.granted:
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
    await db.refresh(attachment)
    return await to_attachment_read(attachment, include_secrets=True)
