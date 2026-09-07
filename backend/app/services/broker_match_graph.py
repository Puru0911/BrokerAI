from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    BrokerMatch,
    BrokerMediationEvent,
    BrokerMessage,
    BrokerRequest,
    BrokerSession,
)
from app.services.broker_matching import (
    ACTIVE_MATCHING_STATUSES,
    MATCH_EVALUATOR_VERSION,
    evaluate_match_pair,
    _should_reevaluate_match,
)
from app.services.broker_rag import retrieve_similar_requests
from app.services.structured_llm import (
    invoke_structured_openrouter_model,
)
from app.services.broker_workflow import (
    clear_active_workflow,
    clear_match_workflows,
    graph_status_for,
    party_role_for_request,
    set_active_workflow,
    waiting_status_for,
)

logger = logging.getLogger(__name__)

MATCH_GRAPH_VERSION = "broker-matching-graph.v2"
MATCHING_AGENT_VERSION = "broker-matching-agent.v1"


class MatchGraphRoute(BaseModel):
    operation: Literal[
        "retrieve_matches",
        "handle_screening",
        "close_request",
        "no_op",
    ]
    decision_summary: str = Field(default="", max_length=500)


class MatchingAgentDecision(BaseModel):
    plan: str = Field(
        default="",
        max_length=1600,
        description="Natural-language broker plan for audit and downstream context.",
    )
    action: Literal[
        "send_message",
        "wait",
        "update_match",
        "reject_match",
        "qualify_for_mediation",
        "retrieve_more",
        "skip_match",
        "move_to_next_match",
    ]
    target: Literal["source", "candidate", "both", "system"] = "system"
    agreement_reached: bool = False
    message_to_source: str = Field(default="", max_length=1200)
    message_to_candidate: str = Field(default="", max_length=1200)
    source_request_updates: dict[str, Any] = Field(default_factory=dict)
    candidate_request_updates: dict[str, Any] = Field(default_factory=dict)
    decision_summary: str = Field(default="", max_length=500)


class MatchGraphState(TypedDict, total=False):
    db: AsyncSession
    broker_session: BrokerSession
    source_request: BrokerRequest
    user_message: BrokerMessage
    active_matching: tuple[BrokerMatch, BrokerRequest] | None
    route: MatchGraphRoute
    retrieved_matches: list[tuple[BrokerRequest, float | None]]
    evaluated_matches: list[BrokerMatch]
    assistant_messages: list[BrokerMessage]
    closed_request: BrokerRequest | None


async def run_match_graph_for_request(
    db: AsyncSession,
    source_request: BrokerRequest,
) -> list[BrokerMatch]:
    """Run retrieval, evaluation, screening, and mediation handoff for an embedded request."""
    graph = _build_match_graph()
    final_state = await graph.ainvoke(
        {
            "db": db,
            "source_request": source_request,
        }
    )
    return final_state.get("evaluated_matches", [])


async def run_match_graph_for_message(
    db: AsyncSession,
    broker_session: BrokerSession,
    user_message: BrokerMessage,
    active_matching: tuple[BrokerMatch, BrokerRequest] | None,
) -> list[BrokerMessage]:
    """Route a user message through the matching/screening graph."""
    graph = _build_match_graph()
    final_state = await graph.ainvoke(
        {
            "db": db,
            "broker_session": broker_session,
            "user_message": user_message,
            "active_matching": active_matching,
        }
    )
    return final_state.get("assistant_messages", [])


async def process_next_matches_for_request(
    db: AsyncSession,
    source_request: BrokerRequest,
) -> list[BrokerMatch]:
    """Compatibility wrapper for stale-mediation recovery and manual triggers."""
    return await run_match_graph_for_request(db, source_request)


def _build_match_graph():
    graph = StateGraph(MatchGraphState)
    graph.add_node("route", _route_node)
    graph.add_node("retrieve_matches", _retrieve_matches_node)
    graph.add_node("evaluate_matches", _evaluate_matches_node)
    graph.add_node("screen_plan", _screen_plan_node)
    graph.add_node("handle_screening", _handle_screening_node)
    graph.add_node("close_request", _close_request_node)
    graph.add_node("no_op", _no_op_node)
    graph.set_entry_point("route")
    graph.add_conditional_edges(
        "route",
        _route_after_route_node,
        {
            "retrieve_matches": "retrieve_matches",
            "handle_screening": "handle_screening",
            "close_request": "close_request",
            "no_op": "no_op",
        },
    )
    graph.add_edge("retrieve_matches", "evaluate_matches")
    graph.add_edge("evaluate_matches", "screen_plan")
    graph.add_edge("screen_plan", END)
    graph.add_edge("handle_screening", END)
    graph.add_edge("close_request", END)
    graph.add_edge("no_op", END)
    return graph.compile()


