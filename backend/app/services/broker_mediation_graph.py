from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    BrokerMatch,
    BrokerMediationEvent,
    BrokerMessage,
    BrokerRequest,
    BrokerSession,
)
from app.services.broker_contact import share_match_contacts
from app.services.broker_workflow import (
    clear_active_workflow,
    clear_match_workflows,
    graph_status_for,
    party_role_for_request,
    set_active_workflow,
    waiting_status_for,
)
from app.services.structured_llm import invoke_structured_openrouter_model

logger = logging.getLogger(__name__)

MEDIATION_GRAPH_VERSION = "broker-mediation-graph.v2"
MEDIATION_AGENT_VERSION = "broker-mediation-agent.v2"


class MediationAgentDecision(BaseModel):
    plan: str = Field(default="", max_length=1600)
    action: Literal[
        "send_message",
        "wait",
        "update_match",
        "reject_match",
        "accept_match",
        "share_contacts",
        "close_request",
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
    source_after_success_status: Literal[
        "ready_for_matching",
        "fulfilled",
        "paused",
        "closed",
    ] = "ready_for_matching"
    candidate_after_success_status: Literal[
        "ready_for_matching",
        "fulfilled",
        "paused",
        "closed",
    ] = "ready_for_matching"
    decision_summary: str = Field(default="", max_length=500)


class MediationGraphState(TypedDict, total=False):
    db: AsyncSession
    broker_session: BrokerSession
    broker_match: BrokerMatch
    user_message: BrokerMessage
    active_mediation: tuple[BrokerMatch, BrokerRequest] | None
    assistant_messages: list[BrokerMessage]


async def start_mediation_for_match(
    db: AsyncSession,
    broker_match: BrokerMatch,
) -> list[BrokerMessage]:
    """Start mediation for a qualified match."""
    graph = _build_mediation_graph()
    final_state = await graph.ainvoke(
        {
            "db": db,
            "broker_match": broker_match,
        }
    )
    return final_state.get("assistant_messages", [])


async def run_mediation_graph_for_message(
    db: AsyncSession,
    broker_session: BrokerSession,
    user_message: BrokerMessage,
    active_mediation: tuple[BrokerMatch, BrokerRequest] | None,
) -> list[BrokerMessage]:
    """Handle a user reply inside an active mediation workflow."""
    graph = _build_mediation_graph()
    final_state = await graph.ainvoke(
        {
            "db": db,
            "broker_session": broker_session,
            "user_message": user_message,
            "active_mediation": active_mediation,
        }
    )
    return final_state.get("assistant_messages", [])


def _build_mediation_graph():
    graph = StateGraph(MediationGraphState)
    graph.add_node("mediate", _mediate_node)
    graph.set_entry_point("mediate")
    graph.add_edge("mediate", END)
    return graph.compile()


async def _mediate_node(state: MediationGraphState) -> MediationGraphState:
    db = state["db"]
    broker_match = state.get("broker_match")
    party_request: BrokerRequest | None = None
    party_role: str | None = None
    user_message = state.get("user_message")
    phase: Literal["initial", "reply"] = "initial"

    if broker_match is None:
        active_mediation = state.get("active_mediation")
        if active_mediation is None:
            return {**state, "assistant_messages": []}
        broker_match, party_request = active_mediation
        phase = "reply"

    source_request = await db.get(BrokerRequest, broker_match.source_request_id)
    candidate_request = await db.get(BrokerRequest, broker_match.candidate_request_id)
    if source_request is None or candidate_request is None:
        broker_match.status = "closed"
        if user_message is None:
            return {**state, "assistant_messages": []}
        message = BrokerMessage(
            session_id=user_message.session_id,
            role="assistant",
            content="I could not continue this mediation because one side is no longer available.",
        )
        db.add(message)
        await db.flush()
        return {**state, "assistant_messages": [message]}

    if party_request is not None and user_message is not None:
        party_role = party_role_for_request(broker_match, party_request)
        db.add(
            BrokerMediationEvent(
                match_id=broker_match.id,
                session_id=user_message.session_id,
                user_id=party_request.user_id,
                event_type=f"{party_role}_mediation_reply_received",
                message_text=user_message.content,
                payload={"message_id": user_message.id},
            )
        )
        clear_active_workflow(party_request)
        await db.flush()

    history = await _load_mediation_history(db, broker_match.id)
    decision = await _decide_mediation_action(
        broker_match=broker_match,
        source_request=source_request,
        candidate_request=candidate_request,
        mediation_history=history,
        phase=phase,
        replying_party=party_role,
        user_message=user_message.content if user_message else None,
    )
    messages = await _apply_mediation_action(
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
            session_id=user_message.session_id if user_message else None,
            user_id=party_request.user_id if party_request else None,
            event_type="mediation_action_decided",
            payload={
                "mediation_graph_version": MEDIATION_GRAPH_VERSION,
                "mediation_agent_version": MEDIATION_AGENT_VERSION,
                "phase": phase,
                "party_role": party_role,
                "decision": decision.model_dump(),
            },
        )
    )
    if user_message is None:
        return {**state, "assistant_messages": messages}
    return {
        **state,
        "assistant_messages": [
            message for message in messages if message.session_id == user_message.session_id
        ],
    }


