from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated, Literal

from langchain_core.tools import BaseTool
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from app.agents.context import OutreachJob, ToolContext
from app.agents.prompts import (
    TOOL_ACCEPT_MATCH,
    TOOL_GET_MATCH_EVENTS,
    TOOL_MESSAGE_PARTY,
    TOOL_OPEN_MATCH,
    TOOL_REJECT_MATCH,
    TOOL_SKIP_MATCH,
    TOOL_UPDATE_NOTEBOOK,
)
from app.agents.tool_call_repair import coerce_optional_str_list
from app.agents.tools._common import make_tool, owned_match
from app.core.config import settings
from app.db.models import AgentMatch, AgentMessage, AgentRequest
from app.services.contact import share_match_contacts
from app.services.living_request import redacted_living_request
from app.services.privacy import json_result, redact_identity
from app.services.workflow import (
    MATCH_ACCEPTED,
    MATCH_CLOSED,
    MATCH_CONNECTED,
    MATCH_OPEN,
    add_event,
    append_match_fact,
    clear_waiting,
    clear_waiting_for_match,
    empty_notebook,
    expiry_from_now,
    get_pair_match,
    load_events,
    match_notebook,
    open_match_count,
    party_has_accepted,
    party_role,
    should_reopen_closed_match,
    write_notebook,
)

logger = logging.getLogger(__name__)


class OpenMatchArgs(BaseModel):
    candidate_id: str = Field(
        min_length=8,
        max_length=36,
        description="The candidate brief to open a working match with.",
    )


class MessagePartyArgs(BaseModel):
    model_config = ConfigDict(extra="ignore")

    match_id: str = Field(
        description="The match whose other party should be reached.",
    )
    context: str = Field(
        min_length=1,
        max_length=1200,
        description=(
            "Why the other party should be reached and what they need to hear "
            "or answer. The later turn writes the finished wording."
        ),
    )


class UpdateNotebookArgs(BaseModel):
    match_id: str
    facts: Annotated[list[str] | None, BeforeValidator(coerce_optional_str_list)] = Field(
        default=None,
        description="Concrete terms this person actually stated.",
    )
    agent_note: str | None = Field(
        default=None,
        max_length=2000,
        description="Inference, unknowns, and why they matter for later turns.",
    )
    next_action: str | None = Field(
        default=None,
        max_length=800,
        description="Intended follow-through and which party it concerns.",
    )
    waiting_on: Literal["source", "candidate", "none"] | None = Field(
        default=None,
        description="Who, if anyone, still owes an answer.",
    )
    outstanding_question: str | None = Field(
        default=None,
        max_length=1200,
        description="The open question if someone is still being asked.",
    )


class MatchIdReasonArgs(BaseModel):
    match_id: str
    reason: str = Field(
        default="",
        max_length=400,
        description="Short note on why this match is being closed.",
    )


class AcceptMatchArgs(BaseModel):
    match_id: str = Field(description="The match this side is agreeing to.")


class GetMatchEventsArgs(BaseModel):
    match_id: str = Field(description="The match whose history and notebook to load.")


async def _deliver_side(
    ctx: ToolContext,
    match: AgentMatch,
    party_request: AgentRequest,
    text: str,
    *,
    to_current_user: bool,
    redact: bool,
) -> None:
    content = redact_identity(text) if redact else text
    message = AgentMessage(
        session_id=party_request.session_id,
        role="assistant",
        content=content,
    )
    ctx.db.add(message)
    await ctx.db.flush()
    party_request.waiting_match_id = match.id
    if to_current_user:
        ctx.track(message)
    await add_event(
        ctx.db,
        match_id=match.id,
        event_type="message_to_current" if to_current_user else "message_to_other",
        session_id=party_request.session_id,
        user_id=party_request.user_id,
        message_text=content,
        payload={"message_id": message.id},
    )


async def _close_match(
    ctx: ToolContext,
    match_id: str,
    reason_code: str,
    note: str,
) -> str:
    match, current, _other, _source = await owned_match(ctx, match_id)
    if match.status == MATCH_CLOSED:
        return json_result(ok=False, error="This match is already closed.")
    match.status = MATCH_CLOSED
    match.close_reason = reason_code
    match.last_activity_at = datetime.now(UTC)
    await clear_waiting_for_match(ctx.db, match)
    await add_event(
        ctx.db,
        match_id=match.id,
        event_type="match_closed",
        session_id=ctx.session.id,
        user_id=ctx.profile.id,
        payload={"reason": reason_code, "note": note},
    )
    clear_waiting(current, match.id)
    logger.info(
        "close_match session=%s match_id=%s reason=%s",
        ctx.session.id,
        match.id,
        reason_code,
    )
    return json_result(
        ok=True,
        match_id=match.id,
        status=match.status,
        close_reason=reason_code,
        outcome=f"Match closed ({reason_code}).",
    )


