from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    BrokerMatch,
    BrokerMediationEvent,
    BrokerMessage,
    BrokerRequest,
)
from app.services.structured_llm import (
    invoke_structured_openrouter_model,
    is_llm_configured,
    llm_configuration_error,
)

logger = logging.getLogger(__name__)

MATCH_EVALUATOR_VERSION = "broker-match-evaluator.v1"
ACTIVE_MEDIATION_STATUSES = {
    "source_contacted",
    "candidate_contacted",
    "both_contacted",
    "waiting_source",
    "waiting_candidate",
    "negotiating",
    "accepted",
}
REEVALUATABLE_MATCH_STATUSES = {"skipped"}


class MatchEvaluation(BaseModel):
    should_mediate: bool
    compatibility_score: float = Field(ge=0.0, le=1.0)
    outreach_strategy: Literal["source_first", "candidate_first", "both", "skip"]
    match_reason: str = Field(default="", max_length=1200)
    message_to_source: str = Field(default="", max_length=1200)
    message_to_candidate: str = Field(default="", max_length=1200)
    risk_flags: list[str] = Field(default_factory=list, max_length=16)
    missing_info: list[str] = Field(default_factory=list, max_length=16)
    decision_summary: str = Field(
        default="",
        max_length=500,
        description="Audit-safe summary of the match judgment.",
    )


async def evaluate_and_start_mediations(
    db: AsyncSession,
    source_request: BrokerRequest,
    retrieved_matches: list[tuple[BrokerRequest, float | None]],
) -> list[BrokerMatch]:
    """Evaluate retrieved candidates and start at most the configured active mediations."""
    started_matches: list[BrokerMatch] = []
    active_count = await _active_mediation_count(db, source_request.id)
    if active_count >= settings.MEDIATION_MAX_ACTIVE_PER_REQUEST:
        return started_matches

    for rank, (candidate_request, distance) in enumerate(retrieved_matches, start=1):
        if active_count >= settings.MEDIATION_MAX_ACTIVE_PER_REQUEST:
            break
        if candidate_request.user_id == source_request.user_id:
            continue
        broker_match = await _get_existing_pair_match(db, source_request.id, candidate_request.id)
        if broker_match is not None and not _should_reevaluate_match(
            broker_match,
            source_request,
            candidate_request,
        ):
            continue

        try:
            evaluation = await evaluate_match_pair(
                source_request=source_request,
                candidate_request=candidate_request,
                retrieval_distance=distance,
            )
        except Exception as exc:
            logger.warning(
                "BrokerAI match evaluation failed",
                exc_info=exc,
                extra={
                    "source_request_id": source_request.id,
                    "candidate_request_id": candidate_request.id,
                },
            )
            continue

        event_type = "match_evaluated"
        if broker_match is None:
            broker_match = BrokerMatch(
                source_request_id=source_request.id,
                candidate_request_id=candidate_request.id,
            )
        else:
            event_type = "match_reevaluated"
            broker_match.source_request_id = source_request.id
            broker_match.candidate_request_id = candidate_request.id

        broker_match.status = _initial_status(evaluation)
        broker_match.score = evaluation.compatibility_score
        broker_match.rank = rank
        broker_match.match_reason = evaluation.match_reason
        broker_match.mediation_required = evaluation.should_mediate
        broker_match.outreach_strategy = evaluation.outreach_strategy
        broker_match.expires_at = _initial_expiry()
        db.add(broker_match)
        await db.flush()
        db.add(
            BrokerMediationEvent(
                match_id=broker_match.id,
                session_id=None,
                user_id=None,
                event_type=event_type,
                payload={
                    "evaluator_version": MATCH_EVALUATOR_VERSION,
                    "retrieval_distance": distance,
                    "evaluation": evaluation.model_dump(),
                },
            )
        )

        if evaluation.should_mediate and evaluation.outreach_strategy != "skip":
            await _send_initial_outreach(
                db=db,
                broker_match=broker_match,
                source_request=source_request,
                candidate_request=candidate_request,
                evaluation=evaluation,
            )
            active_count += 1
            started_matches.append(broker_match)
        else:
            broker_match.status = "skipped"

    return started_matches


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
            "task": (
                "Decide whether BrokerAI should mediate this candidate pair and the "
                "first broker move in a usually sequential mediation."
            ),
        },
        temperature=0.1,
    )


