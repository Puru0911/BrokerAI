from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agents.prompts import PAIR_EVALUATOR_PROMPT
from app.db.models import AgentRequest
from app.llm.client import invoke_structured_model, is_llm_configured, llm_configuration_error
from app.services.living_request import living_request_dict


class PairEvaluation(BaseModel):
    model_config = {"extra": "ignore"}
    verdict: Literal["strong_match", "possible_match", "weak_match", "no_match"]
    score: int = Field(ge=0, le=100)
    matched: list[str] = Field(default_factory=list)
    mismatched: list[str] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    negotiation_room: bool = False
    recommended_action: Literal["open_match", "ask_clarifying_question", "skip"]
    clarifying_question: str = ""
    next_questions: list[str] = Field(default_factory=list)
    rationale: str = ""


async def evaluate_pair(
    source_request: AgentRequest,
    candidate_request: AgentRequest,
    retrieval_distance: float | None = None,
    prior_events: list[dict[str, Any]] | None = None,
) -> PairEvaluation:
    if not is_llm_configured():
        raise RuntimeError(llm_configuration_error())
    similarity = None
    if retrieval_distance is not None:
        similarity = max(0.0, min(1.0, 1.0 - float(retrieval_distance)))
    return await invoke_structured_model(
        parser_model=PairEvaluation,
        system_prompt=PAIR_EVALUATOR_PROMPT,
        human_payload={
            "source_request": living_request_dict(source_request.details),
            "candidate_profile": living_request_dict(candidate_request.details),
            "similarity_score": similarity,
            "prior_events": prior_events or [],
        },
        temperature=0.1,
    )
