from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentMatch, AgentMessage, AgentRequest, AgentSession, UserProfile
from app.services.attachments import context_attachments, shared_attachment_ids_for_match
from app.services.living_request import living_request_from_model, redacted_living_request
from app.services.workflow import (
    MATCH_ACCEPTED,
    MATCH_CONNECTED,
    MATCH_OPEN,
    counterpart_request_id,
    list_matches_for_request,
    load_events,
    load_pair_requests,
    match_notebook,
    party_role,
)

Trigger = Literal["user_message", "request_ready", "match_timeout"]
SessionRole = Literal["source", "counterparty"]


@dataclass
class ToolContext:
    db: AsyncSession
    profile: UserProfile
    session: AgentSession
    request: AgentRequest | None
    user_message: AgentMessage | None
    trigger: Trigger
    trigger_match_id: str | None = None
    current_user_messages: list[AgentMessage] = field(default_factory=list)
    saved_this_turn: bool = False
    indexed_this_turn: bool = False
    searched_this_turn: bool = False
    opened_match_ids: list[str] = field(default_factory=list)
    new_attachment_ids: list[str] = field(default_factory=list)

    def track(self, message: AgentMessage) -> None:
        if message.session_id == self.session.id:
            self.current_user_messages.append(message)


def _event_snapshot(event) -> dict[str, Any]:
    return {
        "type": event.event_type,
        "payload": event.payload,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


async def resolve_session_role(ctx: ToolContext) -> SessionRole:
    if ctx.request is None:
        return "source"
    if ctx.request.waiting_match_id:
        match = await ctx.db.get(AgentMatch, ctx.request.waiting_match_id)
        if match is not None and ctx.request.id == match.candidate_request_id:
            return "counterparty"
    return "source"


async def build_context_packet(ctx: ToolContext) -> dict[str, Any]:
    role = await resolve_session_role(ctx)
    living = living_request_from_model(ctx.request)
    open_matches: list[dict[str, Any]] = []
    recent_events: list[dict[str, Any]] = []
    attention = "idle"

    if ctx.request is not None:
        matches = await list_matches_for_request(ctx.db, ctx.request.id, limit=8)
        for match in matches:
            snapshot = await _match_snapshot(ctx, match)
            if match.status == MATCH_OPEN:
                open_matches.append(snapshot)
            recent_events.extend(snapshot.get("last_events") or [])
        recent_events.sort(key=lambda item: item.get("created_at") or "")
        recent_events = recent_events[-12:]
        if ctx.request.waiting_match_id:
            attention = f"waiting on reply for match {ctx.request.waiting_match_id}"

    user_text = ctx.user_message.content if ctx.user_message else None
    attachments, new_uploads = await context_attachments(
        ctx.db,
        session_id=ctx.session.id,
        new_ids=ctx.new_attachment_ids,
    )
    return {
        "SESSION_ROLE": role,
        "TRIGGER": ctx.trigger,
        "living_request": living,
        "open_matches": open_matches,
        "recent_events": recent_events,
        "attention_pointer": attention,
        "current_user_message": user_text,
        "trigger_match_id": ctx.trigger_match_id,
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
    other_party = redacted_living_request(other)
    if identity_open:
        other_profile = await ctx.db.get(UserProfile, other.user_id)
        if other_profile is not None:
            other_party["contact"] = {
                "name": other_profile.name,
                "location": other_profile.location,
            }
    shared_ids = await shared_attachment_ids_for_match(ctx.db, match.id)
    your_attachments, _ = await context_attachments(ctx.db, session_id=ctx.session.id)
    other_attachments, _ = await context_attachments(ctx.db, session_id=other.session_id)
    shared_by_you = [item for item in your_attachments if item["id"] in shared_ids]
    shared_with_you = [
        {
            "id": item["id"],
            "kind": item["kind"],
            "label": item["label"],
            "purpose": item["purpose"],
            "filename": item["filename"],
            "content_type": item["content_type"],
        }
        for item in other_attachments
        if item["id"] in shared_ids
    ]
    return {
        "match_id": match.id,
        "status": match.status,
        "your_role": party_role(match, ctx.request),
        "your_brief": living_request_from_model(ctx.request),
        "other_brief": other_party,
        "other_party": other_party,
        "notebook": match_notebook(match),
        "shared_by_you": shared_by_you,
        "shared_with_you": shared_with_you,
        "last_events": [_event_snapshot(event) for event in events],
    }


async def load_session_history(
    db: AsyncSession,
    session_id: str,
    *,
    exclude_message_id: str | None = None,
    limit: int = 20,
) -> list[AgentMessage]:
    result = await db.execute(
        select(AgentMessage)
        .where(AgentMessage.session_id == session_id)
        .order_by(AgentMessage.created_at)
    )
    messages = [
        message
        for message in result.scalars().all()
        if message.id != exclude_message_id
    ]
    return messages[-limit:]
