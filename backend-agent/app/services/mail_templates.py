"""Plain-text and HTML bodies for activity mail."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass

from app.core.config import settings

CREAM = "#F4F1EC"
TEAL = "#0F5C56"
INK = "#1C1917"
MUTED = "#78716C"


@dataclass(frozen=True)
class MailContent:
    subject: str
    text: str
    html: str


def preview_for_mail(content: str, *, limit: int = 280) -> str:
    """User-facing preview. JSON cards collapse to a short label."""
    text = (content or "").strip()
    if not text:
        return ""
    if text.startswith(("{", "[")):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            kind = str(payload.get("kind") or "")
            if kind == "broker_contact_card":
                name = ""
                contact = payload.get("contact")
                if isinstance(contact, dict):
                    name = str(contact.get("name") or "").strip()
                return f"You're introduced{f' to {name}' if name else ''}."
            if kind == "broker_connect_offer":
                prompt = str(payload.get("prompt") or "Ready to be introduced?").strip()
                return prompt
            title = str(payload.get("title") or "").strip()
            if title:
                return title
            return "There's an update in your chat."
    collapsed = re.sub(r"\s+", " ", text).strip()
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[: limit - 3].rstrip()}..."


def session_url(session_id: str) -> str:
    return f"{settings.public_app_url}/app?session={session_id}"


def _layout(*, title: str, preview: str, cta_url: str, cta_label: str, footer: str) -> MailContent:
    product = settings.mail_from_name
    subject = title
    text = "\n".join(
        part
        for part in (
            preview,
            "",
            f"{cta_label}: {cta_url}",
            "",
            footer,
        )
        if part is not None
    )
    safe_preview = html.escape(preview).replace("\n", "<br>")
    html_body = f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:{CREAM};color:{INK};font-family:Georgia,'Times New Roman',serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:{CREAM};padding:32px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" width="560" cellspacing="0" cellpadding="0" style="max-width:560px;background:#fff;border-radius:16px;padding:32px 28px;">
          <tr>
            <td style="font-size:12px;letter-spacing:0.14em;text-transform:uppercase;color:{TEAL};font-family:system-ui,sans-serif;font-weight:600;">
              {html.escape(product)}
            </td>
          </tr>
          <tr>
            <td style="padding-top:16px;font-size:22px;line-height:1.3;color:{INK};">{html.escape(title)}</td>
          </tr>
          <tr>
            <td style="padding-top:16px;font-size:16px;line-height:1.55;color:{INK};">{safe_preview}</td>
          </tr>
          <tr>
            <td style="padding-top:28px;">
              <a href="{html.escape(cta_url)}" style="display:inline-block;background:{TEAL};color:{CREAM};text-decoration:none;font-family:system-ui,sans-serif;font-size:14px;font-weight:600;padding:12px 18px;border-radius:10px;">
                {html.escape(cta_label)}
              </a>
            </td>
          </tr>
          <tr>
            <td style="padding-top:28px;font-size:12px;line-height:1.5;color:{MUTED};font-family:system-ui,sans-serif;">
              {html.escape(footer)}
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
    return MailContent(subject=subject, text=text, html=html_body)


def outreach_mail(
    *,
    session_title: str,
    preview: str,
    session_id: str,
    offer_prompt: str | None,
    unsubscribe_url: str,
) -> MailContent:
    title = (session_title or "").strip() or "Your broker has an update"
    body = preview.strip() or "There's a new message in your request."
    if offer_prompt:
        prompt = offer_prompt.strip()
        if prompt and prompt.lower() not in body.lower():
            body = f"{body}\n\n{prompt} Open the chat to answer."
    return _layout(
        title=title,
        preview=body,
        cta_url=session_url(session_id),
        cta_label="Open chat",
        footer=(
            "You received this because you have an open request. "
            f"Unsubscribe: {unsubscribe_url}"
        ),
    )


def intro_mail(
    *,
    session_title: str,
    offer_prompt: str,
    session_id: str,
    unsubscribe_url: str,
) -> MailContent:
    title = (session_title or "").strip() or "Ready to be introduced?"
    prompt = (offer_prompt or "").strip() or "Ready to be introduced?"
    return _layout(
        title=title,
        preview=f"{prompt} Open the chat to answer.",
        cta_url=session_url(session_id),
        cta_label="Open chat",
        footer=(
            "You received this because you have an open request. "
            f"Unsubscribe: {unsubscribe_url}"
        ),
    )


def contacts_mail(
    *,
    peer_name: str,
    session_id: str,
    unsubscribe_url: str,
) -> MailContent:
    name = (peer_name or "").strip() or "the other person"
    return _layout(
        title="You're introduced",
        preview=f"You're introduced. {name}'s details are in your chat.",
        cta_url=session_url(session_id),
        cta_label="Open chat",
        footer=(
            "You received this because you have an open request. "
            f"Unsubscribe: {unsubscribe_url}"
        ),
    )
