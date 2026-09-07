from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, TypedDict

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    BrokerDecisionLog,
    BrokerMatch,
    BrokerMediationEvent,
    BrokerMessage,
    BrokerRequest,
    BrokerSession,
)
from app.services.broker_intake import WELCOME_MESSAGE, create_title, run_intake_decision
from app.services.broker_match_graph import (
    process_next_matches_for_request,
    run_match_graph_for_message,
    run_match_graph_for_request,
)
from app.services.broker_mediation_graph import run_mediation_graph_for_message
from app.services.broker_rag import index_request
from app.services.broker_request_builder import upsert_request_from_decision
from app.services.broker_workflow import (
    MATCH_ACTIVE_STATUSES,
    clear_match_workflows,
    get_active_workflow_match,
)

logger = logging.getLogger(__name__)

ORCHESTRATOR_VERSION = "broker-master-orchestrator.v1"


class BrokerOperationDecision(BaseModel):
    operation: Literal["intake_graph", "matching_graph", "mediation_graph"]
    decision_summary: str = Field(
        default="",
        max_length=500,
        description="Audit-safe summary of the routing decision.",
    )


class BrokerOrchestratorState(TypedDict, total=False):
    db: AsyncSession
    broker_session: BrokerSession
    content: str
    user_message: BrokerMessage
    active_matching: tuple[BrokerMatch, BrokerRequest] | None
    active_mediation: tuple[BrokerMatch, BrokerRequest] | None
    session_request: BrokerRequest | None
    operation_decision: BrokerOperationDecision
    assistant_messages: list[BrokerMessage]


@dataclass
class SessionCreationResult:
    session: BrokerSession
    messages: list[BrokerMessage]
    request: BrokerRequest | None


async def create_session_with_orchestration(
    db: AsyncSession,
    user_id: str,
    initial_message: str | None,
) -> SessionCreationResult:
    """Create a broker session and run intake/matching if the user starts with a request."""
    normalized_initial = initial_message.strip() if initial_message else None
    broker_session = BrokerSession(
        user_id=user_id,
        title=create_title(normalized_initial),
        status="intake",
        summary=normalized_initial,
    )
    db.add(broker_session)
    await db.flush()

    messages = [
        BrokerMessage(
            session_id=broker_session.id,
            role="assistant",
            content=WELCOME_MESSAGE,
        )
    ]

    if normalized_initial:
        user_message = BrokerMessage(
            session_id=broker_session.id,
            role="user",
            content=normalized_initial,
        )
        messages.append(user_message)
        intake_run = await _run_intake_for_session(
            db=db,
            broker_session=broker_session,
            user_message=user_message,
            existing_messages=messages,
            decision_type="session_create",
        )
        assistant_message = BrokerMessage(
            session_id=broker_session.id,
            role="assistant",
            content=intake_run.decision.reply,
        )
        messages.append(assistant_message)

    db.add_all(messages)
    await db.flush()
    if normalized_initial:
        await _process_ready_request(db, broker_session, intake_run)
    broker_request = await _get_session_request(db, broker_session.id)
    return SessionCreationResult(
        session=broker_session,
        messages=messages,
        request=broker_request,
    )


async def handle_session_message_with_orchestration(
    db: AsyncSession,
    broker_session: BrokerSession,
    content: str,
) -> list[BrokerMessage]:
    """Route a user message through the master orchestrator graph."""
    graph = _build_orchestrator_graph()
    final_state = await graph.ainvoke(
        {
            "db": db,
            "broker_session": broker_session,
            "content": content,
        }
    )
    return [final_state["user_message"], *final_state.get("assistant_messages", [])]


async def process_stale_mediations(db: AsyncSession, limit: int = 50) -> list[BrokerMatch]:
    """Expire timed-out active mediations and try the next candidate for each source."""
    result = await db.execute(
        select(BrokerMatch)
        .where(
            BrokerMatch.status.in_(MATCH_ACTIVE_STATUSES),
            BrokerMatch.expires_at.is_not(None),
            BrokerMatch.expires_at <= datetime.now(UTC),
        )
        .order_by(BrokerMatch.expires_at)
        .limit(limit)
    )
    stale_matches = list(result.scalars().all())
    for broker_match in stale_matches:
        broker_match.status = "expired"
        await clear_match_workflows(db, broker_match)
        db.add(
            BrokerMediationEvent(
                match_id=broker_match.id,
                session_id=None,
                user_id=None,
                event_type="match_expired",
                payload={"reason": "mediation_timeout"},
            )
        )
        source_request = await db.get(BrokerRequest, broker_match.source_request_id)
        if source_request is None or source_request.embedding_status != "embedded":
            continue
        try:
            await process_next_matches_for_request(db, source_request)
        except Exception as exc:
            logger.warning(
                "Next-match processing after stale mediation failed",
                exc_info=exc,
                extra={"match_id": broker_match.id},
            )
    return stale_matches


