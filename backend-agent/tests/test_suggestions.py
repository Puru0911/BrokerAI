from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.agents.context import ToolContext
from app.agents.tools.match_tools import build_match_tools
from app.agents.tools.search_tools import EvaluatePairArgs, build_search_tools
from app.core.config import settings
from app.db.models import AgentMatch, AgentRequest, AgentSuggestedMatch
from app.services.evaluate import PairEvaluation
from app.services.suggestions import (
    SUGGESTION_INTERESTED,
    SUGGESTION_PENDING_CLARIFY,
    SUGGESTION_PRESENTED,
    SUGGESTION_SKIPPED,
    SUGGESTION_STRONG_MATCH,
    SuggestionError,
    all_pending_questions,
    batch_waiting_on_clarify,
    packet_snapshot,
    present_candidates,
    status_for_evaluation,
)


def _request(request_id: str, user_id: str) -> AgentRequest:
    return AgentRequest(
        id=request_id,
        session_id=f"sess-{request_id}",
        user_id=user_id,
        title="Need a match",
        summary="Looking",
        details={},
        status="open",
    )


def _ctx(source: AgentRequest, *, trigger: str = "user_message") -> ToolContext:
    return ToolContext(
        db=AsyncMock(),
        profile=MagicMock(id="user-a"),
        session=MagicMock(id=source.session_id),
        request=source,
        user_message=None,
        trigger=trigger,
    )


def test_max_pair_per_request_is_three() -> None:
    assert settings.MAX_PAIR_PER_REQUEST == 3


def test_evaluate_pair_args_collects_ids() -> None:
    args = EvaluatePairArgs(candidate_ids=["cand-aaaa", "cand-bbbb"], candidate_id="cand-aaaa")
    assert args.candidate_ids == ["cand-aaaa", "cand-bbbb"]
    single = EvaluatePairArgs(candidate_id="cand-cccc")
    assert single.candidate_ids == ["cand-cccc"]
    with pytest.raises(ValidationError):
        EvaluatePairArgs()


def test_status_for_evaluation_maps_actions() -> None:
    ready = PairEvaluation(
        verdict="strong_match",
        score=90,
        recommended_action="open_match",
        candidate_id="cand-1",
    )
    clarify = PairEvaluation(
        verdict="possible_match",
        score=65,
        recommended_action="ask_clarifying_question",
        candidate_id="cand-2",
    )
    other = PairEvaluation(
        verdict="possible_match",
        score=70,
        recommended_action="ask_other_person",
        candidate_id="cand-3",
    )
    skip = PairEvaluation(
        verdict="no_match",
        score=10,
        recommended_action="skip",
        candidate_id="cand-4",
    )
    assert status_for_evaluation(ready) == SUGGESTION_STRONG_MATCH
    assert status_for_evaluation(clarify) == SUGGESTION_PENDING_CLARIFY
    assert status_for_evaluation(other) == SUGGESTION_STRONG_MATCH
    assert status_for_evaluation(skip) == SUGGESTION_SKIPPED


def test_packet_snapshot_is_source_only() -> None:
    row = AgentSuggestedMatch(
        id="sug-1",
        request_id="req-a",
        candidate_request_id="req-b",
        status=SUGGESTION_PENDING_CLARIFY,
        evaluation={
            "verdict": "possible_match",
            "recommended_action": "ask_clarifying_question",
            "clarifying_question": "Can you relocate?",
            "clarifying_questions": ["Can you relocate?", "Do you need parking?"],
            "missing_info": ["relocation", "parking"],
            "score": 62,
        },
    )
    snap = packet_snapshot(row)
    assert snap["suggestion_id"] == "sug-1"
    assert snap["candidate_id"] == "req-b"
    assert snap["status"] == SUGGESTION_PENDING_CLARIFY
    assert snap["pending_clarify"] == "Can you relocate?"
    assert snap["clarifying_question"] == "Can you relocate?"
    assert snap["pending_questions"] == ["Can you relocate?", "Do you need parking?"]
    assert snap["missing_info"] == ["relocation", "parking"]
    assert snap["presented"] is False

    strong = AgentSuggestedMatch(
        id="sug-2",
        request_id="req-a",
        candidate_request_id="req-c",
        status=SUGGESTION_STRONG_MATCH,
        evaluation={"verdict": "strong_match", "recommended_action": "open_match"},
    )
    strong_snap = packet_snapshot(strong)
    assert strong_snap["status"] == SUGGESTION_STRONG_MATCH
    assert strong_snap["pending_clarify"] is None
    assert strong_snap["clarifying_question"] == ""
    assert strong_snap["pending_questions"] == []


