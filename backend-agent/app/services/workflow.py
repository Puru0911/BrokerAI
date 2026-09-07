from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.db.models import AgentEvent, AgentMatch, AgentRequest

PartyRole = Literal["source", "candidate"]

REQUEST_OPEN = "open"
REQUEST_PAUSED = "paused"
REQUEST_CLOSED = "closed"

MATCH_OPEN = "open"
MATCH_ACCEPTED = "accepted"
MATCH_CONNECTED = "connected"
MATCH_CLOSED = "closed"

CLOSE_SKIP = "skip"
CLOSE_REJECT = "reject"
CLOSE_WITHDRAW = "withdraw"
CLOSE_EXPIRED = "expired"
CLOSE_REQUEST_CLOSED = "request_closed"

REOPENABLE_REASONS = {CLOSE_SKIP, CLOSE_EXPIRED}


def party_role(match: AgentMatch, request: AgentRequest) -> PartyRole:
    if request.id == match.source_request_id:
        return "source"
    if request.id == match.candidate_request_id:
        return "candidate"
    raise ValueError("Request is not part of this match.")


def counterpart_request_id(match: AgentMatch, request: AgentRequest) -> str:
    role = party_role(match, request)
    if role == "source":
        return match.candidate_request_id
    return match.source_request_id


def expiry_from_now() -> datetime:
    return datetime.now(UTC) + timedelta(hours=settings.MATCH_TIMEOUT_HOURS)


def empty_notebook() -> dict[str, Any]:
    return {"facts": [], "outstanding": None, "agent_note": None, "next_action": None}