def _build_orchestrator_graph():
    graph = StateGraph(BrokerOrchestratorState)
    graph.add_node("prepare_context", _prepare_context_node)
    graph.add_node("master_router", _master_router_node)
    graph.add_node("intake", _intake_node)
    graph.add_node("matching", _matching_node)
    graph.add_node("mediation", _mediation_node)
    graph.set_entry_point("prepare_context")
    graph.add_edge("prepare_context", "master_router")
    graph.add_conditional_edges(
        "master_router",
        _route_after_master,
        {
            "intake": "intake",
            "matching": "matching",
            "mediation": "mediation",
        },
    )
    graph.add_edge("intake", END)
    graph.add_edge("matching", END)
    graph.add_edge("mediation", END)
    return graph.compile()


async def _prepare_context_node(
    state: BrokerOrchestratorState,
) -> BrokerOrchestratorState:
    db = state["db"]
    broker_session = state["broker_session"]
    session_request = await _get_session_request(db, broker_session.id)
    active_matching = (
        (
            await get_active_workflow_match(db, session_request, "matching"),
            session_request,
        )
        if session_request is not None
        else None
    )
    if active_matching and active_matching[0] is None:
        active_matching = None
    active_mediation = (
        (
            await get_active_workflow_match(db, session_request, "mediation"),
            session_request,
        )
        if session_request is not None
        else None
    )
    if active_mediation and active_mediation[0] is None:
        active_mediation = None
    user_message = BrokerMessage(
        session_id=broker_session.id,
        role="user",
        content=state["content"],
    )
    db.add(user_message)
    await db.flush()
    return {
        **state,
        "active_matching": active_matching,
        "active_mediation": active_mediation,
        "session_request": session_request,
        "user_message": user_message,
    }


async def _master_router_node(
    state: BrokerOrchestratorState,
) -> BrokerOrchestratorState:
    session_request = state.get("session_request")
    if state.get("active_matching") is not None:
        decision = BrokerOperationDecision(
            operation="matching_graph",
            decision_summary=(
                "The request has an active matching workflow pointer for the current match."
            ),
        )
    elif state.get("active_mediation") is not None:
        decision = BrokerOperationDecision(
            operation="mediation_graph",
            decision_summary=(
                "The request has an active mediation workflow pointer for the current match."
            ),
        )
    elif session_request is None:
        decision = BrokerOperationDecision(
            operation="intake_graph",
            decision_summary="No structured request was found for this session.",
        )
    elif session_request.status == "closed":
        decision = BrokerOperationDecision(
            operation="intake_graph",
            decision_summary="The request is closed, so the message is handled as general intake context.",
        )
    else:
        decision = BrokerOperationDecision(
            operation="intake_graph",
            decision_summary=(
                "No active workflow pointer exists, so the message updates or starts "
                "the user's canonical broker request."
            ),
        )
    return {**state, "operation_decision": decision}


def _route_after_master(state: BrokerOrchestratorState) -> str:
    operation = state["operation_decision"].operation
    if operation == "matching_graph":
        return "matching"
    if operation == "mediation_graph":
        return "mediation"
    return "intake"


async def _intake_node(state: BrokerOrchestratorState) -> BrokerOrchestratorState:
    db = state["db"]
    broker_session = state["broker_session"]
    user_message = state["user_message"]
    existing_messages_result = await db.execute(
        select(BrokerMessage)
        .where(BrokerMessage.session_id == broker_session.id)
        .order_by(BrokerMessage.created_at)
    )
    existing_messages = [
        message for message in existing_messages_result.scalars().all()
        if message.id != user_message.id
    ]
    intake_run = await _run_intake_for_session(
        db=db,
        broker_session=broker_session,
        user_message=user_message,
        existing_messages=[*existing_messages, user_message],
        decision_type="message_reply",
    )
    assistant_message = BrokerMessage(
        session_id=broker_session.id,
        role="assistant",
        content=intake_run.decision.reply,
    )
    db.add(assistant_message)
    await db.flush()
    await _process_ready_request(db, broker_session, intake_run)
    return {**state, "assistant_messages": [assistant_message]}


async def _matching_node(state: BrokerOrchestratorState) -> BrokerOrchestratorState:
    try:
        assistant_messages = await run_match_graph_for_message(
            db=state["db"],
            broker_session=state["broker_session"],
            user_message=state["user_message"],
            active_matching=state.get("active_matching"),
        )
    except Exception as exc:
        logger.warning(
            "BrokerAI matching handling failed",
            exc_info=exc,
            extra={
                "session_id": state["broker_session"].id,
                "active_matching": bool(state.get("active_matching")),
            },
        )
        assistant_messages = [
            BrokerMessage(
                session_id=state["broker_session"].id,
                role="assistant",
                content=(
                    "I noted your reply, but I could not safely continue matching "
                    "right now. Please try again once the broker model is available."
                ),
            )
        ]
        state["db"].add_all(assistant_messages)
        await state["db"].flush()
    return {**state, "assistant_messages": assistant_messages}


