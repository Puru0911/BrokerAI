from app.agents.tools.match_tools import MessagePartyArgs, UpdateNotebookArgs
from app.db.models.broker import AgentMessage, utc_now
from app.services import orchestrator as orchestrator_mod


def test_user_message_path_does_not_auto_start_request_ready() -> None:
    source = orchestrator_mod.handle_session_message.__code__.co_names
    create = orchestrator_mod.create_session_with_agent.__code__.co_names
    assert "_continue_if_ready" not in source
    assert "_continue_if_ready" not in create
    assert not hasattr(orchestrator_mod, "_continue_if_ready")
    assert not hasattr(orchestrator_mod, "assistant_awaiting_user")


def test_message_party_does_not_accept_to() -> None:
    args = MessagePartyArgs(
        match_id="match-1",
        context="They answered location and price. Ask if those terms work.",
        to="source",
    )
    assert "to" not in MessagePartyArgs.model_fields
    assert "to" not in args.model_dump()
    assert "location" in args.context
    schema = MessagePartyArgs.model_json_schema()
    assert "to" not in schema.get("properties", {})
    required = schema.get("required") or []
    assert "match_id" in required
    assert "context" in required
    assert "to" not in required


def test_agent_message_uses_python_created_at_default() -> None:
    column = AgentMessage.__table__.c.created_at
    assert column.default is not None
    assert column.default.is_callable
    assert column.default.arg.__name__ == "utc_now"
    stamp = utc_now()
    assert stamp.tzinfo is not None


def test_update_notebook_args_allow_plan_without_facts() -> None:
    args = UpdateNotebookArgs(
        match_id="match-1",
        agent_note="Constraint is now known; other side has not seen it.",
        next_action="message the source and wait for a yes or no.",
        waiting_on="source",
    )
    assert args.facts is None
    assert args.waiting_on == "source"
