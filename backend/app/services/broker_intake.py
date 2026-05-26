from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field, ValidationError

from app.services.structured_llm import (
    invoke_structured_openrouter_model,
    is_llm_configured,
    llm_audit_info,
    llm_configuration_error,
)

logger = logging.getLogger(__name__)

WELCOME_MESSAGE = (
    "Tell me what you are looking for, offering, or trying to work out. I will help "
    "shape it into a clear request and take it from there."
)

PROMPT_VERSION = "broker-orchestrator-v3-natural-agent-contracts"


class IntakeDecision(BaseModel):
    reply: str = Field(min_length=1, max_length=1200)
    status: Literal["intake", "ready_for_matching"]
    summary: str = Field(default="", max_length=1000)
    title: str = Field(default="New broker request", max_length=140)
    missing_fields: list[str] = Field(default_factory=list)
    extracted_request: dict[str, Any] = Field(default_factory=dict)
    next_step: Literal["ask_follow_up", "ready_for_matching"]
    decision_summary: str = Field(
        default="",
        max_length=500,
        description="Concise audit summary. No hidden chain-of-thought.",
    )


class MasterDecision(BaseModel):
    route: Literal["clarify", "ready_for_matching"]
    status: Literal["intake", "ready_for_matching"]
    title: str = Field(default="New broker request", max_length=140)
    summary: str = Field(default="", max_length=1000)
    extracted_request: dict[str, Any] = Field(default_factory=dict)
    missing_context: list[str] = Field(default_factory=list)
    clarification_focus: str = Field(
        default="",
        max_length=240,
        description="The single most useful clarification theme for this turn, if route is clarify.",
    )
    readiness: Literal["low", "medium", "high"]
    broker_reply: str = Field(
        default="",
        max_length=1200,
        description="User-facing reply when the request can move forward without a clarifier.",
    )
    decision_summary: str = Field(
        default="",
        max_length=500,
        description="Concise audit summary of the master routing decision.",
    )


class ClarifierDecision(BaseModel):
    reply: str = Field(min_length=1, max_length=1200)
    missing_fields: list[str] = Field(default_factory=list)
    decision_summary: str = Field(
        default="",
        max_length=500,
        description="Concise audit summary of the clarification strategy.",
    )


class BrokerGraphState(TypedDict, total=False):
    conversation: list[dict[str, str]]
    current_summary: str | None
    latest_user_message: str | None
    compact_context: dict[str, Any]
    master_decision: MasterDecision
    clarifier_decision: ClarifierDecision
    decision: IntakeDecision
    request_payload: dict[str, Any] | None
    response_payload: dict[str, Any] | None
    error: str | None


@dataclass(frozen=True)
class IntakeRun:
    decision: IntakeDecision
    provider: str
    model: str
    request_payload: dict[str, Any] | None
    response_payload: dict[str, Any] | None
    error: str | None
    latency_ms: int | None


def create_title(message: str | None) -> str:
    if not message:
        return "New broker request"

    normalized = " ".join(message.strip().split())
    if not normalized:
        return "New broker request"

    title = normalized[:72].rstrip(" .,")
    return title if len(normalized) <= 72 else f"{title}..."


async def run_intake_decision(
    conversation: list[dict[str, str]],
    current_summary: str | None = None,
) -> IntakeRun:
    started_at = time.perf_counter()

    if not is_llm_configured():
        return _configuration_missing_run(conversation, current_summary, started_at)

    graph = _build_broker_graph()
    llm_info = llm_audit_info()

    try:
        final_state = await graph.ainvoke(
            {
                "conversation": conversation,
                "current_summary": current_summary,
            }
        )
        decision = final_state["decision"]
        latency_ms = round((time.perf_counter() - started_at) * 1000)
        logger.info(
            "BrokerAI master graph decision",
            extra={
                "provider": llm_info["provider"],
                "model": llm_info["model"],
                "status": decision.status,
                "next_step": decision.next_step,
                "decision_summary": decision.decision_summary,
                "latency_ms": latency_ms,
                "prompt_version": PROMPT_VERSION,
            },
        )
        return IntakeRun(
            decision=decision,
            provider=f"{llm_info['provider']}-langgraph",
            model=llm_info["model"],
            request_payload=final_state.get("request_payload"),
            response_payload=final_state.get("response_payload"),
            error=final_state.get("error"),
            latency_ms=latency_ms,
        )
    except (KeyError, TypeError, ValidationError, ValueError) as exc:
        latency_ms = round((time.perf_counter() - started_at) * 1000)
        logger.warning("BrokerAI master graph failed", exc_info=exc)
        return IntakeRun(
            decision=_llm_unavailable_decision(conversation),
            provider=f"{llm_info['provider']}-langgraph",
            model=llm_info["model"],
            request_payload=_request_audit_payload(conversation, current_summary),
            response_payload=None,
            error=str(exc),
            latency_ms=latency_ms,
        )


