from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser, get_current_user
from app.api.routes.users import get_profile_for_current_user
from app.db.models import (
    BrokerMatch,
    BrokerMediationEvent,
    BrokerMessage,
    BrokerPartyConnection,
    BrokerRequest,
    BrokerSession,
    UserProfile,
)
from app.db.session import get_db
from app.schemas.broker import (
    BrokerMessageCreate,
    BrokerMessageRead,
    BrokerMatchRead,
    BrokerMediationEventRead,
    BrokerPartyConnectionRead,
    BrokerRequestRead,
    BrokerRequestMatch,
    BrokerSessionCreate,
    BrokerSessionDetail,
    BrokerSessionRead,
)
from app.services.broker_orchestrator import (
    create_session_with_orchestration,
    handle_session_message_with_orchestration,
    process_stale_mediations,
)
from app.services.broker_contact import create_party_connection, share_match_contacts
from app.services.broker_rag import index_request, retrieve_similar_requests

router = APIRouter()


async def _get_session_request(
    db: AsyncSession,
    session_id: str,
) -> BrokerRequest | None:
    result = await db.execute(
        select(BrokerRequest).where(BrokerRequest.session_id == session_id)
    )
    return result.scalar_one_or_none()


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
) -> BrokerSession:
    broker_session = await db.get(BrokerSession, session_id)
    if broker_session is None or broker_session.user_id != profile.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Broker session not found",
        )
    return broker_session


async def _get_owned_match(
    match_id: str,
    db: AsyncSession,
    profile: UserProfile,
) -> BrokerMatch:
    broker_match = await db.get(BrokerMatch, match_id)
    if broker_match is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Broker match not found",
        )
    result = await db.execute(
        select(BrokerRequest).where(
            BrokerRequest.id.in_(
                [broker_match.source_request_id, broker_match.candidate_request_id]
            ),
            BrokerRequest.user_id == profile.id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Broker match not found",
        )
    return broker_match


@router.get("/sessions", response_model=list[BrokerSessionRead])
async def list_sessions(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BrokerSession]:
    profile = await _require_profile(db, current_user)
    result = await db.execute(
        select(BrokerSession)
        .where(BrokerSession.user_id == profile.id)
        .order_by(desc(BrokerSession.updated_at))
    )
    return list(result.scalars().all())


@router.get("/requests", response_model=list[BrokerRequestRead])
async def list_requests(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BrokerRequest]:
    profile = await _require_profile(db, current_user)
    result = await db.execute(
        select(BrokerRequest)
        .where(BrokerRequest.user_id == profile.id)
        .order_by(desc(BrokerRequest.updated_at))
    )
    return list(result.scalars().all())


@router.get("/requests/{request_id}/matches", response_model=list[BrokerRequestMatch])
async def get_request_matches(
    request_id: str,
    limit: int = 10,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BrokerRequestMatch]:
    profile = await _require_profile(db, current_user)
    broker_request = await db.get(BrokerRequest, request_id)
    if broker_request is None or broker_request.user_id != profile.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Broker request not found",
        )
    if broker_request.embedding_status != "embedded":
        await index_request(broker_request)
        await db.commit()
        await db.refresh(broker_request)
    if broker_request.embedding_status != "embedded":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Semantic indexing is not available for this request right now.",
        )
    try:
        matches = await retrieve_similar_requests(
            db,
            broker_request,
            min(max(limit, 1), 50),
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return [
        BrokerRequestMatch(
            request_id=request.id,
            title=request.title,
            summary=request.summary,
            request_type=request.request_type,
            category=request.category,
            status=request.status,
            distance=distance,
        )
        for request, distance in matches
    ]


@router.get("/requests/{request_id}/mediations", response_model=list[BrokerMatchRead])
async def list_request_mediations(
    request_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BrokerMatch]:
    profile = await _require_profile(db, current_user)
    broker_request = await db.get(BrokerRequest, request_id)
    if broker_request is None or broker_request.user_id != profile.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Broker request not found",
        )
    result = await db.execute(
        select(BrokerMatch)
        .where(
            (BrokerMatch.source_request_id == request_id)
            | (BrokerMatch.candidate_request_id == request_id)
        )
        .order_by(desc(BrokerMatch.updated_at))
    )
    return list(result.scalars().all())


