from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

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
from app.services.broker_matching import ACTIVE_MEDIATION_STATUSES
from app.services.structured_llm import (
    invoke_structured_openrouter_model,
    is_llm_configured,
    llm_configuration_error,
)

logger = logging.getLogger(__name__)

MEDIATION_REPLY_VERSION = "broker-mediation-reply.v1"


class MediationReplyDecision(BaseModel):
    reply_kind: Literal["accept", "reject", "question", "update", "other"]
    agreement_reached: bool = Field(
        default=False,
        description=(
            "True when the latest reply completes mutual alignment on the core deal "
            "or match terms, including accepting a proposal the other party already made."
        ),
    )
    message_to_source: str = Field(default="", max_length=1200)
    message_to_candidate: str = Field(default="", max_length=1200)
    source_request_updates: dict[str, Any] = Field(default_factory=dict)
    candidate_request_updates: dict[str, Any] = Field(default_factory=dict)
    decision_summary: str = Field(
        default="",
        max_length=500,
        description="Audit-safe summary of mediation reply handling.",
    )


async def find_active_mediation_for_session(
    db: AsyncSession,
    broker_session: BrokerSession,
) -> tuple[BrokerMatch, BrokerRequest] | None:
    """Return the active mediation involving this session, if any."""
    request_result = await db.execute(
        select(BrokerRequest).where(BrokerRequest.session_id == broker_session.id)
    )
    broker_request = request_result.scalar_one_or_none()
    if broker_request is None:
        return None

    match_result = await db.execute(
        select(BrokerMatch).where(
            (
                (BrokerMatch.source_request_id == broker_request.id)
                | (BrokerMatch.candidate_request_id == broker_request.id)
            ),
            BrokerMatch.status.in_(ACTIVE_MEDIATION_STATUSES),
        )
    )
    broker_match = match_result.scalars().first()
    if broker_match is None:
        return None
    return broker_match, broker_request


async def handle_mediation_reply(
    db: AsyncSession,
    broker_session: BrokerSession,
    user_message: BrokerMessage,
    broker_match: BrokerMatch,
    party_request: BrokerRequest,
) -> list[BrokerMessage]:
    """Handle a user reply inside an active mediated match."""
    source_request = await db.get(BrokerRequest, broker_match.source_request_id)
    candidate_request = await db.get(BrokerRequest, broker_match.candidate_request_id)
    if source_request is None or candidate_request is None:
        broker_match.status = "closed"
        return [
            BrokerMessage(
                session_id=broker_session.id,
                role="assistant",
                content="I could not continue this mediation because one side is no longer available.",
            )
        ]

    party_role = "source" if party_request.id == source_request.id else "candidate"
    db.add(
        BrokerMediationEvent(
            match_id=broker_match.id,
            session_id=broker_session.id,
            user_id=party_request.user_id,
            event_type=f"{party_role}_reply_received",
            message_text=user_message.content,
            payload={"message_id": user_message.id},
        )
    )
    await db.flush()

    mediation_history = await _load_mediation_history(db, broker_match.id)
    decision = await _decide_mediation_reply(
        broker_match=broker_match,
        source_request=source_request,
        candidate_request=candidate_request,
        party_role=party_role,
        user_message=user_message.content,
        mediation_history=mediation_history,
    )
    assistant_messages = await _apply_mediation_decision(
        db=db,
        broker_match=broker_match,
        source_request=source_request,
        candidate_request=candidate_request,
        party_role=party_role,
        decision=decision,
    )
    broker_match.last_activity_at = datetime.now(UTC)
    db.add(
        BrokerMediationEvent(
            match_id=broker_match.id,
            session_id=broker_session.id,
            user_id=party_request.user_id,
            event_type="mediation_reply_decided",
            payload={
                "reply_version": MEDIATION_REPLY_VERSION,
                "party_role": party_role,
                "decision": decision.model_dump(),
            },
        )
    )
    return [
        message for message in assistant_messages if message.session_id == broker_session.id
    ]


async def _decide_mediation_reply(
    broker_match: BrokerMatch,
    source_request: BrokerRequest,
    candidate_request: BrokerRequest,
    party_role: str,
    user_message: str,
    mediation_history: list[dict[str, Any]],
) -> MediationReplyDecision:
    _require_llm_configuration()
    return await invoke_structured_openrouter_model(
        parser_model=MediationReplyDecision,
        system_prompt=_mediation_reply_prompt(),
        human_payload={
            "reply_version": MEDIATION_REPLY_VERSION,
            "match": {
                "id": broker_match.id,
                "status": broker_match.status,
                "outreach_strategy": broker_match.outreach_strategy,
                "match_reason": broker_match.match_reason,
            },
            "source_request": _request_context(source_request),
            "candidate_request": _request_context(candidate_request),
            "mediation_history": mediation_history,
            "replying_party": party_role,
            "user_message": user_message,
            "task": "Interpret this mediation reply and decide BrokerAI's next messages.",
        },
        temperature=0.1,
    )