def generate_intake_reply(user_messages: list[str]) -> tuple[str, str, str]:
    decision = _llm_unavailable_decision(
        [{"role": "user", "content": message} for message in user_messages]
    )
    return decision.reply, decision.status, decision.summary


def create_summary(user_messages: list[str]) -> str:
    text = " ".join(message.strip() for message in user_messages if message.strip())
    text = re.sub(r"\s+", " ", text)
    return text[:500]


def _build_broker_graph():
    graph = StateGraph(BrokerGraphState)
    graph.add_node("prepare_context", _prepare_context_node)
    graph.add_node("master_broker", _master_broker_node)
    graph.add_node("clarifier", _clarifier_node)
    graph.add_node("finalize_decision", _finalize_decision_node)
    graph.set_entry_point("prepare_context")
    graph.add_edge("prepare_context", "master_broker")
    graph.add_conditional_edges(
        "master_broker",
        _route_after_master,
        {
            "clarifier": "clarifier",
            "finalize_decision": "finalize_decision",
        },
    )
    graph.add_edge("clarifier", "finalize_decision")
    graph.add_edge("finalize_decision", END)
    return graph.compile()


async def _prepare_context_node(state: BrokerGraphState) -> BrokerGraphState:
    conversation = state.get("conversation", [])
    latest_user_message = next(
        (
            message["content"]
            for message in reversed(conversation)
            if message.get("role") == "user" and message.get("content")
        ),
        None,
    )
    compact_context = {
        "current_summary": state.get("current_summary"),
        "latest_user_message": latest_user_message,
        "conversation": conversation[-14:],
    }
    return {
        **state,
        "latest_user_message": latest_user_message,
        "compact_context": compact_context,
        "request_payload": _request_audit_payload(
            conversation,
            state.get("current_summary"),
        ),
    }


async def _master_broker_node(state: BrokerGraphState) -> BrokerGraphState:
    decision = await invoke_structured_openrouter_model(
        parser_model=MasterDecision,
        system_prompt=_master_prompt(),
        human_payload={
            "broker_context": state["compact_context"],
            "task": (
                "Understand the current broker request and choose whether the workflow "
                "should clarify or move toward matching."
            ),
        },
        temperature=0.15,
    )
    return {
        **state,
        "master_decision": decision,
    }


def _route_after_master(state: BrokerGraphState) -> str:
    master_decision = state["master_decision"]
    return "clarifier" if master_decision.route == "clarify" else "finalize_decision"


async def _clarifier_node(state: BrokerGraphState) -> BrokerGraphState:
    clarifier_decision = await invoke_structured_openrouter_model(
        parser_model=ClarifierDecision,
        system_prompt=_clarifier_prompt(),
        human_payload={
            "broker_context": state["compact_context"],
            "master_decision": state["master_decision"].model_dump(),
            "task": (
                "Continue the BrokerAI conversation using the master's clarification "
                "decision."
            ),
        },
        temperature=0.25,
    )
    return {
        **state,
        "clarifier_decision": clarifier_decision,
    }


async def _finalize_decision_node(state: BrokerGraphState) -> BrokerGraphState:
    master = state["master_decision"]
    clarifier = state.get("clarifier_decision")
    latest_user_message = state.get("latest_user_message")

    if clarifier is not None:
        decision = IntakeDecision(
            reply=clarifier.reply.strip(),
            status="intake",
            summary=master.summary.strip() or state.get("current_summary") or "",
            title=master.title.strip() or create_title(latest_user_message),
            missing_fields=clarifier.missing_fields or master.missing_context,
            extracted_request={
                **master.extracted_request,
                "clarification_focus": master.clarification_focus,
            },
            next_step="ask_follow_up",
            decision_summary=_join_audit_summaries(
                master.decision_summary,
                clarifier.decision_summary,
            ),
        )
    else:
        decision = IntakeDecision(
            reply=(
                master.broker_reply.strip()
                or "I have enough context to prepare this request for matching."
            ),
            status="ready_for_matching",
            summary=master.summary.strip() or state.get("current_summary") or "",
            title=master.title.strip() or create_title(latest_user_message),
            missing_fields=[],
            extracted_request=master.extracted_request,
            next_step="ready_for_matching",
            decision_summary=master.decision_summary.strip()
            or "The master broker node found enough context to move forward.",
        )

    return {
        **state,
        "decision": decision,
        "response_payload": {
            "prompt_version": PROMPT_VERSION,
            "master_decision": master.model_dump(),
            "clarifier_decision": clarifier.model_dump() if clarifier else None,
            "decision": decision.model_dump(),
        },
    }


