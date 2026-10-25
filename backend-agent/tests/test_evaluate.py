from unittest.mock import patch

import pytest

from app.db.models import AgentRequest
from app.services.evaluate import PairEvaluation, clarifying_questions_from, evaluate_pairs


def test_pair_evaluation_keeps_ask_clarifying_question() -> None:
    evaluation = PairEvaluation(
        verdict="possible_match",
        score=65,
        recommended_action="ask_clarifying_question",
        clarifying_question="Can you relocate?",
        candidate_id="cand-1",
    )
    assert evaluation.recommended_action == "ask_clarifying_question"
    assert evaluation.clarifying_question == "Can you relocate?"
    assert evaluation.candidate_id == "cand-1"
    evaluation.clarifying_questions = ["Can you relocate?", "Do you need parking?"]
    assert clarifying_questions_from(evaluation) == [
        "Can you relocate?",
        "Do you need parking?",
    ]
    assert clarifying_questions_from(
        {
            "clarifying_question": "Can you relocate?",
            "clarifying_questions": ["Do you need parking?", "Can you relocate?"],
        }
    ) == ["Can you relocate?", "Do you need parking?"]


def test_pair_evaluation_accepts_ask_other_person() -> None:
    evaluation = PairEvaluation(
        verdict="possible_match",
        score=70,
        recommended_action="ask_other_person",
        clarifying_question="Are they open to relocating?",
        candidate_id="cand-2",
    )
    assert evaluation.recommended_action == "ask_other_person"
    assert evaluation.candidate_id == "cand-2"


def test_screener_does_not_require_candidate_id() -> None:
    evaluation = PairEvaluation(
        verdict="strong_match",
        score=90,
        recommended_action="open_match",
    )
    assert evaluation.candidate_id == ""
    evaluation.candidate_id = "cand-3"
    assert evaluation.candidate_id == "cand-3"


@pytest.mark.asyncio
async def test_evaluate_pairs_stamps_each_candidate() -> None:
    source = AgentRequest(
        id="req-a",
        session_id="sess-a",
        user_id="user-a",
        title="A",
        summary="A",
        details={},
        status="open",
    )
    first = AgentRequest(
        id="cand-1",
        session_id="sess-1",
        user_id="user-1",
        title="B",
        summary="B",
        details={},
        status="open",
    )
    second = AgentRequest(
        id="cand-2",
        session_id="sess-2",
        user_id="user-2",
        title="C",
        summary="C",
        details={},
        status="open",
    )

    async def fake_evaluate(
        source_request,
        candidate_request,
        retrieval_distance=None,
        prior_events=None,
        view_filters=None,
    ):
        return PairEvaluation(
            verdict="possible_match",
            score=60,
            recommended_action="ask_clarifying_question",
            candidate_id=candidate_request.id,
            clarifying_question="Can you relocate?",
        )

    with patch("app.services.evaluate.evaluate_pair", side_effect=fake_evaluate) as mocked:
        results = await evaluate_pairs(
            source,
            [first, second],
            view_filters=["Kharadi", "furnished"],
        )
    assert [item.candidate_id for item in results] == ["cand-1", "cand-2"]
    assert mocked.await_args_list[0].kwargs["view_filters"] == ["Kharadi", "furnished"]
