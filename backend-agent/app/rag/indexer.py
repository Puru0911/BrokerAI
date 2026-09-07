from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.agents.prompts import SEMANTIC_INDEX_PROMPT, SEMANTIC_SEARCH_PROMPT
from app.db.models import AgentRequest
from app.llm.client import (
    invoke_structured_model,
    invoke_text_model,
    is_llm_configured,
    llm_configuration_error,
)
from app.rag.store import get_vector_store
from app.services.living_request import living_request_dict

logger = logging.getLogger(__name__)

PROFILE_VERSION = "agent-semantic-profile.v2"
PLAN_VERSION = "agent-retrieval-plan.v3"


class SemanticRetrievalPlan(BaseModel):
    model_config = {"extra": "ignore"}
    query_text: str = Field(min_length=20, max_length=4000)


def living_input(request: AgentRequest) -> dict[str, Any]:
    return living_request_dict(request.details)


def _fallback_profile(request: AgentRequest) -> str:
    living = living_input(request)
    constraints = living["hard_constraints"] or ["Not specified."]
    preferences = living["soft_preferences"] or ["Not specified."]
    return (
        f"DOMAIN: {living['domain'] or 'general'}\n"
        f"LOOKING FOR: {living['objective'] or request.summary}\n"
        f"CAN OFFER: {living['freeform_notes'] or 'Not specified.'}\n"
        f"IDEAL COUNTERPART: Someone whose need or offer complements: {living['objective']}\n"
        f"HARD CONSTRAINTS:\n"
        + "\n".join(f"- {item}" for item in constraints)
        + "\nSOFT PREFERENCES:\n"
        + "\n".join(f"- {item}" for item in preferences)
        + f"\nKEYWORDS: {living['domain']}, {living['location']}, {living['objective']}"
    )


async def build_semantic_document(request: AgentRequest) -> str:
    if not is_llm_configured():
        raise RuntimeError(llm_configuration_error())
    text = await invoke_text_model(
        system_prompt=SEMANTIC_INDEX_PROMPT,
        human_payload=living_input(request),
        temperature=0.1,
        max_tokens=800,
    )
    if "LOOKING FOR:" not in text.upper() and len(text) < 80:
        return _fallback_profile(request)
    return text


async def build_retrieval_plan(request: AgentRequest) -> SemanticRetrievalPlan:
    if not is_llm_configured():
        raise RuntimeError(llm_configuration_error())
    return await invoke_structured_model(
        parser_model=SemanticRetrievalPlan,
        system_prompt=SEMANTIC_SEARCH_PROMPT,
        human_payload=living_input(request),
        temperature=0.1,
    )


async def index_request(request: AgentRequest) -> str:
    document = await build_semantic_document(request)
    details = dict(request.details or {})
    details["semantic"] = {
        "profile_version": PROFILE_VERSION,
        "embedding_model": "chroma-default/all-MiniLM-L6-v2",
        "document": document,
    }
    request.details = details
    living = living_input(request)
    await asyncio.to_thread(
        get_vector_store().upsert_request,
        request,
        document,
        living.get("domain") or None,
        living.get("location") or None,
    )
    request.indexed_at = datetime.now(UTC)
    logger.info("request indexed request_id=%s session_id=%s", request.id, request.session_id)
    return document