@router.get("/matches/{match_id}", response_model=BrokerMatchRead)
async def get_match(
    match_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BrokerMatch:
    profile = await _require_profile(db, current_user)
    broker_match = await _get_owned_match(match_id, db, profile)
    return broker_match


@router.get("/matches/{match_id}/events", response_model=list[BrokerMediationEventRead])
async def list_match_events(
    match_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BrokerMediationEvent]:
    profile = await _require_profile(db, current_user)
    await _get_owned_match(match_id, db, profile)
    result = await db.execute(
        select(BrokerMediationEvent)
        .where(BrokerMediationEvent.match_id == match_id)
        .order_by(BrokerMediationEvent.created_at)
    )
    return list(result.scalars().all())


@router.post("/matches/{match_id}/skip", response_model=BrokerMatchRead)
async def skip_match(
    match_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BrokerMatch:
    profile = await _require_profile(db, current_user)
    broker_match = await _get_owned_match(match_id, db, profile)
    broker_match.status = "skipped"
    db.add(
        BrokerMediationEvent(
            match_id=broker_match.id,
            session_id=None,
            user_id=profile.id,
            event_type="match_skipped",
            payload={"reason": "manual_api_skip"},
        )
    )
    await db.commit()
    await db.refresh(broker_match)
    return broker_match


@router.post("/matches/{match_id}/share-contacts", response_model=list[BrokerMessageRead])
async def share_contacts(
    match_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BrokerMessage]:
    profile = await _require_profile(db, current_user)
    broker_match = await _get_owned_match(match_id, db, profile)
    if broker_match.status != "accepted":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Both parties must accept before contact details can be shared.",
        )
    try:
        messages = await share_match_contacts(db, broker_match)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    await db.commit()
    for message in messages:
        await db.refresh(message)
    return messages


@router.post("/matches/{match_id}/connect", response_model=BrokerPartyConnectionRead)
async def connect_parties(
    match_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BrokerPartyConnection:
    profile = await _require_profile(db, current_user)
    broker_match = await _get_owned_match(match_id, db, profile)
    if broker_match.status != "accepted":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Both parties must accept before a direct connection can be created.",
        )
    try:
        connection = await create_party_connection(db, broker_match)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    await db.commit()
    await db.refresh(connection)
    return connection


@router.post("/mediations/process-stale", response_model=list[BrokerMatchRead])
async def process_stale_mediations_route(
    limit: int = 50,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BrokerMatch]:
    await _require_profile(db, current_user)
    stale_matches = await process_stale_mediations(db, min(max(limit, 1), 100))
    await db.commit()
    for broker_match in stale_matches:
        await db.refresh(broker_match)
    return stale_matches


@router.post(
    "/sessions",
    response_model=BrokerSessionDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    payload: BrokerSessionCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BrokerSessionDetail:
    profile = await _require_profile(db, current_user)

    result = await create_session_with_orchestration(
        db=db,
        user_id=profile.id,
        initial_message=payload.initial_message,
    )
    await db.commit()
    await db.refresh(result.session)

    return BrokerSessionDetail(
        session=result.session,
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
    broker_session = await _get_owned_session(session_id, db, profile)
    result = await db.execute(
        select(BrokerMessage)
        .where(BrokerMessage.session_id == session_id)
        .order_by(BrokerMessage.created_at)
    )
    broker_request = await _get_session_request(db, session_id)
    return BrokerSessionDetail(
        session=broker_session,
        messages=list(result.scalars().all()),
        request=broker_request,
    )


@router.get("/sessions/{session_id}/request", response_model=BrokerRequestRead)
async def get_session_request(
    session_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BrokerRequest:
    profile = await _require_profile(db, current_user)
    broker_session = await _get_owned_session(session_id, db, profile)
    broker_request = await _get_session_request(db, broker_session.id)
    if broker_request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Structured request has not been created for this session.",
        )
    return broker_request


@router.post("/sessions/{session_id}/messages", response_model=list[BrokerMessageRead])
async def add_message(
    session_id: str,
    payload: BrokerMessageCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BrokerMessage]:
    profile = await _require_profile(db, current_user)
    broker_session = await _get_owned_session(session_id, db, profile)
    messages = await handle_session_message_with_orchestration(
        db=db,
        broker_session=broker_session,
        content=payload.content,
    )
    await db.commit()
    for message in messages:
        await db.refresh(message)
    return messages