def _master_prompt() -> str:
    return (
        "You are BrokerAI's master intake agent. BrokerAI is a general broker for "
        "human requests that may lead to a useful match, counterparty, option, or "
        "coordinated outcome. Requests may concern needs, offers, services, goods, "
        "introductions, plans, opportunities, or other situations expressed in natural "
        "conversation.\n\n"
        "Your role is to understand the conversation as a living broker request and "
        "return the working state that the orchestration graph needs. Capture the "
        "user's objective, the meaning of the request, and the signals that would help "
        "future retrieval, ranking, and mediation. Summarize what is supported by the "
        "conversation without forcing it into a narrow category model. Use request_type "
        "and category when they are reasonably supported, and leave uncertain details "
        "uncertain rather than inventing them.\n\n"
        "Choose the next route with broker judgment. A request is ready_for_matching "
        "when BrokerAI can represent it honestly and begin a credible matching step "
        "from the available context. Use clarify when the remaining ambiguity prevents "
        "that next step or would send matching in a materially wrong direction. "
        "Clarification should improve progress, not turn intake into a rigid form.\n\n"
        "Keep this node focused on master-agent work: request state, routing, "
        "readiness, and an audit-safe decision summary. Do not output hidden reasoning. "
        "Do not fabricate user facts, consent, prices, availability, compatibility, or "
        "match quality.\n\n"
        "Return JSON only. If route is clarify, set status to intake, provide "
        "missing_context and a useful clarification_focus, and leave broker_reply empty. "
        "If route is ready_for_matching, set status to ready_for_matching and provide "
        "a brief broker_reply that moves the request forward without promising a match."
    )


def _clarifier_prompt() -> str:
    return (
        "You are BrokerAI's clarifier agent. The master intake agent has decided that "
        "the conversation should continue before matching begins and has provided the "
        "current clarification focus.\n\n"
        "Continue the conversation as a capable broker. Use the request context, the "
        "user's natural language, and the master's focus to ask for context that would "
        "make the request more useful for matching. Let the conversation sound human "
        "and domain-appropriate rather than like a schema or a fixed questionnaire. "
        "Acknowledge existing context when it helps the user continue naturally.\n\n"
        "Stay within clarification. Do not change the route, claim that matching has "
        "already started, evaluate candidates, or create facts the user did not give. "
        "Respect privacy during intake and avoid asking for secrets, credentials, or "
        "unnecessary contact details.\n\n"
        "Return JSON only. The reply field must contain only the user-facing message "
        "for this turn. missing_fields should name the unresolved context this turn "
        "targets. decision_summary is a brief audit note, not hidden reasoning."
    )


def _configuration_missing_run(
    conversation: list[dict[str, str]],
    current_summary: str | None,
    started_at: float,
) -> IntakeRun:
    llm_info = llm_audit_info()
    return IntakeRun(
        decision=_llm_unavailable_decision(conversation),
        provider=f"{llm_info['provider']}-langgraph",
        model=llm_info["model"],
        request_payload=_request_audit_payload(conversation, current_summary),
        response_payload=None,
        error=llm_configuration_error(),
        latency_ms=round((time.perf_counter() - started_at) * 1000),
    )


def _llm_unavailable_decision(conversation: list[dict[str, str]]) -> IntakeDecision:
    latest_user_message = next(
        (
            message["content"]
            for message in reversed(conversation)
            if message.get("role") == "user" and message.get("content")
        ),
        None,
    )
    title = create_title(latest_user_message)
    return IntakeDecision(
        reply=(
            "I can hold this request, but the BrokerAI decision model is not available "
            "right now. Once the model is configured, I can continue the broker flow."
        ),
        status="intake",
        summary=create_summary([latest_user_message] if latest_user_message else []),
        title=title,
        missing_fields=[],
        extracted_request={"raw_request": latest_user_message} if latest_user_message else {},
        next_step="ask_follow_up",
        decision_summary="The BrokerAI master graph could not run, so no routing decision was made.",
    )


def _join_audit_summaries(*summaries: str) -> str:
    compact = [summary.strip() for summary in summaries if summary and summary.strip()]
    return " ".join(compact)[:500] or "The master delegated to the clarifier for additional context."


def _request_audit_payload(
    conversation: list[dict[str, str]],
    current_summary: str | None,
) -> dict[str, Any]:
    llm_info = llm_audit_info()
    return {
        "prompt_version": PROMPT_VERSION,
        "provider": llm_info["provider"],
        "model": llm_info["model"],
        "graph_nodes": [
            "prepare_context",
            "master_broker",
            "clarifier",
            "finalize_decision",
        ],
        "message_count": len(conversation),
        "has_current_summary": bool(current_summary),
    }
