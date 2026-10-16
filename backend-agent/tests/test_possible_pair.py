from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.context import OutreachJob, ToolContext, focused_match_id
from app.agents.tools.match_tools import (
    MessagePartyArgs,
    _queue_possible_pair_question,
    build_match_tools,
)
from app.core.config import settings
from app.db.models import AgentRequest
from app.services.possible_pair import (
    clear_possible_pair,
    possible_pair,
    possible_pair_entry,
    set_possible_pair,
)


def test_possible_pair_round_trip() -> None:
    entry = possible_pair_entry(
        other_request_id="req-b",
        question="Confirm they can relocate",
        waiting_on_request_id="req-b",
        asked_by_request_id="req-a",
        verdict="possible_match",
    )
    details = set_possible_pair({}, entry)
    loaded = possible_pair(details)
    assert loaded is not None
    assert loaded["other_request_id"] == "req-b"
    assert possible_pair(clear_possible_pair(details)) is None


@pytest.mark.asyncio
async def test_possible_pair_question_stores_one_pair_on_both_requests() -> None:
    source = AgentRequest(
        id="req-a",
        session_id="sess-a",
        user_id="user-a",
        title="Need a match",
        summary="Looking",
        details={},
        status="open",
    )
    other = AgentRequest(
        id="req-b",
        session_id="sess-b",
        user_id="user-b",
        title="Other",
        summary="Other",
        details={},
        status="open",
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=other)
    ctx = ToolContext(
        db=db,
        profile=MagicMock(),
        session=MagicMock(id="sess-a"),
        request=source,
        user_message=None,
        trigger="user_message",
    )
    result = await _queue_possible_pair_question(ctx, "req-b", "Ask if they can relocate.")
    assert '"possible_pair": true' in result
    assert possible_pair(source.details)["other_request_id"] == "req-b"
    assert possible_pair(other.details)["other_request_id"] == "req-a"
    assert possible_pair(source.details)["waiting_on_request_id"] == "req-b"
    assert len(ctx.queued_outreach) == 1
    job = ctx.queued_outreach[0]
    assert isinstance(job, OutreachJob)
    assert job.match_id is None
    assert job.to_request_id == "req-b"


def test_message_party_accepts_candidate_id() -> None:
    args = MessagePartyArgs(candidate_id="12345678-1234-1234-1234-1234567890ab", context="Ask community.")
    assert args.candidate_id is not None
    assert "to" not in MessagePartyArgs.model_fields


def test_open_match_cap_stays_three() -> None:
    assert settings.MAX_OPEN_MATCHES_PER_REQUEST == 3


def _request(request_id: str, user_id: str, details: dict | None = None) -> AgentRequest:
    return AgentRequest(
        id=request_id,
        session_id=f"sess-{request_id}",
        user_id=user_id,
        title="Need a match",
        summary="Looking",
        details=details or {},
        status="open",
    )


def _ctx(source: AgentRequest, other: AgentRequest, *, trigger: str = "user_message") -> ToolContext:
    db = AsyncMock()

    async def get(_model, ident):
        return other if ident == other.id else None

    db.get = AsyncMock(side_effect=get)
    return ToolContext(
        db=db,
        profile=MagicMock(),
        session=MagicMock(id=source.session_id),
        request=source,
        user_message=None,
        trigger=trigger,
    )


@pytest.mark.asyncio
async def test_possible_pair_overwrites_this_side_only() -> None:
    source = _request("req-a", "user-a")
    first = _request(
        "req-b",
        "user-b",
        set_possible_pair(
            {},
            possible_pair_entry(
                other_request_id="req-a",
                question="old",
                waiting_on_request_id="req-b",
                asked_by_request_id="req-a",
            ),
        ),
    )
    second = _request("req-c", "user-c")
    source.details = set_possible_pair(
        {},
        possible_pair_entry(
            other_request_id="req-b",
            question="old",
            waiting_on_request_id="req-b",
            asked_by_request_id="req-a",
        ),
    )
    db = AsyncMock()

    async def get(_model, ident):
        return {"req-b": first, "req-c": second}[ident]

    db.get = AsyncMock(side_effect=get)
    ctx = ToolContext(
        db=db,
        profile=MagicMock(),
        session=MagicMock(id="sess-a"),
        request=source,
        user_message=None,
        trigger="user_message",
    )
    result = await _queue_possible_pair_question(ctx, "req-c", "Ask budget.")
    assert '"possible_pair": true' in result
    assert possible_pair(source.details)["other_request_id"] == "req-c"
    assert possible_pair(first.details) is None
    assert possible_pair(second.details)["other_request_id"] == "req-a"