async def _route_node(state: MatchGraphState) -> MatchGraphState:
    if state.get("source_request") is not None and state.get("user_message") is None:
        route = MatchGraphRoute(
            operation="retrieve_matches",
            decision_summary="An embedded request triggered match retrieval.",
        )
        return {**state, "route": route}

    active_matching = state.get("active_matching")
    user_message = state.get("user_message")
    if user_message is None:
        return {
            **state,
            "route": MatchGraphRoute(operation="no_op", decision_summary="No user message."),
        }

    session_request = await _get_session_request(state["db"], user_message.session_id)
    route = MatchGraphRoute(
        operation="handle_screening" if active_matching else "no_op",
        decision_summary=(
            "Deterministic route from the request active matching pointer."
            if active_matching
            else "No active matching pointer was found."
        ),
    )
    return {**state, "source_request": session_request, "route": route}


def _route_after_route_node(state: MatchGraphState) -> str:
    return state["route"].operation


async def _retrieve_matches_node(state: MatchGraphState) -> MatchGraphState:
    source_request = state.get("source_request")
    if source_request is None or source_request.embedding_status != "embedded":
        return {**state, "retrieved_matches": []}
    matches = await retrieve_similar_requests(
        state["db"],
        source_request,
        settings.MATCH_EXPORT_AUTO_LIMIT,
    )
    return {**state, "retrieved_matches": matches}


async def _evaluate_matches_node(state: MatchGraphState) -> MatchGraphState:
    source_request = state.get("source_request")
    if source_request is None:
        return {**state, "evaluated_matches": []}

    db = state["db"]
    source_request.status = "matching"
    active_count = await _active_matching_count(db, source_request.id)
    evaluated_matches: list[BrokerMatch] = []

    for rank, (candidate_request, distance) in enumerate(
        state.get("retrieved_matches", []),
        start=1,
    ):
        if active_count >= settings.MEDIATION_MAX_ACTIVE_PER_REQUEST:
            break
        if candidate_request.user_id == source_request.user_id:
            continue

        broker_match = await _get_existing_pair_match(
            db,
            source_request.id,
            candidate_request.id,
        )
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

        broker_match.score = evaluation.compatibility_score
        broker_match.rank = rank
        broker_match.match_reason = evaluation.match_reason
        broker_match.mediation_required = evaluation.should_mediate
        broker_match.expires_at = _initial_expiry()
        broker_match.outreach_strategy = "pending_screening" if evaluation.should_mediate else "skip"
        broker_match.status = "discovered" if evaluation.should_mediate else "skipped"
        db.add(broker_match)
        await db.flush()
        db.add(
            BrokerMediationEvent(
                match_id=broker_match.id,
                session_id=None,
                user_id=None,
                event_type=event_type,
                payload={
                    "match_graph_version": MATCH_GRAPH_VERSION,
                    "evaluator_version": MATCH_EVALUATOR_VERSION,
                    "retrieval_distance": distance,
                    "evaluation": evaluation.model_dump(),
                },
            )
        )

        if evaluation.should_mediate:
            evaluated_matches.append(broker_match)
        else:
            broker_match.status = "skipped"

    return {**state, "evaluated_matches": evaluated_matches}


async def _screen_plan_node(state: MatchGraphState) -> MatchGraphState:
    db = state["db"]
    assistant_messages: list[BrokerMessage] = []
    source_request = state.get("source_request")
    if source_request is None:
        return {**state, "assistant_messages": assistant_messages}

    active_count = await _active_matching_count(db, source_request.id)
    for broker_match in state.get("evaluated_matches", []):
        if active_count >= settings.MEDIATION_MAX_ACTIVE_PER_REQUEST:
            break
        source_request = await db.get(BrokerRequest, broker_match.source_request_id)
        candidate_request = await db.get(BrokerRequest, broker_match.candidate_request_id)
        if source_request is None or candidate_request is None:
            broker_match.status = "closed"
            continue

        history = await _load_mediation_history(db, broker_match.id)
        decision = await _decide_matching_action(
            broker_match=broker_match,
            source_request=source_request,
            candidate_request=candidate_request,
            matching_history=history,
            phase="initial",
        )
        messages = await _apply_matching_action(
            db=db,
            broker_match=broker_match,
            source_request=source_request,
            candidate_request=candidate_request,
            decision=decision,
            party_role=None,
            party_request=None,
        )
        db.add(
            BrokerMediationEvent(
                match_id=broker_match.id,
                session_id=None,
                user_id=None,
                event_type="screening_action_planned",
                payload={
                    "matching_agent_version": MATCHING_AGENT_VERSION,
                    "phase": "initial",
                    "decision": decision.model_dump(),
                },
            )
        )
        if broker_match.status in ACTIVE_MATCHING_STATUSES:
            active_count += 1
        assistant_messages.extend(messages)

    return {**state, "assistant_messages": assistant_messages}


