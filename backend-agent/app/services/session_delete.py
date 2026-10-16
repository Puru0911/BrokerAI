from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentMatch, AgentMessage, AgentRequest, AgentSession
from app.rag.store import get_vector_store
from app.services.attachments import delete_session_files
from app.services.introduction import dismiss_pending_offers_for_match
from app.services.workflow import (
    CLOSE_REQUEST_CLOSED,
    MATCH_CLOSED,
    REQUEST_CLOSED,
    add_event,
    clear_waiting,
    clear_waiting_for_match,
    counterpart_request_id,
    list_matches_for_request,
)

logger = logging.getLogger(__name__)

SESSION_DELETED = "deleted"
COUNTERPART_LEFT_MATCH_REPLY = (
    "The other person is no longer in this match. This conversation is closed."
)


async def delete_session_cascade(db: AsyncSession, session: AgentSession) -> None:
    """Remove a session from this user. Live matches stay as closed lanes for the other party."""
    result = await db.execute(
        select(AgentRequest).where(AgentRequest.session_id == session.id)
    )
    request = result.scalar_one_or_none()
    if request is None:
        await delete_session_files(db, session.id)
        await db.delete(session)
        await db.flush()
        return

    matches = await list_matches_for_request(db, request.id, limit=100)
    await _drop_request_from_index(request.id, session.id)
    if not matches:
        await db.delete(request)
        await delete_session_files(db, session.id)
        await db.delete(session)
        await db.flush()
        return

    for match in matches:
        await _close_match_for_deleted_request(db, request, match)

    request.status = REQUEST_CLOSED
    session.status = SESSION_DELETED
    await delete_session_files(db, session.id)
    await db.flush()


async def _drop_request_from_index(request_id: str, session_id: str) -> None:
    try:
        await asyncio.to_thread(get_vector_store().delete_request, request_id)
    except Exception as exc:
        logger.warning(
            "Chroma delete failed for request",
            exc_info=exc,
            extra={"request_id": request_id, "session_id": session_id},
        )


async def _close_match_for_deleted_request(
    db: AsyncSession,
    request: AgentRequest,
    match: AgentMatch,
) -> None:
    was_live = match.status != MATCH_CLOSED
    if was_live:
        match.status = MATCH_CLOSED
        match.close_reason = CLOSE_REQUEST_CLOSED
        match.last_activity_at = datetime.now(UTC)
        await dismiss_pending_offers_for_match(db, match.id)
        await clear_waiting_for_match(db, match)
        await add_event(
            db,
            match_id=match.id,
            event_type="match_closed",
            session_id=request.session_id,
            user_id=request.user_id,
            payload={"reason": CLOSE_REQUEST_CLOSED},
        )
    clear_waiting(request, match.id)
    other_id = counterpart_request_id(match, request)
    other = await db.get(AgentRequest, other_id)
    if other is None:
        return
    if other.waiting_match_id == match.id:
        clear_waiting(other, match.id)
    if not was_live:
        return
    notice = AgentMessage(
        session_id=other.session_id,
        role="assistant",
        content=COUNTERPART_LEFT_MATCH_REPLY,
        match_id=match.id,
    )
    db.add(notice)
    await db.flush()
