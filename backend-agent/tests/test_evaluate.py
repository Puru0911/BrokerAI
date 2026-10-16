from app.services.evaluate import PairEvaluation


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