@pytest.mark.asyncio
async def test_open_match_refused_until_interested() -> None:
    source = _request("req-aaaaaa", "user-a")
    ctx = _ctx(source)
    with (
        patch("app.agents.tools.match_tools.get_pair_match", AsyncMock(return_value=None)),
        patch(
            "app.agents.tools.match_tools.suggestion_for_pair",
            AsyncMock(return_value=SimpleNamespace(status=SUGGESTION_STRONG_MATCH)),
        ),
        patch("app.agents.tools.match_tools.open_working_match", AsyncMock()) as opened,
    ):
        ctx.db.get = AsyncMock(return_value=_request("req-bbbbbb", "user-b"))
        tool = next(item for item in build_match_tools(ctx) if item.name == "open_match")
        result = await tool.ainvoke({"candidate_id": "req-bbbbbb"})
    assert "has not marked Interested" in result
    opened.assert_not_called()


@pytest.mark.asyncio
async def test_open_match_runs_after_interested() -> None:
    source = _request("req-aaaaaa", "user-a")
    candidate = _request("req-bbbbbb", "user-b")
    match = AgentMatch(
        id="match-1",
        source_request_id=source.id,
        candidate_request_id=candidate.id,
        status="open",
    )
    ctx = _ctx(source)
    ctx.db.get = AsyncMock(return_value=candidate)
    with (
        patch("app.agents.tools.match_tools.get_pair_match", AsyncMock(return_value=None)),
        patch(
            "app.agents.tools.match_tools.suggestion_for_pair",
            AsyncMock(return_value=SimpleNamespace(status=SUGGESTION_INTERESTED)),
        ),
        patch(
            "app.agents.tools.match_tools.open_working_match",
            AsyncMock(return_value=(match, False)),
        ) as opened,
    ):
        tool = next(item for item in build_match_tools(ctx) if item.name == "open_match")
        result = await tool.ainvoke({"candidate_id": "req-bbbbbb"})
    assert '"ok": true' in result
    opened.assert_awaited()
    assert match.id in ctx.opened_match_ids


@pytest.mark.asyncio
async def test_message_party_refuses_pre_open_outreach() -> None:
    source = _request("req-aaaaaa", "user-a")
    ctx = _ctx(source)
    tool = next(item for item in build_match_tools(ctx) if item.name == "message_party")
    result = await tool.ainvoke(
        {"candidate_id": "req-bbbbbb", "context": "Ask if they can relocate."}
    )
    assert '"ok": false' in result
    assert "Open a match first" in result
    assert ctx.queued_outreach == []


@pytest.mark.asyncio
async def test_open_match_refused_on_match_context_without_focus() -> None:
    source = _request("req-bbbbbb", "user-b")
    ctx = _ctx(source, trigger="match_context")
    ctx.focus_match_id = None
    tool = next(item for item in build_match_tools(ctx) if item.name == "open_match")
    result = await tool.ainvoke({"candidate_id": "12345678-1234-1234-1234-1234567890ab"})
    assert "Do not open a match yet" in result


