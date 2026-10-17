from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.context import (
    ToolContext,
    build_context_packet,
    focused_match_id,
    load_session_history,
    reply_lane_id,
    resolve_session_role,
)
from app.agents.tools._common import adopt_focus_if_idle, resolve_match_id
from app.agents.tools.match_tools import MessagePartyArgs
from app.db.models import AgentMatch, AgentMessage, AgentRequest, AgentSession
from app.services.match_lanes import (
    MatchLaneError,
    _unread_counts,
    match_lane_label,
    match_lane_summary,
    require_request_match,
    roster_entry,
)
from app.services.workflow import MATCH_ACCEPTED, MATCH_OPEN


def _request(**kwargs) -> AgentRequest:
    values = {
        "id": "req-1",
        "session_id": "sess-1",
        "user_id": "user-1",
        "title": "1BHK in Baner",
        "summary": "Need a flat",
        "details": {"objective": "Rent a 1BHK", "domain": "housing", "location": "Baner"},
        "status": "open",
    }
    values.update(kwargs)
    return AgentRequest(**values)


def test_unread_counts_are_scoped_to_this_session() -> None:
    import inspect

    signature = inspect.signature(_unread_counts)
    source = inspect.getsource(_unread_counts)
    assert "session_id" in signature.parameters
    assert "AgentMessage.session_id == session_id" in source
    assert "AgentMessage.role == \"assistant\"" in source


def test_open_match_on_request_lane_adopts_focus_for_later_tools() -> None:
    ctx = SimpleNamespace(focus_match_id=None, trigger_match_id=None)
    adopt_focus_if_idle(ctx, "match-new")
    assert ctx.focus_match_id == "match-new"
    adopt_focus_if_idle(ctx, "match-other")
    assert ctx.focus_match_id == "match-new"


def test_reply_lane_stays_on_request_when_open_match_adopts_focus() -> None:
    ctx = ToolContext(
        db=AsyncMock(),
        profile=SimpleNamespace(id="u1"),
        session=AgentSession(id="s1", user_id="u1"),
        request=_request(),
        user_message=None,
        trigger="user_message",
        focus_match_id=None,
    )
    assert reply_lane_id(ctx) is None
    adopt_focus_if_idle(ctx, "match-new")
    assert ctx.focus_match_id == "match-new"
    assert reply_lane_id(ctx) is None


def test_match_id_defaults_off_the_focused_lane() -> None:
    args = MessagePartyArgs(context="Ask if the dates still work.")
    assert args.match_id is None
    ctx = SimpleNamespace(focus_match_id="match-b", trigger_match_id=None)
    assert resolve_match_id(ctx, args.match_id) == "match-b"
    assert resolve_match_id(ctx, "match-a") == "match-a"
    with pytest.raises(ValueError, match="No match is in focus"):
        resolve_match_id(SimpleNamespace(focus_match_id=None, trigger_match_id=None), None)


def test_focus_prefers_explicit_lane_over_waiting_pointer() -> None:
    ctx = ToolContext(
        db=AsyncMock(),
        profile=SimpleNamespace(id="u1"),
        session=AgentSession(id="s1", user_id="u1"),
        request=_request(waiting_match_id="match-old"),
        user_message=None,
        trigger="user_message",
        focus_match_id="match-new",
        trigger_match_id=None,
    )
    assert focused_match_id(ctx) == "match-new"


@pytest.mark.asyncio
async def test_session_role_follows_focused_match_not_waiting_pointer() -> None:
    match = AgentMatch(
        id="match-1",
        source_request_id="other",
        candidate_request_id="req-1",
        status=MATCH_OPEN,
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=match)
    ctx = ToolContext(
        db=db,
        profile=SimpleNamespace(id="u1"),
        session=AgentSession(id="s1", user_id="u1"),
        request=_request(id="req-1"),
        user_message=None,
        trigger="user_message",
        focus_match_id="match-1",
    )
    assert await resolve_session_role(ctx) == "counterparty"
    ctx.focus_match_id = None
    assert await resolve_session_role(ctx) == "source"


def test_lane_label_hides_identity_until_accept() -> None:
    other = _request(title="Designer in Pune", user_id="u2")
    profile = SimpleNamespace(name="Priya Sharma")
    assert match_lane_label(other=other, other_profile=profile, identity_open=False) == "Housing · Baner"
    assert match_lane_label(other=other, other_profile=profile, identity_open=True) == "Priya Sharma · Baner"
    unnamed = _request(title="New broker request", details={"domain": "housing", "location": "Aundh"})
    assert match_lane_label(other=unnamed, other_profile=None, identity_open=False) == "Housing · Aundh"


def test_lane_label_prefers_brief_over_first_message_title() -> None:
    other = _request(
        title="Electrician in Pimple Nilakh to install 2 ceiling fans and re-configure...",
        details={
            "objective": "Electrician in Pimple Nilakh to install 2 ceiling fans and re-configure the whole flat",
            "domain": "trades",
            "location": "Pimple Nilakh, Pune",
        },
    )
    assert match_lane_label(other=other, other_profile=None, identity_open=False) == "Trades · Pimple Nilakh"


