from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentMatch, AgentMessage, AgentRequest, AgentSession, UserProfile
from app.services.attachments import (
    context_attachments,
    counterpart_file_inventory,
    shared_attachment_ids_for_match,
)
from app.services.living_request import (
    counterpart_brief_stub,
    living_request_from_model,
    redacted_living_request,
)
from app.services.suggestions import all_pending_questions, list_suggestions, packet_snapshot
from app.services.workflow import (
    MATCH_ACCEPTED,
    MATCH_CONNECTED,
    counterpart_request_id,
    list_matches_for_request,
    load_events,
    load_pair_requests,
    match_notebook,
    open_match_count,
    party_role,
)

Trigger = Literal["user_message", "request_ready", "match_timeout", "match_context"]
SessionRole = Literal["source", "counterparty"]
PartyTo = Literal["source", "candidate"]


@dataclass
class OutreachJob:
    """A broker turn to run later on the other party's session."""

    match_id: str | None
    to: PartyTo | None
    context: str
    from_session_id: str
    to_request_id: str | None = None


MailKind = Literal["broker_outreach", "intro_offered", "contacts_delivered"]


@dataclass
class MailJob:
    """Transactional mail to send after the current request commits."""

    kind: MailKind
    user_id: str
    session_id: str
    source_id: str
    title: str | None = None
    preview: str | None = None
    offer_prompt: str | None = None
    peer_name: str | None = None


@dataclass
class ToolContext:
    db: AsyncSession
    profile: UserProfile
    session: AgentSession
    request: AgentRequest | None
    user_message: AgentMessage | None
    trigger: Trigger
    trigger_match_id: str | None = None
    focus_match_id: str | None = None
    reply_match_id: str | None = field(init=False, default=None)
    outreach_context: str | None = None
    current_user_messages: list[AgentMessage] = field(default_factory=list)
    saved_this_turn: bool = False
    indexed_this_turn: bool = False
    searched_this_turn: bool = False
    opened_match_ids: list[str] = field(default_factory=list)
    new_attachment_ids: list[str] = field(default_factory=list)
    queued_outreach: list[OutreachJob] = field(default_factory=list)
    queued_mail: list[MailJob] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Human-visible replies on this turn stay on the lane the user sent from.
        # open_match may adopt focus_match_id for later tools in the same turn.
        self.reply_match_id = self.focus_match_id

    def track(self, message: AgentMessage) -> None:
        if message.session_id == self.session.id:
            self.current_user_messages.append(message)


