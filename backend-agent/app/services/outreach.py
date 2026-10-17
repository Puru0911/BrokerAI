"""Fire-and-forget broker turns on the other party's session."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context import MailJob, OutreachJob, ToolContext
from app.agents.runtime import run_broker_turn
from app.db.models import AgentMatch, AgentRequest, AgentSession, UserProfile
from app.db.session import AsyncSessionLocal
from app.services.notify import mail_jobs_for_outreach, schedule_mail
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
        if not job.match_id:
            logger.info(
                "outreach skipped reason=no_match_id from_session=%s to_request=%s",
                job.from_session_id,
                job.to_request_id,
            )
            continue
        label = job.match_id
        asyncio.create_task(_run_outreach_job(job), name=f"outreach-{label}-{job.to}")


def schedule_match_kickoff(
    *,
    match_id: str,
    session_id: str,
    request_id: str,
    user_id: str,
    context: str,
) -> None:
    """Run a request_ready turn on this person's new match lane after Interested."""
    asyncio.create_task(
        _run_match_kickoff(
            match_id=match_id,
            session_id=session_id,
            request_id=request_id,
            user_id=user_id,
            context=context,
        ),
        name=f"kickoff-{match_id}",
    )


async def _run_match_kickoff(
    *,
    match_id: str,
    session_id: str,
    request_id: str,
    user_id: str,
    context: str,
) -> None:
    try:
        async with AsyncSessionLocal() as db:
            mail, outreach = await run_interested_kickoff_turn(
                db,
                match_id=match_id,
                session_id=session_id,
                request_id=request_id,
                user_id=user_id,
                context=context,
            )
            await db.commit()
            if outreach:
                schedule_outreach(outreach)
            if mail:
                schedule_mail(mail)
    except Exception:
        logger.exception(
            "interested kickoff failed match_id=%s session=%s",
            match_id,
            session_id,
        )


async def _run_outreach_job(job: OutreachJob) -> None:
    try:
        async with AsyncSessionLocal() as db:
            mail = await run_match_context_turn(db, job)
            await db.commit()
            schedule_mail(mail)
    except Exception:
        logger.exception(
            "outreach turn failed match_id=%s to_request=%s to=%s from_session=%s",
            job.match_id,
            job.to_request_id,
            job.to,
            job.from_session_id,
        )


async def run_interested_kickoff_turn(
    db: AsyncSession,
    *,
    match_id: str,
    session_id: str,
    request_id: str,
    user_id: str,
    context: str,
) -> tuple[list[MailJob], list[OutreachJob]]:
    match = await db.get(AgentMatch, match_id)
    if match is None or match.status not in {MATCH_OPEN, MATCH_ACCEPTED}:
        logger.info("kickoff skipped match_id=%s reason=match_unavailable", match_id)
        return [], []
    session = await db.get(AgentSession, session_id)
    profile = await db.get(UserProfile, user_id)
    request = await db.get(AgentRequest, request_id)
    if session is None or profile is None or request is None:
        logger.info("kickoff skipped match_id=%s reason=missing_session", match_id)
        return [], []
    ctx = ToolContext(
        db=db,
        profile=profile,
        session=session,
        request=request,
        user_message=None,
        trigger="request_ready",
        trigger_match_id=match.id,
        focus_match_id=match.id,
        outreach_context=context,
    )
    logger.info(
        "interested kickoff start match_id=%s session=%s",
        match.id,
        session.id,
    )
    replies = await run_broker_turn(ctx)
    mail = await mail_jobs_for_outreach(
        db,
        session=session,
        profile=profile,
        replies=replies,
    )
    if ctx.queued_mail:
        mail.extend(ctx.queued_mail)
    return mail, list(ctx.queued_outreach)


async def run_match_context_turn(db: AsyncSession, job: OutreachJob) -> list[MailJob]:
    """Same broker loop as a user message, on the recipient's session, no user text."""
    if not job.match_id:
        logger.info("outreach skipped reason=missing_match from_session=%s", job.from_session_id)
        return []
    match = await db.get(AgentMatch, job.match_id)
    if match is None or match.status not in {MATCH_OPEN, MATCH_ACCEPTED}:
        logger.info("outreach skipped match_id=%s reason=match_unavailable", job.match_id)
        return []
    source, candidate = await load_pair_requests(db, match)
    if source is None or candidate is None:
        logger.info("outreach skipped match_id=%s reason=missing_party", job.match_id)
        return []
    target = request_for_role(match, source, candidate, job.to)
    session = await db.get(AgentSession, target.session_id)
    profile = await db.get(UserProfile, target.user_id)
    if session is None or profile is None:
        logger.info("outreach skipped match_id=%s reason=missing_session_or_profile", job.match_id)
        return []

    ctx = ToolContext(
        db=db,
        profile=profile,
        session=session,
        request=target,
        user_message=None,
        trigger="match_context",
        trigger_match_id=match.id,
        focus_match_id=match.id,
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
    mail = await mail_jobs_for_outreach(
        db,
        session=session,
        profile=profile,
        replies=replies,
    )
    if ctx.queued_mail:
        mail.extend(ctx.queued_mail)
    return mail
