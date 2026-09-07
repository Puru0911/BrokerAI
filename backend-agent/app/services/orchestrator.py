from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context import ToolContext
from app.agents.runtime import run_broker_turn
from app.db.models import (
    AgentAttachment,
    AgentMatch,
    AgentMessage,
    AgentRequest,
    AgentSession,
    UserProfile,
)
from app.services.attachments import (
    attach_to_message,
    ingest_urls_from_text,
    upload_notice,
)
from app.services.titles import WELCOME_MESSAGE, create_title
from app.services.workflow import (
    MATCH_OPEN,
    add_event,
    clear_waiting_for_match,
    get_session_request,
)

logger = logging.getLogger(__name__)


@dataclass
class SessionCreationResult:
    session: AgentSession
    messages: list[AgentMessage]
    request: AgentRequest | None


async def create_session_with_agent(
    db: AsyncSession,
    profile: UserProfile,
    initial_message: str | None,
) -> SessionCreationResult:
    normalized = initial_message.strip() if initial_message else None
    session = AgentSession(
        user_id=profile.id,
        title=create_title(normalized),
        status="open",
        summary=normalized,
    )
    db.add(session)
    await db.flush()

    messages: list[AgentMessage] = []
    if not normalized:
        welcome = AgentMessage(
            session_id=session.id,
            role="assistant",
            content=WELCOME_MESSAGE,
        )
        db.add(welcome)
        await db.flush()
        logger.info("session created session=%s user=%s has_initial_message=false", session.id, profile.id)
        return SessionCreationResult(session=session, messages=[welcome], request=None)

    user_message = AgentMessage(session_id=session.id, role="user", content=normalized)
    db.add(user_message)
    await db.flush()
    messages.append(user_message)
    ingested = await ingest_urls_from_text(
        db,
        user_id=profile.id,
        session_id=session.id,
        request_id=None,
        message=user_message,
        text=normalized,
    )

    ctx = ToolContext(
        db=db,
        profile=profile,
        session=session,
        request=None,
        user_message=user_message,
        trigger="user_message",
        new_attachment_ids=[item.id for item in ingested],
    )
    logger.info("session created session=%s user=%s has_initial_message=true", session.id, profile.id)
    replies = await _run_turn_safely(ctx)
    messages.extend(replies)
    request = await get_session_request(db, session.id)
    return SessionCreationResult(session=session, messages=messages, request=request)


async def handle_session_message(
    db: AsyncSession,
    profile: UserProfile,
    session: AgentSession,
    content: str,
    attachment_ids: list[str] | None = None,
) -> list[AgentMessage]:
    request = await get_session_request(db, session.id)
    linked_ids = list(dict.fromkeys(attachment_ids or []))
    user_message = AgentMessage(session_id=session.id, role="user", content=content.strip())
    db.add(user_message)
    await db.flush()

    new_attachment_ids: list[str] = []
    if linked_ids:
        linked = await attach_to_message(
            db,
            user_id=profile.id,
            session_id=session.id,
            message=user_message,
            attachment_ids=linked_ids,
        )
        new_attachment_ids.extend(item.id for item in linked)
        if not user_message.content.strip():
            user_message.content = upload_notice(linked, "")
    ingested = await ingest_urls_from_text(
        db,
        user_id=profile.id,
        session_id=session.id,
        request_id=request.id if request else None,
        message=user_message,
        text=user_message.content,
    )
    new_attachment_ids.extend(item.id for item in ingested)
    if request is not None:
        for attachment_id in new_attachment_ids:
            attachment = await db.get(AgentAttachment, attachment_id)
            if attachment is not None and attachment.request_id is None:
                attachment.request_id = request.id

    ctx = ToolContext(
        db=db,
        profile=profile,
        session=session,
        request=request,
        user_message=user_message,
        trigger="user_message",
        new_attachment_ids=new_attachment_ids,
    )
    logger.info(
        "user message session=%s has_request=%s indexed=%s",
        session.id,
        request is not None,
        request.indexed_at is not None if request else False,
    )
    replies = await _run_turn_safely(ctx)
    return [user_message, *replies]


async def process_stale_matches(db: AsyncSession, limit: int = 50) -> list[AgentMatch]:
    result = await db.execute(
        select(AgentMatch)
        .where(
            AgentMatch.status == MATCH_OPEN,
            AgentMatch.expires_at.is_not(None),
            AgentMatch.expires_at <= datetime.now(UTC),
        )
        .order_by(AgentMatch.expires_at)
        .limit(limit)
    )
    stale = list(result.scalars().all())
    for match in stale:
        match.status = "closed"
        match.close_reason = "expired"
        await clear_waiting_for_match(db, match)
        await add_event(
            db,
            match_id=match.id,
            event_type="match_expired",
            payload={"reason": "timeout"},
        )
        source_request = await db.get(AgentRequest, match.source_request_id)
        if source_request is None:
            continue
        session = await db.get(AgentSession, source_request.session_id)
        profile = await db.get(UserProfile, source_request.user_id)
        if session is None or profile is None:
            continue
        try:
            ctx = ToolContext(
                db=db,
                profile=profile,
                session=session,
                request=source_request,
                user_message=None,
                trigger="match_timeout",
                trigger_match_id=match.id,
            )
            await run_broker_turn(ctx)
        except Exception as exc:
            logger.warning("stale-match broker turn failed match_id=%s", match.id, exc_info=exc)
    return stale


async def _run_turn_safely(ctx: ToolContext) -> list[AgentMessage]:
    """Run the agent and always persist a user-visible reply if it fails."""
    try:
        replies = await run_broker_turn(ctx)
        if replies:
            return replies
    except Exception as exc:
        logger.warning(
            "broker turn failed session=%s trigger=%s",
            ctx.session.id,
            ctx.trigger,
            exc_info=exc,
        )
    fallback = AgentMessage(
        session_id=ctx.session.id,
        role="assistant",
        content=(
            "I hit a problem continuing this request. Please try that last "
            "message again in a moment."
        ),
    )
    ctx.db.add(fallback)
    await ctx.db.flush()
    return [fallback]
