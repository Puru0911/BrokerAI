from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import UserProfile
from app.db.session import get_db
from app.services.notify import parse_unsubscribe_token

router = APIRouter()


def _page(*, title: str, body: str) -> HTMLResponse:
    cream = "#F4F1EC"
    teal = "#0F5C56"
    ink = "#1C1917"
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
</head>
<body style="margin:0;background:{cream};color:{ink};font-family:Georgia,serif;">
  <main style="max-width:32rem;margin:12vh auto;padding:0 1.5rem;">
    <p style="font-family:system-ui,sans-serif;font-size:12px;letter-spacing:0.14em;text-transform:uppercase;color:{teal};font-weight:600;">{settings.mail_from_name}</p>
    <h1 style="font-size:1.75rem;font-weight:500;">{title}</h1>
    <p style="font-size:1.05rem;line-height:1.55;">{body}</p>
  </main>
</body>
</html>"""
    return HTMLResponse(html)


def _wants_json(request: Request) -> bool:
    accept = (request.headers.get("accept") or "").lower()
    return "application/json" in accept and "text/html" not in accept


@router.api_route("/unsubscribe", methods=["GET", "POST"])
async def unsubscribe(
    request: Request,
    token: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
):
    user_id = parse_unsubscribe_token(token)
    if user_id is None:
        title = "Link expired"
        body = (
            "This unsubscribe link is invalid or has expired. "
            "Open the app to change email settings."
        )
        if _wants_json(request):
            return {"ok": False, "title": title, "message": body}
        return _page(title=title, body=body)
    profile = await db.get(UserProfile, user_id)
    if profile is None:
        title = "Already done"
        body = (
            "We could not find an account for this link. "
            "You will not receive further activity email."
        )
        if _wants_json(request):
            return {"ok": True, "title": title, "message": body}
        return _page(title=title, body=body)
    profile.notify_email = False
    await db.commit()
    title = "Email updates are off"
    body = (
        "You will no longer get activity email when you are away. "
        "You can turn this back on from the app."
    )
    if _wants_json(request):
        return {"ok": True, "title": title, "message": body}
    return _page(title=title, body=body)
