from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from app.db.models import BrokerMatch, BrokerRequest
from app.services.structured_llm import (
    invoke_structured_openrouter_model,
    is_llm_configured,
    llm_configuration_error,
)

logger = logging.getLogger(__name__)

MATCH_EVALUATOR_VERSION = "broker-match-evaluator.v2"
ACTIVE_MEDIATION_STATUSES = {
    "mediating",
    "waiting_source_mediation",
    "waiting_candidate_mediation",
}
ACTIVE_MATCHING_STATUSES = {
    "screening",
    "waiting_source_screening",
    "waiting_candidate_screening",
}
REEVALUATABLE_MATCH_STATUSES = {"skipped"}


class MatchEvaluation(BaseModel):
    should_mediate: bool
    compatibility_score: float = Field(ge=0.0, le=1.0)
    match_reason: str = Field(default="", max_length=1200)
    risk_flags: list[str] = Field(default_factory=list, max_length=16)
    missing_info: list[str] = Field(default_factory=list, max_length=16)
    decision_summary: str = Field(
        default="",
        max_length=500,
        description="Audit-safe summary of the match judgment.",
    )


async def evaluate_match_pair(
    source_request: BrokerRequest,
    candidate_request: BrokerRequest,
    retrieval_distance: float | None,
) -> MatchEvaluation:
    """Use the LLM broker to judge whether this retrieved pair deserves mediation."""
    _require_llm_configuration()
    return await invoke_structured_openrouter_model(
        parser_model=MatchEvaluation,
        system_prompt=_match_evaluator_prompt(),
        human_payload={
            "evaluator_version": MATCH_EVALUATOR_VERSION,
            "source_request": _request_context(source_request),
            "candidate_request": _request_context(candidate_request),
            "retrieval_distance": retrieval_distance,
            "task": "Decide only whether this retrieved pair is promising enough for mediation.",
        },
        temperature=0.1,
    )


def _should_reevaluate_match(
    broker_match: BrokerMatch,
    source_request: BrokerRequest,
    candidate_request: BrokerRequest,
) -> bool:
    if broker_match.status not in REEVALUATABLE_MATCH_STATUSES:
        return False
    if broker_match.updated_at is None:
        return True
    request_updated_at_values = [
        updated_at
        for updated_at in (source_request.updated_at, candidate_request.updated_at)
        if updated_at is not None
    ]
    return any(updated_at > broker_match.updated_at for updated_at in request_updated_at_values)


def _request_context(broker_request: BrokerRequest) -> dict[str, Any]:
    return {
        "id": broker_request.id,
        "session_id": broker_request.session_id,
        "user_id": broker_request.user_id,
        "request_type": broker_request.request_type,
        "category": broker_request.category,
        "title": broker_request.title,
        "summary": broker_request.summary,
        "structured_data": broker_request.structured_data,
    }


def _require_llm_configuration() -> None:
    if not is_llm_configured():
        raise RuntimeError(f"{llm_configuration_error()} for match evaluation.")


def _match_evaluator_prompt() -> str:
    return (
        "You are BrokerAI's match evaluator. Decide whether a retrieved pair is "
        "promising enough for a broker to mediate.\n\n"
        "BrokerAI is not a listings feed. It should protect users from weak leads, "
        "spam, and manual searching, while still noticing promising opportunities "
        "that may need broker-led qualification. Judge the substance of the fit: real "
        "complementarity, plausible mutual value, important gaps, risks, and whether "
        "a professional broker could reasonably move the pair forward.\n\n"
        "Return should_mediate=true when the pair is worth handing to the mediation "
        "agent. Return should_mediate=false when the pair is unrelated, depends on "
        "unsupported assumptions, has no credible path to value, or would mostly add "
        "noise. Do not decide whom to message or write outreach; that belongs to the "
        "mediation agent.\n\n"
        "Return JSON only and match the schema exactly. Keep decision_summary brief "
        "and audit-safe."
    )
