from __future__ import annotations

from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BrokerMatch, BrokerRequest

BrokerGraphName = Literal["matching", "mediation"]
BrokerPartyRole = Literal["source", "candidate"]

REQUEST_TERMINAL_STATUSES = {"closed", "fulfilled"}
REQUEST_HOLD_STATUSES = {"paused"}
REQUEST_REUSABLE_STATUSES = {"ready_for_matching", "matching", "mediation"}

MATCH_SCREENING_STATUSES = {
    "screening",
    "waiting_source_screening",
    "waiting_candidate_screening",
}
MATCH_MEDIATION_STATUSES = {
    "mediating",
    "waiting_source_mediation",
    "waiting_candidate_mediation",
}
MATCH_ACTIVE_STATUSES = MATCH_SCREENING_STATUSES | MATCH_MEDIATION_STATUSES | {"qualified"}
MATCH_TERMINAL_STATUSES = {
    "accepted",
    "connected",
    "rejected",
    "skipped",
    "expired",
    "closed",
}


def party_role_for_request(broker_match: BrokerMatch, broker_request: BrokerRequest) -> BrokerPartyRole:
    """Return the request's side in a match."""
    if broker_request.id == broker_match.source_request_id:
        return "source"
    if broker_request.id == broker_match.candidate_request_id:
        return "candidate"
    raise ValueError("Request is not part of this broker match.")


def waiting_status_for(graph: BrokerGraphName, party_role: BrokerPartyRole) -> str:
    """Return the match status that means BrokerAI is waiting on this party."""
    phase = "screening" if graph == "matching" else "mediation"
    return f"waiting_{party_role}_{phase}"


def graph_status_for(graph: BrokerGraphName) -> str:
    """Return the neutral in-progress status for a graph."""
    return "screening" if graph == "matching" else "mediating"


def should_reopen_request(broker_request: BrokerRequest) -> bool:
    """Return whether a request should remain matchable after a match path ends."""
    return broker_request.status not in REQUEST_TERMINAL_STATUSES | REQUEST_HOLD_STATUSES


def set_active_workflow(
    broker_request: BrokerRequest,
    broker_match: BrokerMatch,
    graph: BrokerGraphName,
) -> None:
    """Route the request's next user reply to a graph for one active match."""
    broker_request.active_graph = graph
    broker_request.active_match_id = broker_match.id
    broker_request.status = graph


def clear_active_workflow(
    broker_request: BrokerRequest,
    *,
    next_status: str | None = None,
) -> None:
    """Clear graph routing for a request and optionally set its availability status."""
    broker_request.active_graph = None
    broker_request.active_match_id = None
    if next_status is not None:
        broker_request.status = next_status
    elif should_reopen_request(broker_request):
        broker_request.status = "ready_for_matching"


async def clear_match_workflows(
    db: AsyncSession,
    broker_match: BrokerMatch,
    *,
    next_status: str | None = None,
) -> None:
    """Clear active workflow pointers for both requests in a match."""
    for request_id in (broker_match.source_request_id, broker_match.candidate_request_id):
        broker_request = await db.get(BrokerRequest, request_id)
        if broker_request is None:
            continue
        if broker_request.active_match_id == broker_match.id:
            clear_active_workflow(broker_request, next_status=next_status)


async def get_active_workflow_match(
    db: AsyncSession,
    broker_request: BrokerRequest,
    graph: BrokerGraphName,
) -> BrokerMatch | None:
    """Load the active match only when the request is explicitly routed to this graph."""
    if broker_request.active_graph != graph or not broker_request.active_match_id:
        return None
    broker_match = await db.get(BrokerMatch, broker_request.active_match_id)
    if broker_match is None or broker_match.status in MATCH_TERMINAL_STATUSES:
        clear_active_workflow(broker_request)
        return None
    if broker_request.id not in {broker_match.source_request_id, broker_match.candidate_request_id}:
        clear_active_workflow(broker_request)
        return None
    return broker_match


async def find_open_match_for_request(
    db: AsyncSession,
    broker_request: BrokerRequest,
) -> BrokerMatch | None:
    """Return the most recent non-terminal match involving a request."""
    result = await db.execute(
        select(BrokerMatch)
        .where(
            (
                (BrokerMatch.source_request_id == broker_request.id)
                | (BrokerMatch.candidate_request_id == broker_request.id)
            ),
            BrokerMatch.status.in_(MATCH_ACTIVE_STATUSES),
        )
        .order_by(BrokerMatch.updated_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
