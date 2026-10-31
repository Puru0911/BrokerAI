from __future__ import annotations

import re
from typing import Any

from app.agents.tool_call_repair import coerce_str_list
from app.db.models import AgentRequest
from app.services.privacy import public_details, redact_identity


_VIEW_FILTER_CAP = 12
_VIEW_FILTER_ITEM_MAX = 160

SEARCH_CORE_KEYS = (
    "domain",
    "objective",
    "hard_constraints",
    "soft_preferences",
    "freeform_notes",
)
SEARCH_LIST_KEYS = {"hard_constraints", "soft_preferences"}
SEARCH_STR_KEYS = {"domain", "objective", "freeform_notes"}
RESERVED_DETAIL_KEYS = {"semantic", "possible_pair", "request_id", "indexed"}
_CORE_ALIASES = {
    "constraints": "hard_constraints",
    "preferences": "soft_preferences",
    "notes": "freeform_notes",
    "kind": "domain",
}

_EXTRA_KEY_CAP = 20
_EXTRA_KEY_MAX = 40
_EXTRA_VALUE_MAX = 500
_EXTRA_LIST_CAP = 12
_EXTRA_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


def normalize_view_filters(values: Any) -> list[str]:
    """Deduped overlay terms. Not part of the living brief."""
    items: list[str] = []
    for raw in values or []:
        text = str(raw or "").strip()[:_VIEW_FILTER_ITEM_MAX].strip()
        if text and text not in items:
            items.append(text)
        if len(items) >= _VIEW_FILTER_CAP:
            break
    return items


def view_filters_of(request: AgentRequest | None) -> list[str]:
    if request is None:
        return []
    return normalize_view_filters(getattr(request, "view_filters", None))


def normalize_extra_key(raw: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(raw or "").strip().lower()).strip("_")
    return text[:_EXTRA_KEY_MAX]


def normalize_extra_value(value: Any) -> str | list[str] | None:
    if isinstance(value, list):
        items: list[str] = []
        for raw in value:
            text = str(raw or "").strip()[:_EXTRA_VALUE_MAX].strip()
            if text and text not in items:
                items.append(text)
            if len(items) >= _EXTRA_LIST_CAP:
                break
        return items or None
    text = str(value or "").strip()[:_EXTRA_VALUE_MAX].strip()
    return text or None


def extra_fields_of(details: dict[str, Any] | None) -> dict[str, str | list[str]]:
    """Agent-added context keys. Budget, location, and timeline live here when set."""
    extras: dict[str, str | list[str]] = {}
    for raw_key, raw_value in public_details(details).items():
        if raw_key in SEARCH_CORE_KEYS or raw_key in _CORE_ALIASES or raw_key in RESERVED_DETAIL_KEYS:
            continue
        key = normalize_extra_key(raw_key)
        if not key or not _EXTRA_KEY_RE.match(key):
            continue
        if key in SEARCH_CORE_KEYS or key in RESERVED_DETAIL_KEYS:
            continue
        parsed = normalize_extra_value(raw_value)
        if parsed is None:
            continue
        extras[key] = parsed
        if len(extras) >= _EXTRA_KEY_CAP:
            break
    return extras


def search_brief_dict(details: dict[str, Any] | None) -> dict[str, Any]:
    """Fixed keys that the vector index is built from."""
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
        "domain": (data.get("domain") or data.get("kind") or "").strip(),
        "freeform_notes": str(notes).strip(),
    }


def living_request_dict(details: dict[str, Any] | None) -> dict[str, Any]:
    """Search core plus extra context keys. Empty extras are omitted."""
    payload = search_brief_dict(details)
    payload.update(extra_fields_of(details))
    return payload


def _with_preserved_blob(
    details: dict[str, Any] | None,
    core: dict[str, Any],
    extras: dict[str, str | list[str]],
) -> dict[str, Any]:
    merged = {**core, **extras}
    semantic = (details or {}).get("semantic") if isinstance(details, dict) else None
    if semantic is not None:
        merged["semantic"] = semantic
    return merged


def apply_search_brief_patch(
    details: dict[str, Any] | None, patch: dict[str, Any]
) -> dict[str, Any]:
    """Merge a partial search-brief update. Extra context keys stay."""
    current = search_brief_dict(details)
    extras = extra_fields_of(details)
    for key, value in patch.items():
        if value is None or key not in {*SEARCH_STR_KEYS, *SEARCH_LIST_KEYS}:
            continue
        if key in SEARCH_LIST_KEYS:
            current[key] = coerce_str_list(value)
        else:
            current[key] = str(value).strip()
    return _with_preserved_blob(details, current, extras)


def apply_request_patch(details: dict[str, Any] | None, patch: dict[str, Any]) -> dict[str, Any]:
    """Alias for search-brief patches. Extra keys are preserved."""
    return apply_search_brief_patch(details, patch)


def apply_details_extra_patch(
    details: dict[str, Any] | None, fields: dict[str, Any] | None
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Add or replace extra context keys. Search-core keys are refused."""
    applied: list[str] = []
    refused: list[str] = []
    extras = extra_fields_of(details)
    for raw_key, raw_value in (fields or {}).items():
        key = normalize_extra_key(raw_key)
        if (
            not key
            or not _EXTRA_KEY_RE.match(key)
            or key in SEARCH_CORE_KEYS
            or key in _CORE_ALIASES
            or key in RESERVED_DETAIL_KEYS
        ):
            refused.append(str(raw_key or "").strip() or key)
            continue
        parsed = normalize_extra_value(raw_value)
        if parsed is None:
            extras.pop(key, None)
            applied.append(key)
            continue
        if key not in extras and len(extras) >= _EXTRA_KEY_CAP:
            refused.append(key)
            continue
        extras[key] = parsed
        applied.append(key)
    merged = _with_preserved_blob(details, search_brief_dict(details), extras)
    return merged, applied, refused


def living_request_from_model(request: AgentRequest | None) -> dict[str, Any] | None:
    if request is None:
        return None
    payload = living_request_dict(request.details)
    payload["request_id"] = request.id
    payload["indexed"] = request.indexed_at is not None
    return payload


def redacted_living_request(request: AgentRequest) -> dict[str, Any]:
    payload = living_request_dict(request.details)
    for key, value in list(payload.items()):
        if isinstance(value, list):
            payload[key] = [redact_identity(str(item)) for item in value]
        elif isinstance(value, str):
            payload[key] = redact_identity(value)
    payload["request_id"] = request.id
    return payload


def counterpart_brief_stub(request_id: str | None) -> dict[str, Any]:
    """Pre-accept other_brief for the chat packet. Scoped facts come from get_match_brief."""
    return {
        "request_id": request_id,
        "possible_counterpart": True,
        "objective": "A possible counterpart for this request.",
    }
