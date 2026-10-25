import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.context import ToolContext
from app.agents.tools.attachment_tools import build_attachment_tools
from app.agents.tools.match_tools import build_match_tools
from app.agents.tools.search_tools import build_search_tools
from app.core.config import settings
from app.db.models import AgentMatch, AgentRequest, AgentSuggestedMatch
from app.services.evaluate import PairEvaluation
from app.services.screening import load_candidates_by_id, retrieve_candidates, screen_request
from app.services.suggestions import (
    SUGGESTION_INTERESTED,
    SUGGESTION_PENDING_CLARIFY,
    SUGGESTION_POSSIBLE_MATCH,
    SUGGESTION_PRESENTED,
    SUGGESTION_SKIPPED,
    SUGGESTION_NO_MATCH,
    SUGGESTION_STRONG_MATCH,
    SuggestionError,
    CARD_LABEL_CLOSE,
    CARD_LABEL_STRONG,
    all_pending_questions,
    batch_waiting_on_clarify,
    card_label_for,
    packet_snapshot,
    pending_question_items,
    present_candidates,
    status_for_evaluation,
    this_user_questions_from,
    unpresented_reeval_ids,
    upsert_from_evaluations,
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
    possible_open = PairEvaluation(
        verdict="possible_match",
        score=72,
        recommended_action="open_match",
        candidate_id="cand-5",
    )
    strong_clarify = PairEvaluation(
        verdict="strong_match",
        score=88,
        recommended_action="ask_clarifying_question",
        candidate_id="cand-6",
    )
    assert status_for_evaluation(ready) == SUGGESTION_STRONG_MATCH
    assert status_for_evaluation(clarify) == SUGGESTION_PENDING_CLARIFY
    assert status_for_evaluation(other) == SUGGESTION_POSSIBLE_MATCH
    assert status_for_evaluation(possible_open) == SUGGESTION_POSSIBLE_MATCH
    assert status_for_evaluation(skip) == SUGGESTION_NO_MATCH
    assert status_for_evaluation(strong_clarify) == SUGGESTION_PENDING_CLARIFY


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
    assert "missing_info" not in snap
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
    assert strong_snap["card_label"] == CARD_LABEL_STRONG
    assert snap["card_label"] == CARD_LABEL_CLOSE


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
async def test_message_party_refuses_without_an_open_match() -> None:
    source = _request("req-aaaaaa", "user-a")
    other = _request("req-bbbbbb", "user-b")
    ctx = _ctx(source)
    ctx.db.get = AsyncMock(return_value=other)
    with patch(
        "app.agents.tools.match_tools.get_pair_match",
        AsyncMock(return_value=None),
    ):
        tool = next(item for item in build_match_tools(ctx) if item.name == "message_party")
        result = await tool.ainvoke(
            {"candidate_id": "req-bbbbbb", "context": "Ask if they can relocate."}
        )
    assert '"ok": false' in result
    assert "Interested" in result
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
    result = await tool.ainvoke({"candidate_ids": ["req-bbbbbb"]})
    assert '"ok": true' in result
    assert "The other person was not notified" in result
    assert ctx.current_user_messages[0] is message
    assert ctx.presented_this_turn is True


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
    assert pending_question_items([first, second, strong]) == [
        {"candidate_id": "req-b", "question": "Can you relocate?"},
        {"candidate_id": "req-b", "question": "Do you need parking?"},
        {"candidate_id": "req-c", "question": "When do you need to move?"},
        {"candidate_id": "req-c", "question": "Can you relocate?"},
    ]
    harvested = this_user_questions_from(
        [
            PairEvaluation(
                verdict="possible_match",
                score=65,
                recommended_action="ask_clarifying_question",
                clarifying_question="Can you relocate?",
                clarifying_questions=["Do you need parking?"],
                candidate_id="cand-2",
            ),
            PairEvaluation(
                verdict="possible_match",
                score=70,
                recommended_action="ask_other_person",
                clarifying_questions=["Do you live with family?"],
                candidate_id="cand-3",
            ),
        ]
    )
    assert harvested == ["Can you relocate?", "Do you need parking?"]


@pytest.mark.asyncio
async def test_upsert_from_evaluations_stores_strong_close_and_pending() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    with patch(
        "app.services.suggestions.list_suggestions",
        AsyncMock(return_value=[]),
    ):
        rows = await upsert_from_evaluations(
            db,
            request_id="req-aaaaaa",
            evaluations=[
                PairEvaluation(
                    verdict="strong_match",
                    score=90,
                    recommended_action="open_match",
                    candidate_id="cand-strong",
                ),
                PairEvaluation(
                    verdict="possible_match",
                    score=70,
                    recommended_action="ask_other_person",
                    clarifying_question="Do you live with family?",
                    candidate_id="cand-close",
                ),
                PairEvaluation(
                    verdict="possible_match",
                    score=65,
                    recommended_action="ask_clarifying_question",
                    clarifying_question="Can you relocate?",
                    candidate_id="cand-pending",
                ),
                PairEvaluation(
                    verdict="no_match",
                    score=10,
                    recommended_action="skip",
                    candidate_id="cand-skip",
                ),
            ],
        )
    stored = {row.candidate_request_id: row.status for row in rows}
    assert stored == {
        "cand-strong": SUGGESTION_STRONG_MATCH,
        "cand-close": SUGGESTION_POSSIBLE_MATCH,
        "cand-pending": SUGGESTION_PENDING_CLARIFY,
        "cand-skip": SUGGESTION_NO_MATCH,
    }


@pytest.mark.asyncio
async def test_upsert_promotes_pending_clarify_after_reeval() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    pending = AgentSuggestedMatch(
        id="sug-pending",
        request_id="req-aaaaaa",
        candidate_request_id="cand-pending",
        status=SUGGESTION_PENDING_CLARIFY,
        evaluation={"recommended_action": "ask_clarifying_question"},
    )
    evaluation = PairEvaluation(
        verdict="possible_match",
        score=70,
        recommended_action="ask_clarifying_question",
        clarifying_question="Can they start November 1?",
        candidate_id="cand-pending",
    )
    with patch(
        "app.services.suggestions.list_suggestions",
        AsyncMock(return_value=[pending]),
    ):
        kept = await upsert_from_evaluations(
            db,
            request_id="req-aaaaaa",
            evaluations=[evaluation],
        )
        kept_status = kept[0].status
        promoted = await upsert_from_evaluations(
            db,
            request_id="req-aaaaaa",
            evaluations=[evaluation],
            promote_pending=True,
        )
    assert kept_status == SUGGESTION_PENDING_CLARIFY
    assert promoted[0].status == SUGGESTION_POSSIBLE_MATCH
    assert promoted[0].evaluation["recommended_action"] == "ask_other_person"


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
async def test_present_candidates_shows_strong_while_sibling_pending(
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
    candidate = _request("req-bbbbbb", "user-b")

    async def fake_list(*_args, **_kwargs):
        return [strong, pending]

    db = AsyncMock()
    db.get = AsyncMock(return_value=candidate)
    db.add = MagicMock()
    db.flush = AsyncMock()
    monkeypatch.setattr("app.services.suggestions.list_suggestions", fake_list)
    monkeypatch.setattr("app.services.suggestions.list_matches_for_request", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.services.suggestions.user_ids_for_request_ids", AsyncMock(return_value={}))
    added: list[object] = []
    db.add = MagicMock(side_effect=added.append)
    rows = await present_candidates(
        db,
        session_id=source.session_id,
        request=source,
        items=[
            {
                "candidate_id": "req-bbbbbb",
                "preview": "A complementary roommate in the same area.",
            }
        ],
    )
    assert [row.id for row in rows] == [strong.id]
    assert strong.status == SUGGESTION_PRESENTED
    assert pending.status == SUGGESTION_PENDING_CLARIFY
    payload = json.loads(added[0].content)
    assert "images" not in payload["candidates"][0]
    assert payload["candidates"][0]["preview"].startswith("A complementary")
    assert payload["candidates"][0]["label"] == CARD_LABEL_STRONG


@pytest.mark.asyncio
async def test_present_candidates_does_not_resend_shown_cards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _request("req-aaaaaa", "user-a")
    shown = AgentSuggestedMatch(
        id="sug-1",
        request_id=source.id,
        candidate_request_id="req-bbbbbb",
        status=SUGGESTION_PRESENTED,
        card_message_id="msg-old",
        evaluation={},
    )
    fresh = AgentSuggestedMatch(
        id="sug-2",
        request_id=source.id,
        candidate_request_id="req-cccccc",
        status=SUGGESTION_STRONG_MATCH,
        evaluation={},
    )

    async def fake_list(*_args, **_kwargs):
        return [shown, fresh]

    db = AsyncMock()
    db.get = AsyncMock(return_value=_request("req-cccccc", "user-c"))
    added: list[object] = []
    db.add = MagicMock(side_effect=added.append)
    db.flush = AsyncMock()
    monkeypatch.setattr("app.services.suggestions.list_suggestions", fake_list)
    monkeypatch.setattr("app.services.suggestions.list_matches_for_request", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "app.services.suggestions.user_ids_for_request_ids",
        AsyncMock(return_value={"req-bbbbbb": "user-b"}),
    )
    rows = await present_candidates(
        db,
        session_id=source.session_id,
        request=source,
        items=[{"candidate_id": "req-bbbbbb", "preview": ""}, {"candidate_id": "req-cccccc", "preview": ""}],
    )
    assert [row.id for row in rows] == [fresh.id]
    assert shown.status == SUGGESTION_PRESENTED
    assert shown.card_message_id == "msg-old"
    payload = json.loads(added[0].content)
    assert [item["suggestion_id"] for item in payload["candidates"]] == [fresh.id]


@pytest.mark.asyncio
async def test_present_candidates_shows_new_cards_while_earlier_ones_sit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _request("req-aaaaaa", "user-a")
    shown = [
        AgentSuggestedMatch(
            id=f"sug-{index}",
            request_id=source.id,
            candidate_request_id=f"req-{index}bbbb",
            status=SUGGESTION_PRESENTED,
            card_message_id="msg-old",
        )
        for index in range(3)
    ]
    fresh = AgentSuggestedMatch(
        id="sug-new",
        request_id=source.id,
        candidate_request_id="req-zzzzzz",
        status=SUGGESTION_STRONG_MATCH,
        evaluation={},
    )

    async def fake_list(*_args, **_kwargs):
        return [*shown, fresh]

    db = AsyncMock()
    db.get = AsyncMock(return_value=_request("req-zzzzzz", "user-z"))
    added: list[object] = []
    db.add = MagicMock(side_effect=added.append)
    db.flush = AsyncMock()
    monkeypatch.setattr("app.services.suggestions.list_suggestions", fake_list)
    monkeypatch.setattr("app.services.suggestions.list_matches_for_request", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "app.services.suggestions.user_ids_for_request_ids",
        AsyncMock(return_value={f"req-{index}bbbb": f"user-{index}" for index in range(3)}),
    )
    rows = await present_candidates(db, session_id=source.session_id, request=source)
    assert [row.id for row in rows] == [fresh.id]
    payload = json.loads(added[0].content)
    assert [item["suggestion_id"] for item in payload["candidates"]] == [fresh.id]


@pytest.mark.asyncio
async def test_present_candidates_one_card_per_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _request("req-aaaaaa", "user-a")
    first = AgentSuggestedMatch(
        id="sug-1",
        request_id=source.id,
        candidate_request_id="req-bbbbbb",
        status=SUGGESTION_STRONG_MATCH,
        evaluation={},
    )
    duplicate = AgentSuggestedMatch(
        id="sug-2",
        request_id=source.id,
        candidate_request_id="req-b2bbbb",
        status=SUGGESTION_STRONG_MATCH,
        evaluation={},
    )
    people = {
        "req-bbbbbb": _request("req-bbbbbb", "user-b"),
        "req-b2bbbb": _request("req-b2bbbb", "user-b"),
    }

    async def fake_list(*_args, **_kwargs):
        return [first, duplicate]

    async def fake_get(_model, pk):
        return people.get(pk)

    db = AsyncMock()
    db.get = fake_get
    db.add = MagicMock()
    db.flush = AsyncMock()
    monkeypatch.setattr("app.services.suggestions.list_suggestions", fake_list)
    monkeypatch.setattr("app.services.suggestions.list_matches_for_request", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.services.suggestions.user_ids_for_request_ids", AsyncMock(return_value={}))
    rows = await present_candidates(db, session_id=source.session_id, request=source)
    assert [row.id for row in rows] == [first.id]


@pytest.mark.asyncio
async def test_load_candidates_keeps_one_request_per_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _request("req-aaaaaa", "user-a")
    first = _request("req-bbbbbb", "user-b")
    second = _request("req-b2bbbb", "user-b")
    other = _request("req-cccccc", "user-c")
    people = {item.id: item for item in (first, second, other)}

    async def fake_get(_model, pk):
        return people.get(pk)

    db = AsyncMock()
    db.get = fake_get
    monkeypatch.setattr("app.services.screening.suggestion_user_map", AsyncMock(return_value={}))
    monkeypatch.setattr("app.services.screening.skipped_candidate_ids", AsyncMock(return_value=set()))
    monkeypatch.setattr("app.services.screening.live_counterpart_user_ids", AsyncMock(return_value=set()))
    monkeypatch.setattr(
        "app.services.screening.get_pair_match",
        AsyncMock(return_value=None),
    )
    candidates, errors = await load_candidates_by_id(
        db,
        source,
        [first.id, second.id, other.id],
    )
    assert [item.id for item in candidates] == [first.id, other.id]
    assert any("already in the set" in item for item in errors)


@pytest.mark.asyncio
async def test_retrieve_candidates_skips_second_request_from_same_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _request("req-aaaaaa", "user-a")
    first = _request("req-bbbbbb", "user-b")
    second = _request("req-b2bbbb", "user-b")
    monkeypatch.setattr("app.services.screening.skipped_candidate_ids", AsyncMock(return_value=set()))
    monkeypatch.setattr("app.services.screening.user_ids_for_request_ids", AsyncMock(return_value={}))
    monkeypatch.setattr("app.services.screening.suggestion_user_map", AsyncMock(return_value={}))
    monkeypatch.setattr("app.services.screening.live_counterpart_user_ids", AsyncMock(return_value=set()))
    monkeypatch.setattr(
        "app.services.screening.retrieve_similar_requests",
        AsyncMock(return_value=[(first, 0.1), (second, 0.2)]),
    )
    monkeypatch.setattr("app.services.screening.get_pair_match", AsyncMock(return_value=None))
    matches = await retrieve_candidates(AsyncMock(), source)
    assert [item.id for item, _distance in matches] == [first.id]


@pytest.mark.asyncio
async def test_retrieve_candidates_drops_only_user_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _request("req-aaaaaa", "user-a")
    kept = _request("req-bbbbbb", "user-b")
    skipped = _request("req-cccccc", "user-c")
    monkeypatch.setattr(
        "app.services.screening.skipped_candidate_ids",
        AsyncMock(return_value={skipped.id}),
    )
    monkeypatch.setattr(
        "app.services.screening.user_ids_for_request_ids",
        AsyncMock(return_value={skipped.id: skipped.user_id}),
    )
    monkeypatch.setattr("app.services.screening.live_counterpart_user_ids", AsyncMock(return_value=set()))
    monkeypatch.setattr(
        "app.services.screening.retrieve_similar_requests",
        AsyncMock(return_value=[(kept, 0.1), (skipped, 0.2)]),
    )
    monkeypatch.setattr("app.services.screening.get_pair_match", AsyncMock(return_value=None))
    matches = await retrieve_candidates(AsyncMock(), source)
    assert [item.id for item, _distance in matches] == [kept.id]


@pytest.mark.asyncio
async def test_upsert_keeps_user_skip_when_screener_says_strong() -> None:
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    skipped = AgentSuggestedMatch(
        id="sug-skip",
        request_id="req-aaaaaa",
        candidate_request_id="cand-skip",
        status=SUGGESTION_SKIPPED,
        evaluation={"verdict": "no_match"},
    )
    with patch(
        "app.services.suggestions.list_suggestions",
        AsyncMock(return_value=[skipped]),
    ):
        rows = await upsert_from_evaluations(
            db,
            request_id="req-aaaaaa",
            evaluations=[
                PairEvaluation(
                    verdict="strong_match",
                    score=90,
                    recommended_action="open_match",
                    candidate_id="cand-skip",
                )
            ],
        )
    assert rows[0].status == SUGGESTION_SKIPPED


@pytest.mark.asyncio
async def test_request_attachment_does_not_write_a_card() -> None:
    source = _request("req-aaaaaa", "user-a")
    ctx = _ctx(source)
    tool = next(item for item in build_attachment_tools(ctx) if item.name == "request_attachment")
    result = await tool.ainvoke(
        {"purpose": "resume", "hint": "A recent resume helps.", "suggested_share_class": "public"}
    )
    assert '"ok": true' in result
    assert "No upload card was shown" in result
    assert ctx.current_user_messages == []
    ctx.db.add.assert_not_called()


def test_card_label_stays_close_after_present() -> None:
    row = AgentSuggestedMatch(
        id="sug-1",
        request_id="req-a",
        candidate_request_id="req-b",
        status=SUGGESTION_PRESENTED,
        evaluation={
            "verdict": "possible_match",
            "recommended_action": "ask_other_person",
        },
    )
    assert card_label_for(row) == CARD_LABEL_CLOSE


@pytest.mark.asyncio
async def test_present_candidates_writes_close_fit_gaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _request("req-aaaaaa", "user-a")
    close = AgentSuggestedMatch(
        id="sug-1",
        request_id=source.id,
        candidate_request_id="req-bbbbbb",
        status=SUGGESTION_POSSIBLE_MATCH,
        evaluation={
            "verdict": "possible_match",
            "recommended_action": "ask_other_person",
            "matched": ["Same city", "Budget overlap"],
            "missing_info": ["Family living arrangement"],
            "mismatched": ["Timeline"],
            "source_relative_brief": "A close counterpart in the same city.",
        },
    )

    async def fake_list(*_args, **_kwargs):
        return [close]

    db = AsyncMock()
    db.get = AsyncMock(return_value=_request("req-bbbbbb", "user-b"))
    added: list[object] = []
    db.add = MagicMock(side_effect=added.append)
    db.flush = AsyncMock()
    monkeypatch.setattr("app.services.suggestions.list_suggestions", fake_list)
    monkeypatch.setattr("app.services.suggestions.list_matches_for_request", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.services.suggestions.user_ids_for_request_ids", AsyncMock(return_value={}))
    rows = await present_candidates(db, session_id=source.session_id, request=source)
    assert [row.id for row in rows] == [close.id]
    payload = json.loads(added[0].content)
    card = payload["candidates"][0]
    assert card["label"] == CARD_LABEL_CLOSE
    assert card["fits"] == ["Same city", "Budget overlap"]
    assert card["still_open"] == ["Family living arrangement", "Timeline"]


@pytest.mark.asyncio
async def test_present_candidates_refuses_pending_clarify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _request("req-aaaaaa", "user-a")
    pending = AgentSuggestedMatch(
        id="sug-1",
        request_id=source.id,
        candidate_request_id="req-bbbbbb",
        status=SUGGESTION_PENDING_CLARIFY,
        evaluation={"clarifying_question": "Can you relocate?"},
    )

    async def fake_list(*_args, **_kwargs):
        return [pending]

    db = AsyncMock()
    monkeypatch.setattr("app.services.suggestions.list_suggestions", fake_list)
    with pytest.raises(SuggestionError, match="not ready to present"):
        await present_candidates(
            db,
            session_id=source.session_id,
            request=source,
            items=[{"candidate_id": "req-bbbbbb", "preview": ""}],
        )


@pytest.mark.asyncio
async def test_unpresented_reeval_ids_skip_shown_cards() -> None:
    pending = AgentSuggestedMatch(
        id="sug-1",
        request_id="req-a",
        candidate_request_id="cand-pending",
        status=SUGGESTION_PENDING_CLARIFY,
    )
    close = AgentSuggestedMatch(
        id="sug-2",
        request_id="req-a",
        candidate_request_id="cand-close",
        status=SUGGESTION_POSSIBLE_MATCH,
    )
    shown = AgentSuggestedMatch(
        id="sug-3",
        request_id="req-a",
        candidate_request_id="cand-shown",
        status=SUGGESTION_POSSIBLE_MATCH,
        card_message_id="msg-1",
    )
    with patch(
        "app.services.suggestions.list_suggestions",
        AsyncMock(return_value=[pending, close, shown]),
    ):
        ids = await unpresented_reeval_ids(AsyncMock(), "req-a")
    assert ids == ["cand-pending", "cand-close"]


@pytest.mark.asyncio
async def test_screen_request_reevals_stored_before_new_hits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _request("req-aaaaaa", "user-a")
    stored = _request("req-stored", "user-s")
    fresh = _request("req-freshh", "user-f")
    monkeypatch.setattr(
        "app.services.screening.unpresented_reeval_ids",
        AsyncMock(return_value=[stored.id]),
    )
    monkeypatch.setattr(
        "app.services.screening.load_candidates_by_id",
        AsyncMock(return_value=([stored], [])),
    )
    monkeypatch.setattr(
        "app.services.screening.retrieve_candidates",
        AsyncMock(return_value=[(fresh, 0.1)]),
    )
    monkeypatch.setattr(
        "app.services.screening._prior_events_for",
        AsyncMock(return_value={}),
    )
    seen: list[list[str]] = []

    async def fake_eval(request, candidates, prior_events_by_id=None, view_filters=None):
        seen.append([item.id for item in candidates])
        return [
            PairEvaluation(
                verdict="possible_match",
                score=65,
                recommended_action="ask_clarifying_question",
                candidate_id=stored.id,
            ),
            PairEvaluation(
                verdict="strong_match",
                score=90,
                recommended_action="open_match",
                candidate_id=fresh.id,
            ),
        ]

    monkeypatch.setattr("app.services.screening.evaluate_pairs", fake_eval)
    monkeypatch.setattr(
        "app.services.screening.upsert_from_evaluations",
        AsyncMock(return_value=[]),
    )
    summary = await screen_request(AsyncMock(), source)
    assert seen == [[stored.id, fresh.id]]
    assert summary["candidate_ids"] == [stored.id, fresh.id]
