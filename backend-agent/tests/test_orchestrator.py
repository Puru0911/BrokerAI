from app.agents.tools.match_tools import MessagePartyArgs, UpdateNotebookArgs
from app.services import orchestrator as orchestrator_mod


def test_user_message_path_does_not_auto_start_request_ready() -> None:
    source = orchestrator_mod.handle_session_message.__code__.co_names
    create = orchestrator_mod.create_session_with_agent.__code__.co_names
    assert "_continue_if_ready" not in source
    assert "_continue_if_ready" not in create
    assert not hasattr(orchestrator_mod, "_continue_if_ready")
    assert not hasattr(orchestrator_mod, "assistant_awaiting_user")


def test_message_party_requires_explicit_party() -> None:
    args = MessagePartyArgs(match_id="match-1", to="source", message="Are you still interested?")
    assert args.to == "source"
    assert args.expects_reply is None
    candidate = MessagePartyArgs(match_id="match-1", to="candidate", message="Status update.")
    assert candidate.to == "candidate"


def test_update_notebook_args_allow_plan_without_facts() -> None:
    args = UpdateNotebookArgs(
        match_id="match-1",
        agent_note="Constraint is now known; other side has not seen it.",
        next_action="message the source and wait for a yes or no.",
        waiting_on="source",
    )
    assert args.facts is None
    assert args.waiting_on == "source"
