from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BrokerRequest, BrokerSession
from app.services.broker_intake import IntakeDecision

REQUEST_SCHEMA_VERSION = "broker_request.v1"


async def upsert_request_from_decision(
    db: AsyncSession,
    broker_session: BrokerSession,
    decision: IntakeDecision,
) -> BrokerRequest:
    structured_data = build_structured_request_data(decision)
    request_type = _string_value(structured_data, "request_type", "general")
    category = _optional_string_value(structured_data, "category")

    result = await db.execute(
        select(BrokerRequest).where(BrokerRequest.session_id == broker_session.id)
    )
    broker_request = result.scalar_one_or_none()

    if broker_request is None:
        broker_request = BrokerRequest(
            session_id=broker_session.id,
            user_id=broker_session.user_id,
            status="ready_for_matching",
            request_type=request_type,
            category=category,
            title=decision.title or broker_session.title,
            summary=decision.summary or broker_session.summary or "",
            structured_data=structured_data,
            embedding_status="pending",
            active_graph=None,
            active_match_id=None,
        )
        db.add(broker_request)
        return broker_request

    broker_request.status = "ready_for_matching"
    broker_request.request_type = request_type
    broker_request.category = category
    broker_request.title = decision.title or broker_session.title
    broker_request.summary = decision.summary or broker_session.summary or ""
    broker_request.structured_data = structured_data
    broker_request.embedding_status = "pending"
    broker_request.active_graph = None
    broker_request.active_match_id = None
    return broker_request


def build_structured_request_data(decision: IntakeDecision) -> dict[str, Any]:
    extracted = decision.extracted_request or {}
    return {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "request_type": _string_value(extracted, "request_type", "general"),
        "category": _optional_string_value(extracted, "category"),
        "title": decision.title,
        "summary": decision.summary,
        "status": decision.status,
        "missing_fields": decision.missing_fields,
        "next_step": decision.next_step,
        "decision_summary": decision.decision_summary,
        "details": extracted,
    }


def _string_value(data: dict[str, Any], key: str, default: str) -> str:
    value = data.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()[:80]
    return default


def _optional_string_value(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()[:120]
    return None
