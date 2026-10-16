from __future__ import annotations

from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from app.db.models import AgentRequest

POSSIBLE_PAIR_KEY = "possible_pair"


def possible_pair(details: dict[str, Any] | None) -> dict[str, Any] | None:
    raw = (details or {}).get(POSSIBLE_PAIR_KEY)
    if not isinstance(raw, dict):
        return None
    other_id = str(raw.get("other_request_id") or "").strip()
    if not other_id:
        return None
    return {
        "other_request_id": other_id,
        "question": str(raw.get("question") or "").strip(),
        "waiting_on_request_id": str(raw.get("waiting_on_request_id") or "").strip(),
        "asked_by_request_id": str(raw.get("asked_by_request_id") or "").strip(),
        "verdict": str(raw.get("verdict") or "").strip(),
    }


def set_possible_pair(
    details: dict[str, Any] | None, entry: dict[str, Any]
) -> dict[str, Any]:
    data = dict(details or {})
    data[POSSIBLE_PAIR_KEY] = entry
    return data


def clear_possible_pair(details: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(details or {})
    data.pop(POSSIBLE_PAIR_KEY, None)
    return data


def possible_pair_entry(
    *,
    other_request_id: str,
    question: str,
    waiting_on_request_id: str,
    asked_by_request_id: str,
    verdict: str = "",
) -> dict[str, Any]:
    return {
        "other_request_id": other_request_id,
        "question": question,
        "waiting_on_request_id": waiting_on_request_id,
        "asked_by_request_id": asked_by_request_id,
        "verdict": verdict,
    }


def persist_possible_pair(request: AgentRequest, entry: dict[str, Any] | None) -> None:
    if entry is None:
        request.details = clear_possible_pair(request.details)
    else:
        request.details = set_possible_pair(request.details, entry)
    flag_modified(request, "details")