@pytest.mark.asyncio
async def test_possible_pair_rejects_when_other_is_waiting_on_a_third() -> None:
    source = _request("req-a", "user-a")
    other = _request(
        "req-b",
        "user-b",
        set_possible_pair(
            {},
            possible_pair_entry(
                other_request_id="req-z",
                question="elsewhere",
                waiting_on_request_id="req-b",
                asked_by_request_id="req-z",
            ),
        ),
    )
    ctx = _ctx(source, other)
    result = await _queue_possible_pair_question(ctx, "req-b", "Ask budget.")
    assert '"ok": false' in result
    assert possible_pair(source.details) is None


@pytest.mark.asyncio
async def test_answer_without_open_notifies_original_and_drops_pair() -> None:
    source = _request(
        "req-b",
        "user-b",
        set_possible_pair(
            {},
            possible_pair_entry(
                other_request_id="req-a",
                question="Community?",
                waiting_on_request_id="req-b",
                asked_by_request_id="req-a",
            ),
        ),
    )
    original = _request(
        "req-a",
        "user-a",
        set_possible_pair(
            {},
            possible_pair_entry(
                other_request_id="req-b",
                question="Community?",
                waiting_on_request_id="req-b",
                asked_by_request_id="req-a",
            ),
        ),
    )
    ctx = _ctx(source, original)
    result = await _queue_possible_pair_question(ctx, "req-a", "They cannot relocate.")
    assert '"possible_pair": false' in result
    assert possible_pair(source.details) is None
    assert possible_pair(original.details) is None
    assert ctx.queued_outreach[0].match_id is None
    assert ctx.queued_outreach[0].to_request_id == "req-a"


@pytest.mark.asyncio
async def test_open_match_refused_on_possible_pair_outreach() -> None:
    source = _request("req-b", "user-b")
    ctx = ToolContext(
        db=AsyncMock(),
        profile=MagicMock(),
        session=MagicMock(id="sess-b"),
        request=source,
        user_message=None,
        trigger="match_context",
        focus_match_id=None,
    )
    tool = next(item for item in build_match_tools(ctx) if item.name == "open_match")
    result = await tool.ainvoke({"candidate_id": "12345678-1234-1234-1234-1234567890ab"})
    assert "Do not open a match yet" in result


@pytest.mark.asyncio
async def test_possible_pair_still_queues_when_both_sides_are_at_the_open_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _request("req-aaaaaa", "user-a")
    other = _request("req-bbbbbb", "user-b")
    ctx = _ctx(source, other)
    count = AsyncMock(return_value=3)
    monkeypatch.setattr("app.agents.tools.match_tools.open_match_count", count)
    result = await _queue_possible_pair_question(ctx, "req-bbbbbb", "Ask community.")
    assert '"possible_pair": true' in result
    assert ctx.queued_outreach[0].match_id is None
    assert ctx.queued_outreach[0].to_request_id == "req-bbbbbb"
    count.assert_not_called()


@pytest.mark.asyncio
async def test_message_party_on_request_lane_asks_on_their_request_lane() -> None:
    source = _request("req-aaaaaa", "user-a")
    other = _request("req-bbbbbb", "user-b")
    ctx = _ctx(source, other)
    assert focused_match_id(ctx) is None
    tool = next(item for item in build_match_tools(ctx) if item.name == "message_party")
    result = await tool.ainvoke(
        {"candidate_id": "req-bbbbbb", "context": "Ask if they can relocate."}
    )
    assert '"possible_pair": true' in result
    assert ctx.queued_outreach[0].match_id is None
    assert ctx.queued_outreach[0].to_request_id == "req-bbbbbb"


@pytest.mark.asyncio
async def test_open_match_still_blocked_at_cap_three_after_a_possible_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _request("req-aaaaaa", "user-a")
    other = _request("req-bbbbbb", "user-b")
    ctx = _ctx(source, other)
    monkeypatch.setattr(
        "app.agents.tools.match_tools.open_match_count", AsyncMock(return_value=3)
    )
    monkeypatch.setattr(
        "app.agents.tools.match_tools.get_pair_match", AsyncMock(return_value=None)
    )
    tool = next(item for item in build_match_tools(ctx) if item.name == "open_match")
    result = await tool.ainvoke({"candidate_id": "req-bbbbbb"})
    assert "Open-match limit reached" in result
