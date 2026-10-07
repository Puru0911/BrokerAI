"""Resend HTTP client for transactional mail."""

from __future__ import annotations

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


async def send_email(
    *,
    to: str,
    subject: str,
    text: str,
    html: str,
    unsubscribe_url: str | None = None,
) -> str | None:
    """Send one message through Resend. Returns the provider id, or None if skipped."""
    if not settings.can_send_mail:
        logger.info("mail skipped reason=not_configured to=%s subject=%s", to, subject[:80])
        return None

    payload: dict[str, object] = {
        "from": f"{settings.mail_from_name} <{settings.MAIL_FROM}>",
        "to": [to],
        "subject": subject,
        "text": text,
        "html": html,
    }
    if settings.MAIL_REPLY_TO and settings.MAIL_REPLY_TO.strip():
        payload["reply_to"] = settings.MAIL_REPLY_TO.strip()
    if unsubscribe_url:
        payload["headers"] = {"List-Unsubscribe": f"<{unsubscribe_url}>"}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                settings.RESEND_API_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
            )
    except Exception:
        logger.exception("mail transport failed to=%s", to)
        raise

    if response.status_code >= 400:
        logger.warning(
            "mail rejected status=%s to=%s body=%s",
            response.status_code,
            to,
            response.text[:300],
        )
        response.raise_for_status()

    data = response.json() if response.content else {}
    provider_id = data.get("id") if isinstance(data, dict) else None
    logger.info("mail sent to=%s resend_id=%s subject=%s", to, provider_id, subject[:80])
    return str(provider_id) if provider_id else None