def _event_snapshot(event) -> dict[str, Any]:
    return {
        "type": event.event_type,
        "payload": event.payload,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def focused_match_id(ctx: ToolContext) -> str | None:
    return ctx.focus_match_id or ctx.trigger_match_id


def reply_lane_id(ctx: ToolContext) -> str | None:
    return ctx.reply_match_id


async def resolve_session_role(ctx: ToolContext) -> SessionRole:
    if ctx.request is None:
        return "source"
    match_id = focused_match_id(ctx)
    if not match_id:
        return "source"
    match = await ctx.db.get(AgentMatch, match_id)
    if match is not None and ctx.request.id == match.candidate_request_id:
        return "counterparty"
    return "source"


async def build_context_packet(ctx: ToolContext) -> dict[str, Any]:
    role = await resolve_session_role(ctx)
    living = living_request_from_model(ctx.request)
    open_matches: list[dict[str, Any]] = []
    recent_events: list[dict[str, Any]] = []
    attention = "idle"
    focus_id = focused_match_id(ctx)
    lane = "match" if focus_id else "request"

    if ctx.request is not None and focus_id:
        matches = await list_matches_for_request(ctx.db, ctx.request.id, limit=20)
        for match in matches:
            if match.id != focus_id:
                continue
            snapshot = await _match_snapshot(ctx, match)
            open_matches.append(snapshot)
            recent_events.extend(snapshot.get("last_events") or [])
        recent_events.sort(key=lambda item: item.get("created_at") or "")
        recent_events = recent_events[-12:]
        attention = f"focused on match {focus_id}"

    user_text = ctx.user_message.content if ctx.user_message else None
    attachments, new_uploads = await context_attachments(
        ctx.db,
        session_id=ctx.session.id,
        new_ids=ctx.new_attachment_ids,
    )
    suggested: list[dict[str, Any]] = []
    pending_questions: list[str] = []
    if ctx.request is not None and not focus_id:
        suggestion_rows = await list_suggestions(ctx.db, ctx.request.id)
        suggested = [packet_snapshot(row) for row in suggestion_rows]
        pending_questions = all_pending_questions(suggestion_rows)
    live_open_count = 0
    if ctx.request is not None:
        live_open_count = await open_match_count(ctx.db, ctx.request.id)
    return {
        "SESSION_ROLE": role,
        "TRIGGER": ctx.trigger,
        "LANE": lane,
        "focus_match_id": focus_id,
        "living_request": living,
        "open_matches": open_matches,
        "open_match_count": live_open_count,
        "suggested_matches": suggested,
        "pending_questions": pending_questions,
        "recent_events": recent_events,
        "attention_pointer": attention,
        "current_user_message": user_text,
        "trigger_match_id": ctx.trigger_match_id,
        "outreach_context": ctx.outreach_context,
        "attachments": attachments,
        "new_uploads": new_uploads,
    }


async def _match_snapshot(ctx: ToolContext, match: AgentMatch) -> dict[str, Any]:
    source, candidate = await load_pair_requests(ctx.db, match)
    if source is None or candidate is None or ctx.request is None:
        return {"match_id": match.id, "status": match.status, "unavailable": True}

    other_id = counterpart_request_id(match, ctx.request)
    other = candidate if other_id == candidate.id else source
    events = await load_events(ctx.db, match.id, limit=8)
    identity_open = match.status in {MATCH_ACCEPTED, MATCH_CONNECTED}
    your_brief = living_request_from_model(ctx.request)
    if identity_open:
        other_brief = redacted_living_request(other)
        other_profile = await ctx.db.get(UserProfile, other.user_id)
        if other_profile is not None:
            contact: dict[str, Any] = {"name": other_profile.name}
            if other_profile.gender:
                contact["gender"] = other_profile.gender
            if other_profile.date_of_birth:
                contact["date_of_birth"] = other_profile.date_of_birth.isoformat()
            other_brief["contact"] = contact
    else:
        other_brief = counterpart_brief_stub(other.id)
    shared_ids = await shared_attachment_ids_for_match(ctx.db, match.id)
    your_attachments, _ = await context_attachments(ctx.db, session_id=ctx.session.id)
    other_attachments, _ = await context_attachments(ctx.db, session_id=other.session_id)
    shared_by_you = [
        {**item, "owner": "this_person"}
        for item in your_attachments
        if item["id"] in shared_ids
    ]
    shared_with_you = [
        {
            "id": item["id"],
            "kind": item["kind"],
            "label": item["label"],
            "purpose": item["purpose"],
            "content_type": item["content_type"],
            "owner": "counterpart",
        }
        for item in other_attachments
        if item["id"] in shared_ids
    ]
    return {
        "match_id": match.id,
        "status": match.status,
        "your_role": party_role(match, ctx.request),
        "your_brief": your_brief,
        "other_brief": other_brief,
        "notebook": match_notebook(match),
        "other_files": counterpart_file_inventory(other_attachments, shared_ids),
        "shared_by_you": shared_by_you,
        "shared_with_you": shared_with_you,
        "last_events": [_event_snapshot(event) for event in events],
    }


async def load_session_history(
    db: AsyncSession,
    session_id: str,
    *,
    exclude_message_id: str | None = None,
    match_id: str | None = None,
    limit: int = 20,
) -> list[AgentMessage]:
    stmt = select(AgentMessage).where(AgentMessage.session_id == session_id)
    if match_id:
        stmt = stmt.where(AgentMessage.match_id == match_id)
    else:
        stmt = stmt.where(AgentMessage.match_id.is_(None))
    stmt = stmt.order_by(
        AgentMessage.created_at,
        AgentMessage.role.desc(),
        AgentMessage.id,
    )
    result = await db.execute(stmt)
    messages = [
        message
        for message in result.scalars().all()
        if message.id != exclude_message_id
    ]
    return messages[-limit:]