def build_match_tools(ctx: ToolContext) -> list[BaseTool]:
    async def open_match(args: OpenMatchArgs) -> str:
        if ctx.request is None:
            return json_result(ok=False, error="No brief is saved for this session.")
        if args.candidate_id == ctx.request.id:
            return json_result(ok=False, error="Cannot open a match against the same request.")
        candidate = await ctx.db.get(AgentRequest, args.candidate_id)
        if candidate is None:
            return json_result(ok=False, error="Candidate request not found.")
        if candidate.user_id == ctx.request.user_id:
            return json_result(ok=False, error="A user cannot be matched with their own request.")

        existing = await get_pair_match(ctx.db, ctx.request.id, candidate.id)
        reused = False
        if existing is not None:
            if existing.status in {MATCH_ACCEPTED, MATCH_CONNECTED}:
                return json_result(ok=False, error="This pair already completed.")
            if existing.status == MATCH_CLOSED and not should_reopen_closed_match(
                existing, ctx.request, candidate
            ):
                return json_result(
                    ok=False,
                    error="This pair was closed and is not eligible to reopen yet.",
                )
            match = existing
            reused = existing.status == MATCH_OPEN
        else:
            if await open_match_count(ctx.db, ctx.request.id) >= settings.MAX_OPEN_MATCHES_PER_REQUEST:
                return json_result(
                    ok=False,
                    error="Open-match limit reached.",
                )
            match = AgentMatch(
                source_request_id=ctx.request.id,
                candidate_request_id=candidate.id,
            )
            ctx.db.add(match)
            await ctx.db.flush()

        match.status = MATCH_OPEN
        match.close_reason = None
        match.last_activity_at = datetime.now(UTC)
        match.expires_at = expiry_from_now()
        if not getattr(match, "notebook", None):
            write_notebook(match, empty_notebook())
        if not reused:
            await add_event(
                ctx.db,
                match_id=match.id,
                event_type="match_opened",
                session_id=ctx.session.id,
                user_id=ctx.profile.id,
                payload={"candidate_id": candidate.id},
            )
            ctx.opened_match_ids.append(match.id)
        logger.info(
            "open_match session=%s match_id=%s candidate_id=%s reused=%s",
            ctx.session.id,
            match.id,
            candidate.id,
            reused,
        )
        return json_result(
            ok=True,
            match_id=match.id,
            candidate_id=candidate.id,
            reused=reused,
            other_party=redacted_living_request(candidate),
            outcome="Match opened. No message sent.",
        )

    async def message_party(args: MessagePartyArgs) -> str:
        if ctx.trigger == "match_context":
            return json_result(
                ok=False,
                error="This turn is already the other party's chat. Reply here. Do not contact them again now.",
            )
        match, current, other, _source = await owned_match(ctx, args.match_id)
        if match.status not in {MATCH_OPEN, MATCH_ACCEPTED}:
            return json_result(ok=False, error="This match is not open for messaging.")
        target = other
        to = party_role(match, target)
        if target.id == current.id:
            return json_result(
                ok=False,
                error="The other party could not be resolved. This person's text is the final reply.",
            )
        context = args.context.strip()
        job = OutreachJob(
            match_id=match.id,
            to=to,
            context=context,
            from_session_id=ctx.session.id,
        )
        if any(
            item.match_id == job.match_id and item.to == job.to for item in ctx.queued_outreach
        ):
            return json_result(ok=True, match_id=match.id, to=to, queued=True, duplicate=True)
        ctx.queued_outreach.append(job)
        target.waiting_match_id = match.id
        match.last_activity_at = datetime.now(UTC)
        match.expires_at = expiry_from_now()
        await add_event(
            ctx.db,
            match_id=match.id,
            event_type="outreach_queued",
            session_id=ctx.session.id,
            user_id=ctx.profile.id,
            payload={"to": to, "to_session_id": target.session_id},
        )
        logger.info(
            "message_party queued session=%s match_id=%s to=%s to_session=%s",
            ctx.session.id,
            match.id,
            to,
            target.session_id,
        )
        return json_result(
            ok=True,
            match_id=match.id,
            to=to,
            queued=True,
            outcome="Contacting them separately. This chat still needs your final reply.",
        )

    async def update_notebook(args: UpdateNotebookArgs) -> str:
        match, current, _other, _source = await owned_match(ctx, args.match_id)
        facts = [item.strip() for item in (args.facts or []) if item.strip()]
        agent_note = (args.agent_note or "").strip() or None
        next_action = (args.next_action or "").strip() or None
        outstanding_question = (args.outstanding_question or "").strip() or None
        if not facts and not agent_note and not next_action and args.waiting_on is None and not outstanding_question:
            return json_result(ok=False, error="Pass facts, agent_note, next_action, or waiting_on.")
        role = party_role(match, current)
        for fact in facts:
            append_match_fact(match, by=role, text=fact)
        notebook = match_notebook(match)
        if agent_note is not None:
            notebook["agent_note"] = agent_note
        if next_action is not None:
            notebook["next_action"] = next_action
        if args.waiting_on == "none":
            notebook["outstanding"] = None
        elif args.waiting_on in {"source", "candidate"}:
            question = outstanding_question or (notebook.get("outstanding") or {}).get("question") or ""
            notebook["outstanding"] = {"waiting_on": args.waiting_on, "question": question}
        elif outstanding_question:
            waiting = (notebook.get("outstanding") or {}).get("waiting_on")
            notebook["outstanding"] = {"waiting_on": waiting, "question": outstanding_question}
        write_notebook(match, notebook)
        notebook = match_notebook(match)
        await add_event(
            ctx.db,
            match_id=match.id,
            event_type="notebook_updated",
            session_id=ctx.session.id,
            user_id=ctx.profile.id,
            payload={
                "by": role,
                "facts": len(facts),
                "has_agent_note": bool(agent_note),
                "has_next_action": bool(next_action),
                "waiting_on": (notebook.get("outstanding") or {}).get("waiting_on"),
            },
        )
        outstanding = notebook.get("outstanding") or {}
        waiting_on = outstanding.get("waiting_on")
        outcome = "Notebook updated."
        if waiting_on:
            outcome = f"Notebook updated. waiting_on={waiting_on}."
        logger.info(
            "update_notebook session=%s match_id=%s facts=%s waiting_on=%s",
            ctx.session.id,
            match.id,
            len(facts),
            waiting_on,
        )
        return json_result(ok=True, notebook=notebook, outcome=outcome)

    async def skip_match(args: MatchIdReasonArgs) -> str:
        return await _close_match(ctx, args.match_id, "skip", args.reason)

    async def reject_match(args: MatchIdReasonArgs) -> str:
        return await _close_match(ctx, args.match_id, "reject", args.reason)

    async def accept_match(args: AcceptMatchArgs) -> str:
        match, current, other, _source = await owned_match(ctx, args.match_id)
        if match.status == MATCH_CONNECTED:
            return json_result(
                ok=True,
                match_id=match.id,
                status=match.status,
                already_connected=True,
                outcome="Already connected.",
            )
        if match.status == MATCH_CLOSED:
            return json_result(ok=False, error="A closed match cannot be accepted.")

        if not await party_has_accepted(ctx.db, match.id, current.user_id):
            await add_event(
                ctx.db,
                match_id=match.id,
                event_type="party_accepted",
                session_id=ctx.session.id,
                user_id=current.user_id,
            )

        other_accepted = await party_has_accepted(ctx.db, match.id, other.user_id)
        if not other_accepted:
            match.last_activity_at = datetime.now(UTC)
            match.expires_at = expiry_from_now()
            return json_result(
                ok=False,
                error="The other side has not agreed to the same terms yet.",
                accepted_by_you=True,
                match_complete=False,
                outcome="Your acceptance recorded. Other side has not accepted.",
            )

        match.status = MATCH_ACCEPTED
        match.last_activity_at = datetime.now(UTC)
        await clear_waiting_for_match(ctx.db, match)
        cards = await share_match_contacts(ctx.db, match)
        for message in cards:
            ctx.track(message)
        return json_result(
            ok=True,
            match_id=match.id,
            match_complete=True,
            contact_cards=len(cards),
            outcome=f"Both sides accepted. Contact cards delivered: {len(cards)}.",
        )

    async def get_match_events(args: GetMatchEventsArgs) -> str:
        match, _current, other, _source = await owned_match(ctx, args.match_id)
        events = await load_events(ctx.db, match.id, limit=40)
        return json_result(
            ok=True,
            match_id=match.id,
            status=match.status,
            other_party=redacted_living_request(other),
            notebook=match_notebook(match),
            events=[
                {
                    "type": event.event_type,
                    "payload": event.payload,
                    "created_at": event.created_at.isoformat() if event.created_at else None,
                }
                for event in events
            ],
            outcome=f"Loaded {len(events)} event(s). Status {match.status}.",
        )

    return [
        make_tool(name="open_match", description=TOOL_OPEN_MATCH, args_model=OpenMatchArgs, handler=open_match),
        make_tool(
            name="message_party",
            description=TOOL_MESSAGE_PARTY,
            args_model=MessagePartyArgs,
            handler=message_party,
        ),
        make_tool(
            name="update_notebook",
            description=TOOL_UPDATE_NOTEBOOK,
            args_model=UpdateNotebookArgs,
            handler=update_notebook,
        ),
        make_tool(name="skip_match", description=TOOL_SKIP_MATCH, args_model=MatchIdReasonArgs, handler=skip_match),
        make_tool(
            name="reject_match",
            description=TOOL_REJECT_MATCH,
            args_model=MatchIdReasonArgs,
            handler=reject_match,
        ),
        make_tool(
            name="accept_match",
            description=TOOL_ACCEPT_MATCH,
            args_model=AcceptMatchArgs,
            handler=accept_match,
        ),
        make_tool(
            name="get_match_events",
            description=TOOL_GET_MATCH_EVENTS,
            args_model=GetMatchEventsArgs,
            handler=get_match_events,
        ),
    ]