async def _mediation_node(state: BrokerOrchestratorState) -> BrokerOrchestratorState:
    try:
        assistant_messages = await run_mediation_graph_for_message(
            db=state["db"],
            broker_session=state["broker_session"],
            user_message=state["user_message"],
            active_mediation=state.get("active_mediation"),
        )
    except Exception as exc:
        logger.warning(
            "BrokerAI mediation handling failed",
            exc_info=exc,
            extra={
                "session_id": state["broker_session"].id,
                "active_mediation": bool(state.get("active_mediation")),
            },
        )
        assistant_messages = [
            BrokerMessage(
                session_id=state["broker_session"].id,
                role="assistant",
                content=(
                    "I noted your reply, but I could not safely continue this mediation "
                    "right now. Please try again once the broker model is available."
                ),
            )
        ]
        state["db"].add_all(assistant_messages)
        await state["db"].flush()
    return {**state, "assistant_messages": assistant_messages}


async def _run_intake_for_session(
    db: AsyncSession,
    broker_session: BrokerSession,
    user_message: BrokerMessage,
    existing_messages: list[BrokerMessage],
    decision_type: str,
):
    intake_run = await run_intake_decision(
        _conversation_payload(existing_messages),
        current_summary=broker_session.summary,
    )
    if broker_session.title == "New broker request":
        broker_session.title = _decision_title_or_fallback(
            intake_run.decision.title,
            create_title(user_message.content),
        )
    else:
        broker_session.title = _decision_title_or_fallback(
            intake_run.decision.title,
            broker_session.title,
        )
    broker_session.status = intake_run.decision.status
    broker_session.summary = intake_run.decision.summary
    db.add(_decision_log(broker_session.id, decision_type, intake_run))
    return intake_run


async def _process_ready_request(
    db: AsyncSession,
    broker_session: BrokerSession,
    intake_run,
) -> BrokerRequest | None:
    if intake_run.decision.status in {"closed", "paused"}:
        return await _process_request_lifecycle_decision(db, broker_session, intake_run)
    if intake_run.decision.status != "ready_for_matching":
        return None
    broker_request = await upsert_request_from_decision(
        db,
        broker_session,
        intake_run.decision,
    )
    await db.flush()
    await index_request(broker_request)
    if broker_request.embedding_status != "embedded":
        return broker_request
    try:
        await run_match_graph_for_request(db, broker_request)
    except Exception as exc:
        logger.warning(
            "Automatic match retrieval/evaluation/mediation failed",
            exc_info=exc,
            extra={"request_id": broker_request.id},
        )
    return broker_request


async def _process_request_lifecycle_decision(
    db: AsyncSession,
    broker_session: BrokerSession,
    intake_run,
) -> BrokerRequest | None:
    broker_request = await _get_session_request(db, broker_session.id)
    if broker_request is None:
        return None

    broker_request.status = intake_run.decision.status
    broker_request.active_graph = None
    broker_request.active_match_id = None
    if intake_run.decision.status == "closed":
        result = await db.execute(
            select(BrokerMatch).where(
                (
                    (BrokerMatch.source_request_id == broker_request.id)
                    | (BrokerMatch.candidate_request_id == broker_request.id)
                ),
                BrokerMatch.status.in_(MATCH_ACTIVE_STATUSES | {"discovered", "qualified", "accepted"}),
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
                    payload={"reason": "master_request_lifecycle"},
                )
            )
    return broker_request


async def _get_session_request(
    db: AsyncSession,
    session_id: str,
) -> BrokerRequest | None:
    result = await db.execute(
        select(BrokerRequest).where(BrokerRequest.session_id == session_id)
    )
    return result.scalar_one_or_none()


def _conversation_payload(messages: list[BrokerMessage]) -> list[dict[str, str]]:
    return [{"role": message.role, "content": message.content} for message in messages]


def _decision_title_or_fallback(decision_title: str | None, fallback: str) -> str:
    title = decision_title.strip() if decision_title else ""
    return title if title and title != "New broker request" else fallback


def _decision_log(
    session_id: str,
    decision_type: str,
    intake_run,
) -> BrokerDecisionLog:
    return BrokerDecisionLog(
        session_id=session_id,
        provider=intake_run.provider,
        model=intake_run.model,
        decision_type=decision_type,
        status=intake_run.decision.status,
        decision_summary=intake_run.decision.decision_summary,
        request_payload=intake_run.request_payload,
        response_payload=intake_run.response_payload,
        error=intake_run.error,
        latency_ms=intake_run.latency_ms,
    )