async def _handle_screening_node(state: MatchGraphState) -> MatchGraphState:
    active_matching = state.get("active_matching")
    user_message = state.get("user_message")
    if active_matching is None or user_message is None:
        return {**state, "assistant_messages": []}

    broker_match, party_request = active_matching
    db = state["db"]
    source_request = await db.get(BrokerRequest, broker_match.source_request_id)
    candidate_request = await db.get(BrokerRequest, broker_match.candidate_request_id)
    if source_request is None or candidate_request is None:
        broker_match.status = "closed"
        message = BrokerMessage(
            session_id=user_message.session_id,
            role="assistant",
            content="I could not continue screening this match because one side is no longer available.",
        )
        db.add(message)
        await db.flush()
        return {**state, "assistant_messages": [message]}

    party_role = party_role_for_request(broker_match, party_request)
    db.add(
        BrokerMediationEvent(
            match_id=broker_match.id,
            session_id=user_message.session_id,
            user_id=party_request.user_id,
            event_type=f"{party_role}_screening_reply_received",
            message_text=user_message.content,
            payload={"message_id": user_message.id},
        )
    )
    await db.flush()

    history = await _load_mediation_history(db, broker_match.id)
    decision = await _decide_matching_action(
        broker_match=broker_match,
        source_request=source_request,
        candidate_request=candidate_request,
        matching_history=history,
        phase="reply",
        replying_party=party_role,
        user_message=user_message.content,
    )
    messages = await _apply_matching_action(
        db=db,
        broker_match=broker_match,
        source_request=source_request,
        candidate_request=candidate_request,
        decision=decision,
        party_role=party_role,
        party_request=party_request,
    )
    broker_match.last_activity_at = datetime.now(UTC)
    db.add(
        BrokerMediationEvent(
            match_id=broker_match.id,
            session_id=user_message.session_id,
            user_id=party_request.user_id,
            event_type="screening_action_decided",
            payload={
                "matching_agent_version": MATCHING_AGENT_VERSION,
                "phase": "reply",
                "party_role": party_role,
                "decision": decision.model_dump(),
            },
        )
    )
    return {
        **state,
        "assistant_messages": [
            message for message in messages if message.session_id == user_message.session_id
        ],
    }


async def _close_request_node(state: MatchGraphState) -> MatchGraphState:
    db = state["db"]
    broker_request = state.get("source_request")
    user_message = state.get("user_message")
    broker_session = state.get("broker_session")
    if broker_request is None and user_message is not None:
        broker_request = await _get_session_request(db, user_message.session_id)
    if broker_request is None:
        return {**state, "assistant_messages": []}

    await _close_request_records(
        db=db,
        broker_request=broker_request,
        reason="user_requested_closure",
    )
    if broker_session is not None:
        broker_session.status = "closed"

    target_session_id = broker_session.id if broker_session is not None else broker_request.session_id
    message = BrokerMessage(
        session_id=target_session_id,
        role="assistant",
        content="Done. I have closed this broker request and stopped active mediation for it.",
    )
    db.add(message)
    await db.flush()
    return {**state, "closed_request": broker_request, "assistant_messages": [message]}


async def _no_op_node(state: MatchGraphState) -> MatchGraphState:
    return {**state, "assistant_messages": []}


async def _decide_matching_action(
    broker_match: BrokerMatch,
    source_request: BrokerRequest,
    candidate_request: BrokerRequest,
    matching_history: list[dict[str, Any]],
    phase: Literal["initial", "reply"],
    replying_party: str | None = None,
    user_message: str | None = None,
) -> MatchingAgentDecision:
    return await invoke_structured_openrouter_model(
        parser_model=MatchingAgentDecision,
        system_prompt=_matching_agent_prompt(),
        human_payload={
            "matching_agent_version": MATCHING_AGENT_VERSION,
            "phase": phase,
            "match": _match_context(broker_match),
            "source_request": _request_context(source_request),
            "candidate_request": _request_context(candidate_request),
            "matching_history": matching_history,
            "replying_party": replying_party,
            "user_message": user_message,
            "available_actions": [
                "send_message",
                "wait",
                "update_match",
                "reject_match",
                "qualify_for_mediation",
                "retrieve_more",
                "skip_match",
                "move_to_next_match",
            ],
            "task": "Plan and choose the next broker matching/screening action.",
        },
        temperature=0.1,
    )


