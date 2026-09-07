from __future__ import annotations

import json
import re
from typing import Any

from app.db.models import AgentRequest

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)",
)
HANDLE_RE = re.compile(r"(?<!\w)@[A-Za-z0-9._]{2,}")


def redact_identity(text: str) -> str:
    """Hide emails, phones, and handles in cross-party text before accept."""
    redacted = EMAIL_RE.sub("[hidden]", text)
    redacted = PHONE_RE.sub("[hidden]", redacted)
    return HANDLE_RE.sub("[hidden]", redacted)


def public_details(details: dict[str, Any] | None) -> dict[str, Any]:
    if not details:
        return {}
    return {key: value for key, value in details.items() if key != "semantic"}


def anonymized_request(request: AgentRequest) -> dict[str, Any]:
    from app.services.living_request import redacted_living_request

    payload = redacted_living_request(request)
    payload["status"] = request.status
    payload["title"] = request.title
    payload["summary"] = request.summary
    payload["facts"] = public_details(request.details).get("facts") or []
    return payload


def json_result(*, ok: bool, error: str | None = None, **data: Any) -> str:
    payload: dict[str, Any] = {"ok": ok, **data}
    if error:
        payload["error"] = error
    return json.dumps(payload, ensure_ascii=False, default=str)
