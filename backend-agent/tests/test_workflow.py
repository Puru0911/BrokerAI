from datetime import UTC, datetime, timedelta

from app.agents.context import match_situation
from app.db.models import AgentMatch, AgentRequest
from app.services.workflow import (
    CLOSE_REJECT,
    CLOSE_SKIP,
    MATCH_CLOSED,
    MATCH_OPEN,
    append_match_fact,
    clear_outstanding,
    clear_waiting,
    counterpart_request_id,
    empty_notebook,
    match_notebook,
    party_role,
    request_for_role,
    set_outstanding_question,
    should_reopen_closed_match,
    write_notebook,
)


def test_messaging_other_party_does_not_steal_source_attention() -> None:
    match = AgentMatch(
        id="match-1",
        source_request_id="source",
        candidate_request_id="candidate",
        status=MATCH_OPEN,
    )
    source = AgentRequest(
        id="source",
        session_id="source-session",
        user_id="source-user",
        title="Need a designer",
        summary="Need UI help",
        details={},
        status="open",
    )
    candidate = AgentRequest(
        id="candidate",
        session_id="candidate-session",
        user_id="candidate-user",
        title="UI freelancer",
        summary="I design apps",
        details={},
        status="open",
    )

    candidate.waiting_match_id = match.id

    assert source.waiting_match_id is None
    assert candidate.waiting_match_id == match.id
    assert party_role(match, source) == "source"
    assert party_role(match, candidate) == "candidate"
    assert counterpart_request_id(match, source) == "candidate"


def test_clear_waiting_only_clears_the_named_match() -> None:
    request = AgentRequest(
        id="candidate",
        session_id="s",
        user_id="u",
        title="t",
        summary="s",
        details={},
        waiting_match_id="match-1",
    )
    clear_waiting(request, "match-2")
    assert request.waiting_match_id == "match-1"
    clear_waiting(request, "match-1")
    assert request.waiting_match_id is None


def test_skipped_match_reopens_only_after_a_brief_changes() -> None:
    now = datetime.now(UTC)
    match = AgentMatch(
        id="match-1",
        source_request_id="source",
        candidate_request_id="candidate",
        status=MATCH_CLOSED,
        close_reason=CLOSE_SKIP,
        updated_at=now,
    )
    source = AgentRequest(
        id="source",
        session_id="s",
        user_id="u",
        title="t",
        summary="s",
        details={},
        updated_at=now - timedelta(minutes=5),
    )
    candidate = AgentRequest(
        id="candidate",
        session_id="c",
        user_id="v",
        title="t",
        summary="s",
        details={},
        updated_at=now - timedelta(minutes=5),
    )
    assert should_reopen_closed_match(match, source, candidate) is False
    source.updated_at = now + timedelta(minutes=1)
    assert should_reopen_closed_match(match, source, candidate) is True

    match.close_reason = CLOSE_REJECT
    assert should_reopen_closed_match(match, source, candidate) is False


def test_match_notebook_is_shared_and_does_not_infer_the_new_message() -> None:
    match = AgentMatch(
        id="match-1",
        source_request_id="source",
        candidate_request_id="candidate",
        status=MATCH_OPEN,
        notebook=empty_notebook(),
    )
    set_outstanding_question(
        match,
        waiting_on="candidate",
        question="What is your preferred timeline for purchase?",
    )
    notebook = append_match_fact(
        match,
        by="candidate",
        text="Timeline: within 2 months",
        in_reply_to="What is your preferred timeline for purchase?",
    )
    assert notebook["outstanding"]["waiting_on"] == "candidate"
    assert notebook["facts"][0]["by"] == "candidate"
    assert notebook["facts"][0]["text"] == "Timeline: within 2 months"
    same = match_notebook(match)
    assert same["facts"] == notebook["facts"]
    assert same["agent_note"] is None
    assert same["next_action"] is None


def test_notebook_keeps_agent_note_and_next_action_for_later_turns() -> None:
    match = AgentMatch(
        id="match-1",
        source_request_id="source",
        candidate_request_id="candidate",
        status=MATCH_OPEN,
        notebook=empty_notebook(),
    )
    write_notebook(
        match,
        {
            "facts": [],
            "outstanding": None,
            "agent_note": "They answered location; still need the other party's timing.",
            "next_action": "message source with the new constraint and wait.",
        },
    )
    notebook = match_notebook(match)
    assert "other party's timing" in notebook["agent_note"]
    assert notebook["next_action"].startswith("message source")
    append_match_fact(match, by="candidate", text="Available weekdays only")
    notebook = match_notebook(match)
    assert notebook["facts"][0]["text"] == "Available weekdays only"
    assert "other party's timing" in notebook["agent_note"]
    clear_outstanding(match)
    assert match_notebook(match)["outstanding"] is None
    assert match_notebook(match)["next_action"].startswith("message source")


def test_request_for_role_picks_source_or_candidate() -> None:
    match = AgentMatch(
        id="match-1",
        source_request_id="source",
        candidate_request_id="candidate",
        status=MATCH_OPEN,
    )
    source = AgentRequest(
        id="source",
        session_id="source-session",
        user_id="source-user",
        title="t",
        summary="s",
        details={},
        status="open",
    )
    candidate = AgentRequest(
        id="candidate",
        session_id="candidate-session",
        user_id="candidate-user",
        title="t",
        summary="s",
        details={},
        status="open",
    )
    assert request_for_role(match, source, candidate, "source") is source
    assert request_for_role(match, source, candidate, "candidate") is candidate


def test_situation_does_not_label_the_user_message_as_an_answer() -> None:
    text = match_situation(
        [{"match_id": "match-1", "notebook": {"facts": [], "outstanding": None}}],
        "budget is 70 lakhs",
    )
    assert "user_message (raw): budget is 70 lakhs" in text
    assert "Do not assume" in text
    assert "one broker" in text.lower()
    assert "message_party(to='source'|'candidate')" in text
    assert "update_notebook is agent memory only" in text
    assert match_situation([], "hello") == ""