async def _send_initial_outreach(
    db: AsyncSession,
    broker_match: BrokerMatch,
    source_request: BrokerRequest,
    candidate_request: BrokerRequest,
    evaluation: MatchEvaluation,
) -> None:
    if evaluation.outreach_strategy in {"source_first", "both"} and evaluation.message_to_source:
        await _send_broker_message(
            db=db,
            broker_match=broker_match,
            target_request=source_request,
            message_text=evaluation.message_to_source,
            event_type="message_to_source",
        )
    if evaluation.outreach_strategy in {"candidate_first", "both"} and evaluation.message_to_candidate:
        await _send_broker_message(
            db=db,
            broker_match=broker_match,
            target_request=candidate_request,
            message_text=evaluation.message_to_candidate,
            event_type="message_to_candidate",
        )
    broker_match.last_activity_at = datetime.now(UTC)


async def _send_broker_message(
    db: AsyncSession,
    broker_match: BrokerMatch,
    target_request: BrokerRequest,
    message_text: str,
    event_type: str,
) -> BrokerMessage:
    message = BrokerMessage(
        session_id=target_request.session_id,
        role="assistant",
        content=message_text,
    )
    db.add(message)
    await db.flush()
    db.add(
        BrokerMediationEvent(
            match_id=broker_match.id,
            session_id=target_request.session_id,
            user_id=target_request.user_id,
            event_type=event_type,
            message_text=message_text,
            payload={"message_id": message.id},
        )
    )
    return message


async def _active_mediation_count(db: AsyncSession, source_request_id: str) -> int:
    result = await db.execute(
        select(BrokerMatch).where(
            BrokerMatch.source_request_id == source_request_id,
            BrokerMatch.status.in_(ACTIVE_MEDIATION_STATUSES),
        )
    )
    return len(result.scalars().all())


async def _get_existing_pair_match(
    db: AsyncSession,
    source_request_id: str,
    candidate_request_id: str,
) -> BrokerMatch | None:
    result = await db.execute(
        select(BrokerMatch).where(
            or_(
                (
                    (BrokerMatch.source_request_id == source_request_id)
                    & (BrokerMatch.candidate_request_id == candidate_request_id)
                ),
                (
                    (BrokerMatch.source_request_id == candidate_request_id)
                    & (BrokerMatch.candidate_request_id == source_request_id)
                ),
            )
        )
    )
    return result.scalar_one_or_none()


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


def _initial_status(evaluation: MatchEvaluation) -> str:
    if not evaluation.should_mediate or evaluation.outreach_strategy == "skip":
        return "skipped"
    if evaluation.outreach_strategy == "source_first":
        return "waiting_source"
    if evaluation.outreach_strategy == "candidate_first":
        return "waiting_candidate"
    return "both_contacted"


def _initial_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(hours=settings.MEDIATION_INITIAL_TIMEOUT_HOURS)


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
        "You are BrokerAI's match judgment agent. Your role is to decide whether a "
        "retrieved pair should enter broker-led mediation, and what the first broker "
        "move should be.\n\n"
        "BrokerAI is not a listings feed. It protects users from browsing noise and "
        "weak leads, but it should not miss a promising match just because the first "
        "view is imperfect. Evaluate the pair like a skilled intermediary: is there "
        "real complementarity, a plausible path to mutual value, and a useful next "
        "conversation that BrokerAI can handle better than the users doing manual "
        "search and negotiation themselves?\n\n"
        "Choose mediation when a focused broker message can confirm interest, test "
        "flexibility, resolve uncertainty, or move a credible match toward consent. "
        "Choose skip when the requests are not truly complementary, the fit depends "
        "on unsupported assumptions, the gap appears impractical, or contacting a "
        "party would mostly add noise.\n\n"
        "BrokerAI normally mediates sequentially. Select the first party whose reply "
        "will most improve the decision: the side with uncertain interest, flexibility, "
        "authority, consent, or the most important unresolved condition. Contact both "
        "sides only when simultaneous input is genuinely necessary and low-risk; if "
        "the pair is too uncertain for a sensible first contact, skip.\n\n"
        "For any outreach, write only the minimal in-app BrokerAI message needed for "
        "that first move. Be specific, neutral, and grounded in the supplied request "
        "data. Do not expose contact details, private facts, unsupported claims, or "
        "hidden reasoning.\n\n"
        "Return JSON only and match the schema exactly. Keep decision_summary brief "
        "and audit-safe."
    )