def test_lane_label_uses_short_objective_when_domain_is_missing() -> None:
    other = _request(
        title="New broker request",
        details={
            "objective": "Need a girls-only PG near Headagyewar Hospital from next month.",
            "location": "Headagyewar",
        },
    )
    assert match_lane_label(other=other, other_profile=None, identity_open=False) == (
        "Need a girls-only PG… · Headagyewar"
    )


def test_lane_label_clips_long_title_fallback() -> None:
    other = _request(
        title="Find a girl looking for PG paying guest accommodation in Chatrapati Sambhaji Nagar",
        details={},
    )
    label = match_lane_label(other=other, other_profile=None, identity_open=False)
    assert label != other.title
    assert "…" in label
    assert len(label) <= 29


def test_lane_summary_is_redacted() -> None:
    other = _request(summary="Call me at 9876543210 about the flat")
    text = match_lane_summary(other)
    assert "9876543210" not in text


def test_roster_entry_omits_notebook_facts() -> None:
    compact = roster_entry(
        {
            "match_id": "m1",
            "status": MATCH_ACCEPTED,
            "your_role": "source",
            "other_brief": {
                "request_id": "r2",
                "objective": "Let a 1BHK",
                "domain": "housing",
                "location": "Baner",
                "budget": "20k",
            },
            "notebook": {
                "facts": [{"by": "source", "text": "secret term"}],
                "outstanding": {"waiting_on": "candidate", "question": "Dates?"},
                "next_action": "ask dates",
            },
        }
    )
    assert compact["match_id"] == "m1"
    assert "facts" not in compact
    assert compact["outstanding"]["waiting_on"] == "candidate"
    assert compact["other_brief"]["objective"] == "Let a 1BHK"


def test_messages_can_belong_to_a_match_lane() -> None:
    message = AgentMessage(
        session_id="s1",
        role="assistant",
        content="Are those dates still open?",
        match_id="match-1",
    )
    assert message.match_id == "match-1"
    request_lane = AgentMessage(session_id="s1", role="user", content="Need a 1BHK")
    assert request_lane.match_id is None


@pytest.mark.asyncio
async def test_require_request_match_none_is_the_request_lane() -> None:
    db = AsyncMock()
    assert await require_request_match(db, _request(), None) is None
    db.get.assert_not_called()


@pytest.mark.asyncio
async def test_require_request_match_needs_a_brief() -> None:
    db = AsyncMock()
    with pytest.raises(MatchLaneError, match="brief"):
        await require_request_match(db, None, "match-1")


@pytest.mark.asyncio
async def test_require_request_match_rejects_a_foreign_pair() -> None:
    db = AsyncMock()
    db.get = AsyncMock(
        return_value=AgentMatch(
            id="match-1",
            source_request_id="other",
            candidate_request_id="also-other",
            status=MATCH_OPEN,
        )
    )
    with pytest.raises(MatchLaneError, match="does not belong"):
        await require_request_match(db, _request(), "match-1")


@pytest.mark.asyncio
async def test_load_session_history_filters_request_lane() -> None:
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result)
    await load_session_history(db, "sess-1", match_id=None)
    compiled = str(db.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "match_id IS NULL" in compiled or "match_id is null" in compiled.lower()


@pytest.mark.asyncio
async def test_load_session_history_filters_a_match_lane() -> None:
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result)
    await load_session_history(db, "sess-1", match_id="match-1")
    compiled = str(db.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "match-1" in compiled
    assert "IS NULL" not in compiled


@pytest.mark.asyncio
async def test_context_packet_marks_request_vs_match_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_matches(*_args, **_kwargs):
        return []

    async def no_attachments(*_args, **_kwargs):
        return [], []

    async def two_open(*_args, **_kwargs):
        return 2

    async def no_suggestions(*_args, **_kwargs):
        return []

    monkeypatch.setattr("app.agents.context.list_matches_for_request", no_matches)
    monkeypatch.setattr("app.agents.context.context_attachments", no_attachments)
    monkeypatch.setattr("app.agents.context.open_match_count", two_open)
    monkeypatch.setattr("app.agents.context.list_suggestions", no_suggestions)

    ctx = ToolContext(
        db=AsyncMock(),
        profile=SimpleNamespace(id="u1"),
        session=AgentSession(id="s1", user_id="u1"),
        request=_request(),
        user_message=None,
        trigger="user_message",
        focus_match_id=None,
    )
    packet = await build_context_packet(ctx)
    assert packet["LANE"] == "request"
    assert packet["focus_match_id"] is None
    assert "other_matches" not in packet
    assert packet["open_matches"] == []
    assert packet["open_match_count"] == 2
    assert packet["suggested_matches"] == []
    assert packet["pending_questions"] == []
    assert packet["recent_events"] == []

    ctx.focus_match_id = "match-1"
    packet = await build_context_packet(ctx)
    assert packet["LANE"] == "match"
    assert packet["focus_match_id"] == "match-1"