@pytest.mark.asyncio
async def test_present_candidates_writes_cards(monkeypatch: pytest.MonkeyPatch) -> None:
    source = _request("req-aaaaaa", "user-a")
    ctx = _ctx(source)
    row = AgentSuggestedMatch(
        id="sug-1",
        request_id=source.id,
        candidate_request_id="req-bbbbbb",
        status=SUGGESTION_PRESENTED,
        card_message_id="msg-1",
    )
    message = SimpleNamespace(id="msg-1", session_id=source.session_id)
    ctx.db.get = AsyncMock(return_value=message)

    async def fake_present(*_args, **_kwargs):
        return [row]

    monkeypatch.setattr("app.agents.tools.search_tools.present_candidates", fake_present)
    tool = next(item for item in build_search_tools(ctx) if item.name == "present_candidates")
    result = await tool.ainvoke(
        {
            "candidates": [
                {
                    "candidate_id": "req-bbbbbb",
                    "preview": "A complementary roommate in the same area.",
                }
            ]
        }
    )
    assert '"ok": true' in result
    assert "The other person was not notified" in result
    assert ctx.current_user_messages[0] is message


def test_pending_questions_collect_from_every_pair() -> None:
    first = AgentSuggestedMatch(
        id="sug-1",
        request_id="req-a",
        candidate_request_id="req-b",
        status=SUGGESTION_PENDING_CLARIFY,
        evaluation={
            "clarifying_question": "Can you relocate?",
            "clarifying_questions": ["Do you need parking?"],
        },
    )
    second = AgentSuggestedMatch(
        id="sug-2",
        request_id="req-a",
        candidate_request_id="req-c",
        status=SUGGESTION_PENDING_CLARIFY,
        evaluation={"clarifying_questions": ["When do you need to move?", "Can you relocate?"]},
    )
    strong = AgentSuggestedMatch(
        id="sug-3",
        request_id="req-a",
        candidate_request_id="req-d",
        status=SUGGESTION_STRONG_MATCH,
        evaluation={"clarifying_question": "Ignore this on a strong match."},
    )
    assert all_pending_questions([first, second, strong]) == [
        "Can you relocate?",
        "Do you need parking?",
        "When do you need to move?",
    ]


def test_batch_waits_when_any_pair_needs_a_question() -> None:
    strong = AgentSuggestedMatch(
        id="sug-1",
        request_id="req-a",
        candidate_request_id="req-b",
        status=SUGGESTION_STRONG_MATCH,
        evaluation={},
    )
    pending = AgentSuggestedMatch(
        id="sug-2",
        request_id="req-a",
        candidate_request_id="req-c",
        status=SUGGESTION_PENDING_CLARIFY,
        evaluation={"clarifying_question": "Can you relocate?"},
    )
    assert batch_waiting_on_clarify([strong, pending]) is True
    assert batch_waiting_on_clarify([strong]) is False
    legacy = AgentSuggestedMatch(
        id="sug-3",
        request_id="req-a",
        candidate_request_id="req-d",
        status="ready",
        evaluation={},
    )
    assert packet_snapshot(legacy)["status"] == SUGGESTION_STRONG_MATCH
    assert packet_snapshot(legacy)["pending_clarify"] is None


@pytest.mark.asyncio
async def test_present_candidates_holds_the_batch_while_clarify_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _request("req-aaaaaa", "user-a")
    strong = AgentSuggestedMatch(
        id="sug-1",
        request_id=source.id,
        candidate_request_id="req-bbbbbb",
        status=SUGGESTION_STRONG_MATCH,
        evaluation={},
    )
    pending = AgentSuggestedMatch(
        id="sug-2",
        request_id=source.id,
        candidate_request_id="req-cccccc",
        status=SUGGESTION_PENDING_CLARIFY,
        evaluation={"clarifying_question": "Can you relocate?"},
    )

    async def fake_list(*_args, **_kwargs):
        return [strong, pending]

    monkeypatch.setattr("app.services.suggestions.list_suggestions", fake_list)
    with pytest.raises(SuggestionError, match="clarifying question"):
        await present_candidates(
            AsyncMock(),
            session_id=source.session_id,
            request=source,
            items=[
                {
                    "candidate_id": "req-bbbbbb",
                    "preview": "A complementary roommate in the same area.",
                }
            ],
        )
