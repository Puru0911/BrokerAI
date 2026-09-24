from unittest.mock import AsyncMock, patch

from app.agents.context import OutreachJob
from app.agents.prompts import MATCH_CONTEXT_INSTRUCTION
from app.agents.runtime import _trigger_instruction
from app.services.outreach import schedule_outreach


def test_match_context_instruction_is_for_this_chat() -> None:
    ctx = type("Ctx", (), {"trigger": "match_context"})()
    text = _trigger_instruction(ctx)
    assert text == MATCH_CONTEXT_INSTRUCTION
    assert "message_party" in text.lower()
    assert "this person" in text.lower()


def test_schedule_outreach_does_not_run_the_turn_inline() -> None:
    jobs = [
        OutreachJob(
            match_id="match-1",
            to="source",
            context="Relay the new constraint and ask if they still want to proceed.",
            from_session_id="session-a",
        )
    ]
    created: list[object] = []

    def fake_create_task(coro, name=None):
        created.append(name)
        coro.close()

    with (
        patch("app.services.outreach.asyncio.create_task", side_effect=fake_create_task),
        patch("app.services.outreach.run_match_context_turn", new_callable=AsyncMock) as run,
    ):
        schedule_outreach(jobs)
    assert created == ["outreach-match-1-source"]
    run.assert_not_called()