def _optional_note(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def match_notebook(match: AgentMatch) -> dict[str, Any]:
    """Shared match memory both parties' later turns should see.

    Humans never see this. It is only fed back into the broker context packet.
    """
    raw = match.notebook if isinstance(getattr(match, "notebook", None), dict) else {}
    facts: list[dict[str, Any]] = []
    for item in raw.get("facts") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        facts.append(
            {
                "by": str(item.get("by") or "").strip(),
                "text": text,
                "in_reply_to": str(item.get("in_reply_to") or "").strip() or None,
            }
        )
    outstanding = raw.get("outstanding")
    cleaned_outstanding: dict[str, Any] | None = None
    if isinstance(outstanding, dict):
        waiting_on = str(outstanding.get("waiting_on") or "").strip() or None
        question = str(outstanding.get("question") or "").strip()
        if waiting_on or question:
            cleaned_outstanding = {"waiting_on": waiting_on, "question": question}
    return {
        "facts": facts,
        "outstanding": cleaned_outstanding,
        "agent_note": _optional_note(raw.get("agent_note")),
        "next_action": _optional_note(raw.get("next_action")),
    }


def write_notebook(match: AgentMatch, notebook: dict[str, Any]) -> None:
    match.notebook = {
        "facts": list(notebook.get("facts") or []),
        "outstanding": notebook.get("outstanding"),
        "agent_note": _optional_note(notebook.get("agent_note")),
        "next_action": _optional_note(notebook.get("next_action")),
    }
    flag_modified(match, "notebook")


def append_match_fact(
    match: AgentMatch,
    *,
    by: str,
    text: str,
    in_reply_to: str | None = None,
) -> dict[str, Any]:
    notebook = match_notebook(match)
    fact = {
        "by": by,
        "text": text.strip(),
        "in_reply_to": (in_reply_to or "").strip() or None,
    }
    if fact["text"] and not any(
        item.get("by") == fact["by"] and item.get("text") == fact["text"]
        for item in notebook["facts"]
    ):
        notebook["facts"].append(fact)
    write_notebook(match, notebook)
    return notebook


def set_outstanding_question(
    match: AgentMatch,
    *,
    waiting_on: str,
    question: str,
) -> dict[str, Any]:
    notebook = match_notebook(match)
    notebook["outstanding"] = {
        "waiting_on": waiting_on,
        "question": question.strip(),
    }
    write_notebook(match, notebook)
    return notebook


def clear_outstanding(match: AgentMatch) -> dict[str, Any]:
    notebook = match_notebook(match)
    notebook["outstanding"] = None
    write_notebook(match, notebook)
    return notebook


def request_for_role(match: AgentMatch, source: AgentRequest, candidate: AgentRequest, role: PartyRole) -> AgentRequest:
    if role == "source":
        return source
    if role == "candidate":
        return candidate
    raise ValueError("Party must be source or candidate.")


def clear_waiting(request: AgentRequest, match_id: str | None = None) -> None:
    if match_id is None or request.waiting_match_id == match_id:
        request.waiting_match_id = None


async def clear_waiting_for_match(db: AsyncSession, match: AgentMatch) -> None:
    for request_id in (match.source_request_id, match.candidate_request_id):
        request = await db.get(AgentRequest, request_id)
        if request is None:
            continue
        clear_waiting(request, match.id)


async def load_pair_requests(
    db: AsyncSession,
    match: AgentMatch,
) -> tuple[AgentRequest | None, AgentRequest | None]:
    source = await db.get(AgentRequest, match.source_request_id)
    candidate = await db.get(AgentRequest, match.candidate_request_id)
    return source, candidate


async def get_session_request(db: AsyncSession, session_id: str) -> AgentRequest | None:
    result = await db.execute(select(AgentRequest).where(AgentRequest.session_id == session_id))
    return result.scalar_one_or_none()


async def get_pair_match(
    db: AsyncSession,
    source_request_id: str,
    candidate_request_id: str,
) -> AgentMatch | None:
    result = await db.execute(
        select(AgentMatch).where(
            AgentMatch.source_request_id == source_request_id,
            AgentMatch.candidate_request_id == candidate_request_id,
        )
    )
    return result.scalar_one_or_none()


async def open_match_count(db: AsyncSession, request_id: str) -> int:
    result = await db.execute(
        select(AgentMatch).where(
            or_(
                AgentMatch.source_request_id == request_id,
                AgentMatch.candidate_request_id == request_id,
            ),
            AgentMatch.status == MATCH_OPEN,
        )
    )
    return len(list(result.scalars().all()))


async def list_matches_for_request(
    db: AsyncSession,
    request_id: str,
    *,
    statuses: set[str] | None = None,
    limit: int = 8,
) -> list[AgentMatch]:
    stmt = select(AgentMatch).where(
        or_(
            AgentMatch.source_request_id == request_id,
            AgentMatch.candidate_request_id == request_id,
        )
    )
    if statuses:
        stmt = stmt.where(AgentMatch.status.in_(statuses))
    stmt = stmt.order_by(AgentMatch.updated_at.desc()).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def load_events(
    db: AsyncSession,
    match_id: str,
    *,
    limit: int = 30,
) -> list[AgentEvent]:
    result = await db.execute(
        select(AgentEvent)
        .where(AgentEvent.match_id == match_id)
        .order_by(AgentEvent.created_at.desc())
        .limit(limit)
    )
    events = list(result.scalars().all())
    events.reverse()
    return events


async def add_event(
    db: AsyncSession,
    *,
    match_id: str,
    event_type: str,
    session_id: str | None = None,
    user_id: str | None = None,
    message_text: str | None = None,
    payload: dict | None = None,
) -> AgentEvent:
    event = AgentEvent(
        match_id=match_id,
        session_id=session_id,
        user_id=user_id,
        event_type=event_type,
        message_text=message_text,
        payload=payload,
    )
    db.add(event)
    await db.flush()
    return event


async def close_open_matches_for_request(
    db: AsyncSession,
    request: AgentRequest,
    reason: str,
) -> None:
    matches = await list_matches_for_request(
        db,
        request.id,
        statuses={MATCH_OPEN},
        limit=50,
    )
    for match in matches:
        match.status = MATCH_CLOSED
        match.close_reason = reason
        await clear_waiting_for_match(db, match)
        await add_event(
            db,
            match_id=match.id,
            event_type="match_closed",
            session_id=request.session_id,
            user_id=request.user_id,
            payload={"reason": reason},
        )


def should_reopen_closed_match(
    match: AgentMatch,
    source: AgentRequest,
    candidate: AgentRequest,
) -> bool:
    if match.status != MATCH_CLOSED:
        return False
    if match.close_reason not in REOPENABLE_REASONS:
        return False
    if match.updated_at is None:
        return True
    updates = [value for value in (source.updated_at, candidate.updated_at) if value is not None]
    return any(value > match.updated_at for value in updates)


async def party_has_accepted(db: AsyncSession, match_id: str, user_id: str) -> bool:
    result = await db.execute(
        select(AgentEvent).where(
            AgentEvent.match_id == match_id,
            AgentEvent.user_id == user_id,
            AgentEvent.event_type == "party_accepted",
        )
    )
    return result.scalar_one_or_none() is not None
