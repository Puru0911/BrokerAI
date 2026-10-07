"""Queue transactional mail after broker activity commits."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import time
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context import MailJob
from app.agents.prompts import NATURAL_FALLBACK_REPLY, UNAVAILABLE_REPLY
from app.core.config import settings
from app.db.models import (
    AgentMailLog,
    AgentMatch,
    AgentMessage,
    AgentRequest,
    AgentSession,
    UserProfile,
)
from app.db.session import AsyncSessionLocal
from app.services.contact import parse_contact_card
from app.services.introduction import parse_connect_offer, pending_offer_for_session
from app.services.mail_templates import (
    MailContent,
    contacts_mail,
    intro_mail,
    outreach_mail,
    preview_for_mail,
)
from app.services.mailer import send_email
from app.services.realtime import hub

logger = logging.getLogger(__name__)

STATUS_SENT = "sent"
STATUS_SKIPPED_ONLINE = "skipped_online"
STATUS_SKIPPED_NO_EMAIL = "skipped_no_email"
STATUS_SKIPPED_DISABLED = "skipped_disabled"
STATUS_SKIPPED_UNCONFIGURED = "skipped_unconfigured"
STATUS_FAILED = "failed"


def schedule_mail(jobs: list[MailJob]) -> None:
    """Start delivery after the current request has committed. Does not wait."""
    for job in jobs:
        asyncio.create_task(
            _deliver_job(job),
            name=f"mail-{job.kind}-{job.source_id}",
        )


async def _deliver_job(job: MailJob) -> None:
    try:
        async with AsyncSessionLocal() as db:
            await deliver_mail(db, job)
            await db.commit()
    except Exception:
        logger.exception(
            "mail job failed kind=%s source_id=%s user_id=%s",
            job.kind,
            job.source_id,
            job.user_id,
        )


def _user_facing_assistant(message: AgentMessage) -> str | None:
    if message.role != "assistant":
        return None
    text = (message.content or "").strip()
    if not text:
        return None
    if text in {NATURAL_FALLBACK_REPLY, UNAVAILABLE_REPLY}:
        return None
    if parse_contact_card(text) or parse_connect_offer(text):
        return None
    if text.startswith("{") and '"kind"' in text:
        return None
    return text


async def mail_jobs_for_outreach(
    db: AsyncSession,
    *,
    session: AgentSession,
    profile: UserProfile,
    replies: list[AgentMessage],
) -> list[MailJob]:
    prose: list[tuple[AgentMessage, str]] = []
    for message in replies:
        text = _user_facing_assistant(message)
        if text:
            prose.append((message, text))
    offer = await pending_offer_for_session(db, session.id)
    if prose:
        message, text = prose[-1]
        return [
            MailJob(
                kind="broker_outreach",
                user_id=profile.id,
                session_id=session.id,
                source_id=message.id,
                title=session.title,
                preview=preview_for_mail(text),
                offer_prompt=offer.prompt if offer is not None else None,
            )
        ]
    if offer is not None:
        return [
            MailJob(
                kind="intro_offered",
                user_id=profile.id,
                session_id=session.id,
                source_id=offer.id,
                title=session.title,
                offer_prompt=offer.prompt,
            )
        ]
    return []


async def mail_jobs_for_contacts(
    db: AsyncSession,
    match: AgentMatch,
    messages: list[AgentMessage],
) -> list[MailJob]:
    if not messages:
        return []
    source = await db.get(AgentRequest, match.source_request_id)
    candidate = await db.get(AgentRequest, match.candidate_request_id)
    if source is None or candidate is None:
        return []
    source_profile = await db.get(UserProfile, source.user_id)
    candidate_profile = await db.get(UserProfile, candidate.user_id)
    source_name = source_profile.name if source_profile is not None else "the other person"
    candidate_name = (
        candidate_profile.name if candidate_profile is not None else "the other person"
    )
    jobs: list[MailJob] = []
    seen: set[str] = set()
    for message in messages:
        if message.session_id == source.session_id:
            user_id = source.user_id
            peer_name = candidate_name
        elif message.session_id == candidate.session_id:
            user_id = candidate.user_id
            peer_name = source_name
        else:
            continue
        if user_id in seen:
            continue
        seen.add(user_id)
        jobs.append(
            MailJob(
                kind="contacts_delivered",
                user_id=user_id,
                session_id=message.session_id,
                source_id=f"{match.id}:{user_id}",
                peer_name=peer_name,
            )
        )
    return jobs


def unsubscribe_url(user_id: str) -> str:
    return f"{settings.public_app_url}/mail/unsubscribe?token={quote(unsubscribe_token(user_id))}"


def unsubscribe_token(user_id: str, *, ttl_seconds: int = 60 * 60 * 24 * 730) -> str:
    expiry = int(time.time()) + ttl_seconds
    payload = f"{user_id}:{expiry}"
    digest = hmac.new(
        settings.mail_signing_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]
    return f"{payload}:{digest}"


def parse_unsubscribe_token(token: str) -> str | None:
    parts = (token or "").split(":")
    if len(parts) != 3:
        return None
    user_id, expiry_raw, digest = parts
    if not user_id or not expiry_raw.isdigit():
        return None
    if int(expiry_raw) < int(time.time()):
        return None
    payload = f"{user_id}:{expiry_raw}"
    expected = hmac.new(
        settings.mail_signing_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]
    if not hmac.compare_digest(digest, expected):
        return None
    return user_id


def _content_for_job(job: MailJob, unsub: str) -> MailContent:
    if job.kind == "intro_offered":
        return intro_mail(
            session_title=job.title or "",
            offer_prompt=job.offer_prompt or "Ready to be introduced?",
            session_id=job.session_id,
            unsubscribe_url=unsub,
        )
    if job.kind == "contacts_delivered":
        return contacts_mail(
            peer_name=job.peer_name or "the other person",
            session_id=job.session_id,
            unsubscribe_url=unsub,
        )
    return outreach_mail(
        session_title=job.title or "",
        preview=job.preview or "There's a new message in your request.",
        session_id=job.session_id,
        offer_prompt=job.offer_prompt,
        unsubscribe_url=unsub,
    )


async def _existing_log(db: AsyncSession, kind: str, source_id: str) -> AgentMailLog | None:
    result = await db.execute(
        select(AgentMailLog).where(
            AgentMailLog.kind == kind,
            AgentMailLog.source_id == source_id,
        )
    )
    return result.scalar_one_or_none()


async def _record(
    db: AsyncSession,
    job: MailJob,
    *,
    status: str,
    resend_id: str | None = None,
    error: str | None = None,
) -> AgentMailLog:
    existing = await _existing_log(db, job.kind, job.source_id)
    if existing is not None:
        existing.status = status
        existing.resend_id = resend_id
        existing.error = error
        await db.flush()
        return existing
    row = AgentMailLog(
        user_id=job.user_id,
        kind=job.kind,
        source_id=job.source_id,
        session_id=job.session_id,
        status=status,
        resend_id=resend_id,
        error=error,
    )
    db.add(row)
    await db.flush()
    return row


async def deliver_mail(db: AsyncSession, job: MailJob) -> AgentMailLog:
    existing = await _existing_log(db, job.kind, job.source_id)
    if existing is not None and existing.status == STATUS_SENT:
        return existing

    profile = await db.get(UserProfile, job.user_id)
    if profile is None or not (profile.email or "").strip():
        return await _record(db, job, status=STATUS_SKIPPED_NO_EMAIL)

    if not getattr(profile, "notify_email", True):
        return await _record(db, job, status=STATUS_SKIPPED_DISABLED)

    if hub.is_online(job.user_id):
        return await _record(db, job, status=STATUS_SKIPPED_ONLINE)

    if not settings.can_send_mail:
        return await _record(db, job, status=STATUS_SKIPPED_UNCONFIGURED)

    unsub = unsubscribe_url(job.user_id)
    content = _content_for_job(job, unsub)
    try:
        resend_id = await send_email(
            to=profile.email.strip(),
            subject=content.subject,
            text=content.text,
            html=content.html,
            unsubscribe_url=unsub,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "mail send failed kind=%s user=%s error=%s",
            job.kind,
            job.user_id,
            exc,
        )
        return await _record(db, job, status=STATUS_FAILED, error=str(exc)[:500])

    if resend_id is None:
        return await _record(db, job, status=STATUS_SKIPPED_UNCONFIGURED)
    return await _record(db, job, status=STATUS_SENT, resend_id=resend_id)
