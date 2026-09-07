"""Recover tool calls when Groq/Qwen emit XML instead of OpenAI JSON."""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage

logger = logging.getLogger(__name__)

_FUNCTION_RE = re.compile(
    r"<function=(?P<name>[A-Za-z0-9_]+)>(?P<body>.*?)(?:</function>|(?=<function=)|\Z)",
    re.DOTALL,
)
_PARAM_RE = re.compile(
    r"<parameter=(?P<key>[A-Za-z0-9_]+)>\s*(?P<value>.*?)\s*</parameter>",
    re.DOTALL,
)
_OPEN_PARAM_RE = re.compile(
    r"<parameter=(?P<key>[A-Za-z0-9_]+)>\s*(?P<value>.*?)\s*\Z",
    re.DOTALL,
)


def coerce_optional_str_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    return coerce_str_list(value)


def coerce_str_list(value: Any) -> list[str]:
    """Accept JSON arrays, Python lists, or comma/newline-separated strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text[:1] in "[{":
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        return [part.strip(" -•") for part in re.split(r"[\n,;]+", text) if part.strip(" -•")]
    return [str(value).strip()] if str(value).strip() else []


def failed_generation_from_error(exc: BaseException) -> str | None:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            generation = error.get("failed_generation")
            if isinstance(generation, str) and generation.strip():
                return generation
        generation = body.get("failed_generation")
        if isinstance(generation, str) and generation.strip():
            return generation
    text = str(exc)
    marker = "failed_generation"
    if marker not in text:
        return None
    try:
        start = text.index("{")
        payload = json.loads(text[start:].replace("'", '"'))
    except (ValueError, json.JSONDecodeError):
        match = re.search(r"'failed_generation':\s*'(.*)'\}", text, re.DOTALL)
        return match.group(1).encode("utf-8").decode("unicode_escape") if match else None
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict) and isinstance(error.get("failed_generation"), str):
        return error["failed_generation"]
    return None


def parse_xml_tool_calls(text: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for match in _FUNCTION_RE.finditer(text):
        args: dict[str, Any] = {}
        body = match.group("body")
        for param in _PARAM_RE.finditer(body):
            args[param.group("key")] = _coerce_value(param.group("value"))
        leftover = _PARAM_RE.sub("", body).strip()
        open_param = _OPEN_PARAM_RE.search(leftover)
        if open_param and open_param.group("key") not in args:
            args[open_param.group("key")] = _coerce_value(open_param.group("value"))
        if not args and not match.group("name"):
            continue
        calls.append(
            {
                "name": match.group("name"),
                "args": args,
                "id": f"repair_{uuid4().hex[:12]}",
                "type": "tool_call",
            }
        )
    return calls


def repair_tool_message(exc: BaseException) -> AIMessage | None:
    generation = failed_generation_from_error(exc)
    if not generation:
        return None
    calls = parse_xml_tool_calls(generation)
    if not calls:
        logger.info("could not repair tool generation")
        return None
    logger.info("repaired XML tool calls tools=%s", [call["name"] for call in calls])
    return AIMessage(content="", tool_calls=calls)


def _coerce_value(raw: str) -> Any:
    text = raw.strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if text[:1] in "[{":
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text
