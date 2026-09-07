from __future__ import annotations

from typing import Any

from app.agents.tool_call_repair import coerce_str_list
from app.db.models import AgentRequest
from app.services.privacy import public_details, redact_identity


def living_request_dict(details: dict[str, Any] | None) -> dict[str, Any]:
    """Canonical living_request fields, including aliases from earlier briefs."""
    data = public_details(details)
    notes = data.get("freeform_notes") or data.get("notes") or ""
    return {
        "objective": (data.get("objective") or "").strip(),
        "hard_constraints": coerce_str_list(
            data.get("hard_constraints") or data.get("constraints")
        ),
        "soft_preferences": coerce_str_list(
            data.get("soft_preferences") or data.get("preferences")
        ),
        "budget": (data.get("budget") or "").strip(),
        "domain": (data.get("domain") or data.get("kind") or "").strip(),
        "location": (data.get("location") or "").strip(),
        "timeline": (data.get("timeline") or "").strip(),
        "freeform_notes": str(notes).strip(),
    }


def apply_request_patch(details: dict[str, Any] | None, patch: dict[str, Any]) -> dict[str, Any]:
    """Merge a partial brief update into the canonical living request."""
    current = living_request_dict(details)
    list_fields = {"hard_constraints", "soft_preferences"}
    str_fields = {
        "objective",
        "budget",
        "domain",
        "location",
        "timeline",
        "freeform_notes",
    }
    for key, value in patch.items():
        if value is None:
            continue
        if key in list_fields:
            current[key] = coerce_str_list(value)
        elif key in str_fields:
            current[key] = str(value).strip()
    return current


def living_request_from_model(request: AgentRequest | None) -> dict[str, Any] | None:
    if request is None:
        return None
    payload = living_request_dict(request.details)
    payload["request_id"] = request.id
    payload["indexed"] = request.indexed_at is not None
    return payload


def redacted_living_request(request: AgentRequest) -> dict[str, Any]:
    payload = living_request_dict(request.details)
    for key in ("objective", "budget", "domain", "location", "timeline", "freeform_notes"):
        payload[key] = redact_identity(str(payload.get(key) or ""))
    payload["hard_constraints"] = [
        redact_identity(item) for item in payload["hard_constraints"]
    ]
    payload["soft_preferences"] = [
        redact_identity(item) for item in payload["soft_preferences"]
    ]
    payload["request_id"] = request.id
    return payload
