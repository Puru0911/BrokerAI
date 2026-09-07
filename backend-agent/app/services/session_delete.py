from __future__ import annotations

import asyncio
import logging

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentMatch, AgentRequest, AgentSession
from app.rag.store import get_vector_store
from app.services.attachments import delete_session_files
from app.services.workflow import clear_waiting, list_matches_for_request

logger = logging.getLogger(__name__)


async def delete_session_cascade(db: AsyncSession, session: AgentSession) -> None:
    """Delete a chat session, its brief, matches, events, and Chroma vector."""
    result = await db.execute(
        select(AgentRequest).where(AgentRequest.session_id == session.id)
    )
    request = result.scalar_one_or_none()
    if request is not None:
        matches = await list_matches_for_request(db, request.id, limit=100)
        counterpart_ids = {
            match.source_request_id
            if match.source_request_id != request.id
            else match.candidate_request_id
            for match in matches
        }
        match_ids = {match.id for match in matches}
        for counterpart_id in counterpart_ids:
            counterpart = await db.get(AgentRequest, counterpart_id)
            if counterpart is None:
                continue
            if counterpart.waiting_match_id in match_ids:
                clear_waiting(counterpart, counterpart.waiting_match_id)
        request_id = request.id
        try:
            await asyncio.to_thread(get_vector_store().delete_request, request_id)
        except Exception as exc:
            logger.warning(
                "Chroma delete failed for request",
                exc_info=exc,
                extra={"request_id": request_id, "session_id": session.id},
            )
        leftover = await db.execute(
            select(AgentMatch).where(
                or_(
                    AgentMatch.source_request_id == request.id,
                    AgentMatch.candidate_request_id == request.id,
                )
            )
        )
        for match in leftover.scalars().all():
            await db.delete(match)
        await db.delete(request)

    await delete_session_files(db, session.id)
    await db.delete(session)
    await db.flush()
