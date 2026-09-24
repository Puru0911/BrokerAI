"""Fire-and-forget broker turns on the other party's session."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context import OutreachJob, ToolContext
from app.agents.runtime import run_broker_turn
from app.db.models import AgentMatch, AgentSession, UserProfile
from app.db.session import AsyncSessionLocal
from app.services.workflow import (
    MATCH_ACCEPTED,
    MATCH_OPEN,
    expiry_from_now,
    load_pair_requests,
    request_for_role,
    set_outstanding_question,
)

logger = logging.getLogger(__name__)


def schedule_outreach(jobs: list[OutreachJob]) -> None:
    """Start other-session turns after the current request has committed. Does not wait."""
    for job in jobs:
        asyncio.create_task(_run_outreach_job(job), name=f"outreach-{job.match_id}-{job.to}")


async def _run_outreach_job(job: OutreachJob) -> None:
    try:
        async with AsyncSessionLocal() as db:
            await run_match_context_turn(db, job)
            await db.commit()
    except Exception:
        logger.exception(
            "outreach turn failed match_id=%s to=%s from_session=%s",
            job.match_id,
            job.to,
            job.from_session_id,
        )


async def run_match_context_turn(db: AsyncSession, job: OutreachJob) -> None:
    """Same broker loop as a user message, on the recipient's session, no user text."""
    match = await db.get(AgentMatch, job.match_id)
    if match is None or match.status not in {MATCH_OPEN, MATCH_ACCEPTED}:
        logger.info("outreach skipped match_id=%s reason=match_unavailable", job.match_id)
        return
    source, candidate = await load_pair_requests(db, match)
    if source is None or candidate is None:
        logger.info("outreach skipped match_id=%s reason=missing_party", job.match_id)
        return
    target = request_for_role(match, source, candidate, job.to)
    session = await db.get(AgentSession, target.session_id)
    profile = await db.get(UserProfile, target.user_id)
    if session is None or profile is None:
        logger.info("outreach skipped match_id=%s reason=missing_session_or_profile", job.match_id)
        return

    ctx = ToolContext(
        db=db,
        profile=profile,
        session=session,
        request=target,
        user_message=None,
        trigger="match_context",
        trigger_match_id=match.id,
        outreach_context=job.context,
    )
    logger.info(
        "outreach turn start match_id=%s to=%s session=%s from_session=%s",
        job.match_id,
        job.to,
        session.id,
        job.from_session_id,
    )
    replies = await run_broker_turn(ctx)
    if replies:
        set_outstanding_question(
            match,
            waiting_on=job.to,
            question=replies[-1].content,
        )
        target.waiting_match_id = match.id
        match.last_activity_at = datetime.now(UTC)
        match.expires_at = expiry_from_now()
    if ctx.queued_outreach:
        logger.info(
            "outreach ignored nested queue match_id=%s count=%s",
            job.match_id,
            len(ctx.queued_outreach),
        )