async def _apply_matching_action(
    db: AsyncSession,
    broker_match: BrokerMatch,
    source_request: BrokerRequest,
    candidate_request: BrokerRequest,
    decision: MatchingAgentDecision,
    party_role: str | None,
    party_request: BrokerRequest | None,
) -> list[BrokerMessage]:
    _merge_request_updates(source_request, decision.source_request_updates)
    _merge_request_updates(candidate_request, decision.candidate_request_updates)

    if decision.action in {"reject_match", "skip_match", "move_to_next_match"}:
        broker_match.status = "rejected" if decision.action == "reject_match" else "skipped"
        await clear_match_workflows(db, broker_match)
        return await _send_action_messages(db, broker_match, source_request, candidate_request, decision)

    if decision.action == "qualify_for_mediation" or decision.agreement_reached:
        broker_match.status = "qualified"
        await clear_match_workflows(db, broker_match)
        messages = await _send_action_messages(
            db,
            broker_match,
            source_request,
            candidate_request,
            decision,
        )
        db.add(
            BrokerMediationEvent(
                match_id=broker_match.id,
                session_id=None,
                user_id=None,
                event_type="match_qualified_for_mediation",
                payload={"matching_agent_version": MATCHING_AGENT_VERSION},
            )
        )
        from app.services.broker_mediation_graph import start_mediation_for_match

        messages.extend(await start_mediation_for_match(db, broker_match))
        return messages

    messages = await _send_action_messages(db, broker_match, source_request, candidate_request, decision)
    if decision.action == "wait":
        broker_match.status = broker_match.status if broker_match.status else graph_status_for("matching")
    elif decision.action == "update_match":
        broker_match.status = graph_status_for("matching")
    elif decision.action == "retrieve_more":
        broker_match.status = "skipped"
        await clear_match_workflows(db, broker_match)
    elif decision.action == "send_message":
        broker_match.status = _status_from_sent_messages(decision, broker_match.status)
        _sync_matching_workflow_pointers(broker_match, source_request, candidate_request, decision)
    broker_match.expires_at = datetime.now(UTC) + timedelta(
        hours=settings.MEDIATION_NEGOTIATION_TIMEOUT_HOURS
    )
    return messages


async def _send_action_messages(
    db: AsyncSession,
    broker_match: BrokerMatch,
    source_request: BrokerRequest,
    candidate_request: BrokerRequest,
    decision: MatchingAgentDecision,
) -> list[BrokerMessage]:
    messages: list[BrokerMessage] = []
    if decision.message_to_source:
        messages.append(
            await _send_broker_message(
                db,
                broker_match,
                source_request,
                decision.message_to_source,
                "message_to_source",
            )
        )
    if decision.message_to_candidate:
        messages.append(
            await _send_broker_message(
                db,
                broker_match,
                candidate_request,
                decision.message_to_candidate,
                "message_to_candidate",
            )
        )
    return messages


def _sync_matching_workflow_pointers(
    broker_match: BrokerMatch,
    source_request: BrokerRequest,
    candidate_request: BrokerRequest,
    decision: MatchingAgentDecision,
) -> None:
    """Route only the parties that received screening questions back to matching."""
    if decision.message_to_source:
        set_active_workflow(source_request, broker_match, "matching")
    elif source_request.active_match_id == broker_match.id and source_request.active_graph == "matching":
        clear_active_workflow(source_request)
    elif source_request.status == "matching":
        source_request.status = "ready_for_matching"

    if decision.message_to_candidate:
        set_active_workflow(candidate_request, broker_match, "matching")
    elif (
        candidate_request.active_match_id == broker_match.id
        and candidate_request.active_graph == "matching"
    ):
        clear_active_workflow(candidate_request)
    elif candidate_request.status == "matching":
        candidate_request.status = "ready_for_matching"


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


async def _close_request_records(
    db: AsyncSession,
    broker_request: BrokerRequest,
    reason: str,
) -> None:
    broker_request.status = "closed"
    result = await db.execute(
        select(BrokerMatch).where(
            (
                (BrokerMatch.source_request_id == broker_request.id)
                | (BrokerMatch.candidate_request_id == broker_request.id)
            ),
            BrokerMatch.status.in_(ACTIVE_MATCHING_STATUSES | {"discovered", "qualified"}),
        )
    )
    for broker_match in result.scalars().all():
        broker_match.status = "closed"
        db.add(
            BrokerMediationEvent(
                match_id=broker_match.id,
                session_id=broker_request.session_id,
                user_id=broker_request.user_id,
                event_type="request_closed",
                payload={"reason": reason},
            )
        )


