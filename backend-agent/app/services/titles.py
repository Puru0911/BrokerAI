from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from app.agents.prompts import REQUEST_COPY_PROMPT
from app.core.config import settings
from app.llm.client import invoke_structured_model, is_llm_configured
from app.services.living_request import living_request_dict

logger = logging.getLogger(__name__)

TITLE_MAX_LEN = 140
SUMMARY_MAX_LEN = 1000
FALLBACK_TITLE = "New broker request"


class RequestCopy(BaseModel):
    model_config = {"extra": "ignore"}
    title: str = Field(min_length=1, max_length=TITLE_MAX_LEN)
    summary: str = Field(min_length=1, max_length=SUMMARY_MAX_LEN)


def welcome_message(agent_name: str | None = None) -> str:
    name = (agent_name if agent_name is not None else settings.agent_name).strip() or "BrokerAI"
    return (
        f"Hi! I'm {name}. Tell me what you're looking for and I'll find you the right Person."
    )


def create_title(message: str | None) -> str:
    if not message:
        return FALLBACK_TITLE
    normalized = " ".join(message.strip().split())
    if not normalized:
        return FALLBACK_TITLE
    title = normalized[:72].rstrip(" .,")
    return title if len(normalized) <= 72 else f"{title}..."


def create_summary(text: str | None) -> str:
    compact = re.sub(r"\s+", " ", (text or "").strip())
    return compact[:SUMMARY_MAX_LEN]


def _clip_title(title: str, fallback: str) -> str:
    compact = " ".join(title.split()).rstrip(" .,")
    if not compact:
        return fallback
    if len(compact) <= TITLE_MAX_LEN:
        return compact
    return compact[: TITLE_MAX_LEN - 3].rstrip(" .,") + "..."


def fallback_request_copy(details: dict[str, Any] | None) -> tuple[str, str]:
    living = living_request_dict(details)
    objective = living.get("objective") or ""
    return create_title(objective), create_summary(objective)


async def generate_request_copy(details: dict[str, Any] | None) -> tuple[str, str]:
    """LLM title and summary for a living brief, with a heuristic fallback."""
    fallback_title, fallback_summary = fallback_request_copy(details)
    living = living_request_dict(details)
    if not living.get("objective"):
        return fallback_title, fallback_summary
    if not is_llm_configured():
        logger.info("request copy using fallback reason=llm_not_configured")
        return fallback_title, fallback_summary
    try:
        copy = await invoke_structured_model(
            parser_model=RequestCopy,
            system_prompt=REQUEST_COPY_PROMPT,
            human_payload=living,
            temperature=0.1,
            max_tokens=400,
            use_reasoning=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("request copy llm failed error=%s", exc)
        return fallback_title, fallback_summary
    title = _clip_title(copy.title, fallback_title)
    summary = create_summary(copy.summary) or fallback_summary
    logger.info("request copy generated title=%s", title)
    return title, summary