async def _decide_mediation_action(
    broker_match: BrokerMatch,
    source_request: BrokerRequest,
    candidate_request: BrokerRequest,
    mediation_history: list[dict[str, Any]],
    phase: Literal["initial", "reply"],
    replying_party: str | None = None,
    user_message: str | None = None,
) -> MediationAgentDecision:
    return await invoke_structured_openrouter_model(
        parser_model=MediationAgentDecision,
        system_prompt=_mediation_agent_prompt(),
        human_payload={
            "mediation_graph_version": MEDIATION_GRAPH_VERSION,
            "mediation_agent_version": MEDIATION_AGENT_VERSION,
            "phase": phase,
            "match": _match_context(broker_match),
            "source_request": _request_context(source_request),
            "candidate_request": _request_context(candidate_request),
            "mediation_history": mediation_history,
            "replying_party": replying_party,
            "user_message": user_message,
            "available_actions": [
                "send_message",
                "wait",
                "update_match",
                "reject_match",
                "accept_match",
                "share_contacts",
                "close_request",
                "retrieve_more",
                "skip_match",
                "move_to_next_match",
            ],
            "task": "Plan and choose the next broker mediation action.",
        },
        temperature=0.1,
    )


async def _apply_mediation_action(
    db: AsyncSession,
    broker_match: BrokerMatch,
    source_request: BrokerRequest,
    candidate_request: BrokerRequest,
    decision: MediationAgentDecision,
    party_role: str | None,
    party_request: BrokerRequest | None,
) -> list[BrokerMessage]:
    _merge_request_updates(source_request, decision.source_request_updates)
    _merge_request_updates(candidate_request, decision.candidate_request_updates)

    if decision.action == "close_request" and party_request is not None:
        await _close_request_records(db, party_request, "mediation_party_closed_request")
        broker_match.status = "closed"
        await clear_match_workflows(db, broker_match, next_status="closed")
        return await _send_action_messages(db, broker_match, source_request, candidate_request, decision)

    if decision.action in {"reject_match", "skip_match", "move_to_next_match", "retrieve_more"}:
        broker_match.status = "rejected" if decision.action == "reject_match" else "skipped"
        await clear_match_workflows(db, broker_match)
        return await _send_action_messages(db, broker_match, source_request, candidate_request, decision)

    if decision.action in {"accept_match", "share_contacts"} or decision.agreement_reached:
        await _record_acceptance_events(db, broker_match, party_role, decision.agreement_reached)
        broker_match.status = "accepted"
        await clear_match_workflows(db, broker_match)
        messages = await _send_action_messages(
            db,
            broker_match,
            source_request,
            candidate_request,
            decision,
        )
        messages.extend(await share_match_contacts(db, broker_match))
        _set_after_success_statuses(source_request, candidate_request, decision)
        return messages

    messages = await _send_action_messages(db, broker_match, source_request, candidate_request, decision)
    if decision.action == "wait":
        broker_match.status = broker_match.status if broker_match.status else graph_status_for("mediation")
    elif decision.action == "update_match":
        broker_match.status = graph_status_for("mediation")
    elif decision.action == "send_message":
        broker_match.status = _status_from_sent_messages(decision, broker_match.status)
        _sync_mediation_workflow_pointers(broker_match, source_request, candidate_request, decision)
    broker_match.expires_at = datetime.now(UTC) + timedelta(
        hours=settings.MEDIATION_NEGOTIATION_TIMEOUT_HOURS
    )
    return messages