async def _apply_mediation_decision(
    db: AsyncSession,
    broker_match: BrokerMatch,
    source_request: BrokerRequest,
    candidate_request: BrokerRequest,
    party_role: str,
    decision: MediationReplyDecision,
) -> list[BrokerMessage]:
    _merge_request_updates(source_request, decision.source_request_updates)
    _merge_request_updates(candidate_request, decision.candidate_request_updates)

    if decision.reply_kind == "reject":
        broker_match.status = "rejected"
        return await _send_decision_messages(
            db, broker_match, source_request, candidate_request, decision
        )

    if decision.reply_kind == "accept" or decision.agreement_reached:
        other_party = "candidate" if party_role == "source" else "source"
        accepted_by_both = await _has_acceptance_from(db, broker_match.id, other_party)
        agreement_reached = accepted_by_both or decision.agreement_reached
        if agreement_reached:
            broker_match.status = "accepted"
        else:
            broker_match.status = (
                "waiting_candidate" if party_role == "source" else "waiting_source"
            )
        broker_match.expires_at = datetime.now(UTC) + timedelta(
            hours=settings.MEDIATION_NEGOTIATION_TIMEOUT_HOURS
        )
        db.add(
            BrokerMediationEvent(
                match_id=broker_match.id,
                session_id=None,
                user_id=None,
                event_type=f"{party_role}_accepted",
                payload={"reply_version": MEDIATION_REPLY_VERSION},
            )
        )
        if decision.agreement_reached and not accepted_by_both:
            db.add(
                BrokerMediationEvent(
                    match_id=broker_match.id,
                    session_id=None,
                    user_id=None,
                    event_type=f"{other_party}_accepted",
                    payload={
                        "reply_version": MEDIATION_REPLY_VERSION,
                        "inferred_from": "prior_party_offer_or_alignment",
                    },
                )
            )
        messages = await _send_decision_messages(
            db, broker_match, source_request, candidate_request, decision
        )
        if agreement_reached:
            messages.extend(await share_match_contacts(db, broker_match))
        return messages

    broker_match.status = "negotiating"
    broker_match.expires_at = datetime.now(UTC) + timedelta(
        hours=settings.MEDIATION_NEGOTIATION_TIMEOUT_HOURS
    )
    return await _send_decision_messages(
        db, broker_match, source_request, candidate_request, decision
    )


async def _send_decision_messages(
    db: AsyncSession,
    broker_match: BrokerMatch,
    source_request: BrokerRequest,
    candidate_request: BrokerRequest,
    decision: MediationReplyDecision,
) -> list[BrokerMessage]:
    messages = []
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


async def _has_acceptance_from(
    db: AsyncSession,
    match_id: str,
    party_role: str,
) -> bool:
    result = await db.execute(
        select(BrokerMediationEvent).where(
            BrokerMediationEvent.match_id == match_id,
            BrokerMediationEvent.event_type == f"{party_role}_accepted",
        )
    )
    return result.scalar_one_or_none() is not None


async def _load_mediation_history(
    db: AsyncSession,
    match_id: str,
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(BrokerMediationEvent)
        .where(BrokerMediationEvent.match_id == match_id)
        .order_by(BrokerMediationEvent.created_at)
    )
    events = list(result.scalars().all())[-30:]
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


def _request_context(broker_request: BrokerRequest) -> dict[str, Any]:
    return {
        "id": broker_request.id,
        "request_type": broker_request.request_type,
        "category": broker_request.category,
        "title": broker_request.title,
        "summary": broker_request.summary,
        "structured_data": broker_request.structured_data,
    }


def _require_llm_configuration() -> None:
    if not is_llm_configured():
        raise RuntimeError(f"{llm_configuration_error()} for mediation.")


def _mediation_reply_prompt() -> str:
    return (
        "You are BrokerAI's live mediation handler. BrokerAI is a trusted intermediary "
        "whose job is to reduce the time, noise, spam, browsing, and manual negotiation "
        "involved in finding the right person. Interpret the latest user reply within "
        "the active match and choose the broker response that most cleanly advances, "
        "pauses, updates, or closes the mediation.\n\n"
        "Read mediation_history as the source of truth. Preserve continuity: do not "
        "repeat resolved questions, revive stale terms, or ignore concessions and "
        "updates already made. When a user changes any meaningful condition, preference, "
        "constraint, offer, requirement, or next-step detail, carry it forward in the "
        "appropriate request update object so future decisions use the current state.\n\n"
        "Communicate like an experienced broker. Relay only what is useful to the "
        "other side, translate vague replies into practical next steps when possible, "
        "and avoid adding negotiation friction. Keep messages concise, professional, "
        "and privacy-aware. Do not reveal contact details, private facts, or unsupported "
        "claims unless both parties have clearly agreed to proceed.\n\n"
        "Use agreement_reached when the latest reply completes mutual alignment on "
        "the core terms. This includes a party accepting a concrete proposal or "
        "counteroffer the other party already made; do not require the proposing party "
        "to confirm the same terms again just to unlock the accepted-match flow.\n\n"
        "When both sides have aligned on the core terms, do not ask them to choose "
        "between communication channels or ask for another generic confirmation. Move "
        "toward the product's accepted-match flow: BrokerAI shares contact cards in "
        "chat, and the Connect action creates the party connection.\n\n"
        "Return JSON only. decision_summary must be audit-safe and must not contain "
        "hidden reasoning."
    )