async def _active_matching_count(db: AsyncSession, source_request_id: str) -> int:
    result = await db.execute(
        select(BrokerMatch).where(
            BrokerMatch.source_request_id == source_request_id,
            BrokerMatch.status.in_(ACTIVE_MATCHING_STATUSES),
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


async def _get_session_request(
    db: AsyncSession,
    session_id: str,
) -> BrokerRequest | None:
    result = await db.execute(select(BrokerRequest).where(BrokerRequest.session_id == session_id))
    return result.scalar_one_or_none()


async def _load_mediation_history(
    db: AsyncSession,
    match_id: str,
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(BrokerMediationEvent)
        .where(BrokerMediationEvent.match_id == match_id)
        .order_by(BrokerMediationEvent.created_at)
    )
    events = list(result.scalars().all())[-40:]
    return [
        {
            "event_type": event.event_type,
            "session_id": event.session_id,
            "user_id": event.user_id,
            "message_text": event.message_text,
            "payload": event.payload,
            "created_at": event.created_at.isoformat() if event.created_at else None,
        }
        for event in events
    ]


def _merge_request_updates(
    broker_request: BrokerRequest,
    updates: dict[str, Any],
) -> None:
    if not updates:
        return
    structured_data = dict(broker_request.structured_data or {})
    mediation_terms = dict(structured_data.get("screening_terms") or {})
    for key, value in updates.items():
        if value in (None, "", [], {}):
            continue
        mediation_terms[key] = value
    structured_data["screening_terms"] = mediation_terms
    broker_request.structured_data = structured_data


def _status_from_sent_messages(
    decision: MatchingAgentDecision,
    fallback: str,
) -> str:
    if decision.message_to_source and decision.message_to_candidate:
        return graph_status_for("matching")
    if decision.message_to_source:
        return waiting_status_for("matching", "source")
    if decision.message_to_candidate:
        return waiting_status_for("matching", "candidate")
    return fallback or graph_status_for("matching")


def _initial_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(hours=settings.MEDIATION_INITIAL_TIMEOUT_HOURS)


def _request_context(broker_request: BrokerRequest | None) -> dict[str, Any] | None:
    if broker_request is None:
        return None
    return {
        "id": broker_request.id,
        "session_id": broker_request.session_id,
        "user_id": broker_request.user_id,
        "request_type": broker_request.request_type,
        "category": broker_request.category,
        "title": broker_request.title,
        "summary": broker_request.summary,
        "status": broker_request.status,
        "active_graph": broker_request.active_graph,
        "active_match_id": broker_request.active_match_id,
        "structured_data": broker_request.structured_data,
    }


def _session_context(broker_session: BrokerSession | None) -> dict[str, Any] | None:
    if broker_session is None:
        return None
    return {
        "id": broker_session.id,
        "status": broker_session.status,
        "title": broker_session.title,
        "summary": broker_session.summary,
    }


def _match_context(broker_match: BrokerMatch) -> dict[str, Any]:
    return {
        "id": broker_match.id,
        "status": broker_match.status,
        "score": broker_match.score,
        "rank": broker_match.rank,
        "match_reason": broker_match.match_reason,
        "outreach_strategy": broker_match.outreach_strategy,
    }


def _matching_agent_prompt() -> str:
    return (
        "You are BrokerAI's matching and screening agent. Your job is to decide whether "
        "a retrieved pair should be qualified before mediation begins. Matching is not "
        "negotiation and not contact sharing; it is the broker's private screening step "
        "to reduce weak leads, missing context, and unnecessary back-and-forth.\n\n"
        "Use the two requests, the match state, and the event history to choose the next "
        "step. Ask a focused screening question when a useful fact is missing from one "
        "side. Update request state when a reply adds durable facts. Qualify the match "
        "for mediation when the pair has enough credible fit for BrokerAI to start "
        "coordinating between the parties. Skip or reject when the path is not worth "
        "continuing.\n\n"
        "Do not ask for contact details, do not share contact details, and do not imply "
        "the parties have agreed to proceed. User-facing messages should be short, "
        "specific, neutral, and grounded in known facts — ordinary conversation like a "
        "question or 'I'll look and update you.' Never mention graphs, tools, steps, "
        "methods, scores, or a play-by-play of work. The plan is an audit-safe "
        "natural-language strategy note, not hidden reasoning. Return JSON only."
    )