async def _send_action_messages(
    db: AsyncSession,
    broker_match: BrokerMatch,
    source_request: BrokerRequest,
    candidate_request: BrokerRequest,
    decision: MediationAgentDecision,
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


def _sync_mediation_workflow_pointers(
    broker_match: BrokerMatch,
    source_request: BrokerRequest,
    candidate_request: BrokerRequest,
    decision: MediationAgentDecision,
) -> None:
    """Route only the parties who received mediation prompts back to mediation."""
    if decision.message_to_source:
        set_active_workflow(source_request, broker_match, "mediation")
    elif source_request.active_match_id == broker_match.id and source_request.active_graph == "mediation":
        clear_active_workflow(source_request)
    elif source_request.status == "mediation":
        source_request.status = "ready_for_matching"

    if decision.message_to_candidate:
        set_active_workflow(candidate_request, broker_match, "mediation")
    elif (
        candidate_request.active_match_id == broker_match.id
        and candidate_request.active_graph == "mediation"
    ):
        clear_active_workflow(candidate_request)
    elif candidate_request.status == "mediation":
        candidate_request.status = "ready_for_matching"


def _set_after_success_statuses(
    source_request: BrokerRequest,
    candidate_request: BrokerRequest,
    decision: MediationAgentDecision,
) -> None:
    source_request.status = decision.source_after_success_status
    candidate_request.status = decision.candidate_after_success_status
    source_request.active_graph = None
    source_request.active_match_id = None
    candidate_request.active_graph = None
    candidate_request.active_match_id = None


async def _record_acceptance_events(
    db: AsyncSession,
    broker_match: BrokerMatch,
    party_role: str | None,
    agreement_reached: bool,
) -> None:
    if party_role is not None:
        db.add(
            BrokerMediationEvent(
                match_id=broker_match.id,
                session_id=None,
                user_id=None,
                event_type=f"{party_role}_accepted",
                payload={"mediation_agent_version": MEDIATION_AGENT_VERSION},
            )
        )
    if agreement_reached:
        for role in ("source", "candidate"):
            if role != party_role:
                db.add(
                    BrokerMediationEvent(
                        match_id=broker_match.id,
                        session_id=None,
                        user_id=None,
                        event_type=f"{role}_accepted",
                        payload={
                            "mediation_agent_version": MEDIATION_AGENT_VERSION,
                            "inferred_from": "agreement_reached",
                        },
                    )
                )


async def _close_request_records(
    db: AsyncSession,
    broker_request: BrokerRequest,
    reason: str,
) -> None:
    broker_request.status = "closed"
    broker_request.active_graph = None
    broker_request.active_match_id = None
    result = await db.execute(
        select(BrokerMatch).where(
            (
                (BrokerMatch.source_request_id == broker_request.id)
                | (BrokerMatch.candidate_request_id == broker_request.id)
            ),
            BrokerMatch.status.in_(
                {
                    "mediating",
                    "waiting_source_mediation",
                    "waiting_candidate_mediation",
                    "accepted",
                }
            ),
        )
    )
    for broker_match in result.scalars().all():
        broker_match.status = "closed"
        await clear_match_workflows(db, broker_match, next_status="closed")
        db.add(
            BrokerMediationEvent(
                match_id=broker_match.id,
                session_id=broker_request.session_id,
                user_id=broker_request.user_id,
                event_type="request_closed",
                payload={"reason": reason},
            )
        )


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
    mediation_terms = dict(structured_data.get("mediation_terms") or {})
    for key, value in updates.items():
        if value in (None, "", [], {}):
            continue
        mediation_terms[key] = value
    structured_data["mediation_terms"] = mediation_terms
    broker_request.structured_data = structured_data


def _status_from_sent_messages(
    decision: MediationAgentDecision,
    fallback: str,
) -> str:
    if decision.message_to_source and decision.message_to_candidate:
        return graph_status_for("mediation")
    if decision.message_to_source:
        return waiting_status_for("mediation", "source")
    if decision.message_to_candidate:
        return waiting_status_for("mediation", "candidate")
    return fallback or graph_status_for("mediation")


def _request_context(broker_request: BrokerRequest) -> dict[str, Any]:
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


def _match_context(broker_match: BrokerMatch) -> dict[str, Any]:
    return {
        "id": broker_match.id,
        "status": broker_match.status,
        "score": broker_match.score,
        "rank": broker_match.rank,
        "match_reason": broker_match.match_reason,
        "outreach_strategy": broker_match.outreach_strategy,
    }


def _mediation_agent_prompt() -> str:
    return (
        "You are BrokerAI's mediation agent. You operate only after the matching graph "
        "has qualified a pair as worth coordinating. Your work is to reduce manual "
        "negotiation, preserve trust, and move a qualified pair toward agreement, "
        "contact sharing, connection, rejection, or a clean stop.\n\n"
        "Use the source request, candidate request, match state, event history, and "
        "current user reply. Relay useful information between parties without exposing "
        "private details prematurely. Ask the next party only when their answer is "
        "needed to advance the match. Avoid generic interest checks; make every message "
        "carry concrete broker progress.\n\n"
        "When a reply changes any meaningful condition, preference, constraint, offer, "
        "requirement, or next-step detail, write it into the appropriate request update "
        "object. Use agreement_reached when the latest reply completes mutual alignment "
        "on the core terms. After agreement, move to the accepted flow so contact cards "
        "can be shared; the product's Connect action creates the direct party "
        "connection.\n\n"
        "Messages must be concise, neutral, grounded, and privacy-safe natural "
        "conversation only. Never mention graphs, tools, steps, methods, or a "
        "play-by-play of work. The plan field is an audit-safe strategy note, not "
        "hidden reasoning. Return JSON only."
    )
