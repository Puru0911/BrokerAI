from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel
import pytest

from app.agents.runtime import (
    build_turn_human_content,
    collect_turn_replies,
    collapse_turn_replies,
    format_session_history_transcript,
    inline_history_in_packet,
    is_retryable_provider_error,
    looks_like_process_dump,
    message_text,
    model_thinking_text,
    run_tool_loop,
    user_facing_reply_text,
)
from app.db.models import AgentMessage
from app.core.config import settings


class EchoArgs(BaseModel):
    text: str


class FakeLLM:
    def __init__(self, responses: list[AIMessage]) -> None:
        self.responses = list(responses)

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        if not self.responses:
            return AIMessage(content="I have enough to keep going.")
        return self.responses.pop(0)


async def test_tool_loop_retries_failed_call_then_skips_success() -> None:
    attempts: list[str] = []

    async def flaky(text: str) -> str:
        attempts.append(text)
        if len(attempts) == 1:
            return json.dumps({"ok": False, "error": "provider unavailable"})
        return json.dumps({"ok": True, "echo": text})

    tool = StructuredTool.from_function(
        name="echo",
        description="Echo text.",
        coroutine=flaky,
        args_schema=EchoArgs,
    )
    same_call = {"name": "echo", "args": {"text": "saved"}, "id": "call-1"}
    llm = FakeLLM(
        [
            AIMessage(content="", tool_calls=[{**same_call, "id": "call-1"}]),
            AIMessage(content="", tool_calls=[{**same_call, "id": "call-2"}]),
            AIMessage(content="", tool_calls=[{**same_call, "id": "call-3"}]),
            AIMessage(content="Brief saved."),
        ]
    )
    messages, final_text, replies = await run_tool_loop(
        llm,
        [tool],
        [SystemMessage(content="broker"), HumanMessage(content="I need a flat")],
        max_steps=6,
    )
    assert attempts == ["saved", "saved"]
    assert final_text == "Brief saved."
    assert replies == ["Brief saved."]
    tool_payloads = [
        json.loads(message.content)
        for message in messages
        if getattr(message, "type", None) == "tool"
    ]
    assert tool_payloads[0] == {"ok": False, "error": "provider unavailable"}
    assert tool_payloads[1] == {"ok": True, "echo": "saved"}
    assert tool_payloads[2] == {"ok": False, "error": "Duplicate tool call skipped."}


async def test_tool_loop_retries_crashed_call() -> None:
    attempts = 0

    async def crash_once(text: str) -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("upstream timeout")
        return json.dumps({"ok": True, "echo": text})

    tool = StructuredTool.from_function(
        name="echo",
        description="Echo text.",
        coroutine=crash_once,
        args_schema=EchoArgs,
    )
    llm = FakeLLM(
        [
            AIMessage(
                content="",
                tool_calls=[{"name": "echo", "args": {"text": "saved"}, "id": "call-1"}],
            ),
            AIMessage(
                content="",
                tool_calls=[{"name": "echo", "args": {"text": "saved"}, "id": "call-2"}],
            ),
            AIMessage(content="Recovered."),
        ]
    )
    _, final_text, replies = await run_tool_loop(
        llm,
        [tool],
        [SystemMessage(content="broker"), HumanMessage(content="retry")],
        max_steps=4,
    )
    assert attempts == 2
    assert final_text == "Recovered."
    assert replies == ["Recovered."]


async def test_tool_loop_calls_tool_then_replies() -> None:
    seen: list[str] = []

    async def echo(text: str) -> str:
        seen.append(text)
        return json.dumps({"ok": True, "echo": text})

    tool = StructuredTool.from_function(
        name="echo",
        description="Echo text.",
        coroutine=echo,
        args_schema=EchoArgs,
    )
    llm = FakeLLM(
        [
            AIMessage(
                content="",
                tool_calls=[{"name": "echo", "args": {"text": "saved"}, "id": "call-1"}],
            ),
            AIMessage(content="Brief saved. What area are you looking in?"),
        ]
    )
    messages, final_text, replies = await run_tool_loop(
        llm,
        [tool],
        [SystemMessage(content="broker"), HumanMessage(content="I need a flat")],
        max_steps=4,
    )
    assert seen == ["saved"]
    assert final_text == "Brief saved. What area are you looking in?"
    assert replies == ["Brief saved. What area are you looking in?"]
    assert any(getattr(message, "type", None) == "tool" for message in messages)


async def test_make_tool_dispatches_pydantic_args() -> None:
    from app.agents.tools._common import make_tool

    async def handler(args: EchoArgs) -> str:
        return json.dumps({"ok": True, "echo": args.text})

    tool = make_tool(
        name="echo",
        description="Echo text.",
        args_model=EchoArgs,
        handler=handler,
    )
    result = await tool.ainvoke({"text": "hello"})
    assert json.loads(result) == {"ok": True, "echo": "hello"}


class ResponseValidationError(Exception):
    """Mirrors the OpenRouter SDK name used by is_retryable_provider_error."""


class FlakyLLM:
    def __init__(self, failures: list[Exception], response: AIMessage) -> None:
        self.failures = list(failures)
        self.response = response
        self.calls = 0
        self.last_messages = None

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        self.last_messages = list(messages)
        if self.failures:
            raise self.failures.pop(0)
        return self.response


def test_is_retryable_provider_error_detects_openrouter_body() -> None:
    assert is_retryable_provider_error(
        ResponseValidationError("5 validation errors for Unmarshaller\nbody.choices")
    )
    assert is_retryable_provider_error(RuntimeError("provider_unavailable"))
    wrapped = RuntimeError("outer")
    wrapped.__cause__ = ResponseValidationError("provider_unavailable")
    assert is_retryable_provider_error(wrapped)
    assert not is_retryable_provider_error(ValueError("bad tool args"))


async def test_tool_loop_retries_provider_error_and_tells_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AGENT_MODEL_INVOKE_RETRIES", 3)
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("app.agents.runtime.asyncio.sleep", fake_sleep)
    llm = FlakyLLM(
        failures=[
            ResponseValidationError("Unmarshaller body.choices provider_unavailable"),
            ResponseValidationError("Unmarshaller body.choices provider_unavailable"),
        ],
        response=AIMessage(content="I'll look and update you."),
    )
    messages, final_text, replies = await run_tool_loop(
        llm,
        [],
        [SystemMessage(content="broker"), HumanMessage(content="find a match")],
        max_steps=2,
    )
    assert llm.calls == 3
    assert final_text == "I'll look and update you."
    assert replies == ["I'll look and update you."]
    assert sleeps == [2, 4]
    notices = [
        message.content
        for message in messages
        if isinstance(message, HumanMessage)
        and "temporarily unavailable" in str(message.content)
    ]
    assert len(notices) == 1


async def test_tool_loop_raises_after_provider_retries_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AGENT_MODEL_INVOKE_RETRIES", 3)

    async def fake_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr("app.agents.runtime.asyncio.sleep", fake_sleep)
    llm = FlakyLLM(
        failures=[
            ResponseValidationError("provider_unavailable"),
            ResponseValidationError("provider_unavailable"),
            ResponseValidationError("provider_unavailable"),
            ResponseValidationError("provider_unavailable"),
        ],
        response=AIMessage(content="should not reach"),
    )
    with pytest.raises(ResponseValidationError):
        await run_tool_loop(
            llm,
            [],
            [SystemMessage(content="broker"), HumanMessage(content="find a match")],
            max_steps=2,
        )
    assert llm.calls == 4


def test_user_facing_reply_text_skips_empty_and_process_dump() -> None:
    assert user_facing_reply_text("") == ""
    assert user_facing_reply_text("I called save_request and then search_counterparties.") == ""
    assert (
        user_facing_reply_text(
            "Good news: the electrician is available tomorrow and quoted around ₹2,000."
        )
        == "Good news: the electrician is available tomorrow and quoted around ₹2,000."
    )


def test_collect_turn_replies_keeps_tool_step_content_and_drops_trailing_ack() -> None:
    stool_update = (
        "Good news: the electrician is available tomorrow and his quote is around "
        "₹2,000 for both fans and sockets in one visit. One small thing — he'll "
        "need a stool or sturdy raised platform to reach the ceiling fans, and he "
        "doesn't carry one with him. Since the flat is still empty, could you have "
        "a stool or a sturdy raised platform ready?"
    )
    messages = [
        SystemMessage(content="broker"),
        HumanMessage(content="match moved"),
        AIMessage(
            content=stool_update,
            tool_calls=[{"name": "update_notebook", "args": {}, "id": "c1"}],
        ),
        ToolMessage(content='{"ok": true}', tool_call_id="c1"),
        AIMessage(content="That's all for now — just let me know on the stool and I'll sort out the rest."),
    ]
    assert collect_turn_replies(messages) == [stool_update]


def test_collect_turn_replies_keeps_distinct_tool_step_updates() -> None:
    first = (
        "Found another electrician from Aundh who services Pimple Nilakh. I'm "
        "checking with them now on availability tomorrow and whether they bring "
        "their own stools and tools. I'll get back to you shortly."
    )
    second = (
        "I've closed out the first electrician (he doesn't carry a stool) and "
        "opened up a new one from Aundh who explicitly services Pimple Nilakh. "
        "I've asked him about tomorrow's availability, whether he brings his own "
        "stools and tools, and his rate. I'll let you know the moment he responds."
    )
    messages = [
        AIMessage(
            content=first,
            tool_calls=[{"name": "message_party", "args": {}, "id": "c1"}],
        ),
        ToolMessage(content='{"ok": true}', tool_call_id="c1"),
        AIMessage(
            content=second,
            tool_calls=[{"name": "update_notebook", "args": {}, "id": "c2"}],
        ),
        ToolMessage(content='{"ok": true}', tool_call_id="c2"),
        AIMessage(content="All set — I'll update you the moment he confirms."),
    ]
    assert collect_turn_replies(messages) == [first, second]


def test_collapse_turn_replies_keeps_a_lone_short_final() -> None:
    assert collapse_turn_replies(["All set — I'll update you the moment he confirms."]) == [
        "All set — I'll update you the moment he confirms."
    ]


def test_collect_turn_replies_ignores_empty_tool_step_content() -> None:
    messages = [
        AIMessage(
            content="",
            tool_calls=[{"name": "search_again", "args": {}, "id": "c1"}],
        ),
        ToolMessage(content='{"ok": true}', tool_call_id="c1"),
        AIMessage(content="I'll look and update you."),
    ]
    assert collect_turn_replies(messages) == ["I'll look and update you."]


def test_collect_turn_replies_skips_session_history_before_start() -> None:
    welcome = "Looking for someone or something specific? Tell me, and I'll get started."
    thanks = (
        "Thanks for reaching out. I've noted your electrical services covering "
        "Aundh, Pimple Nilakh, Pashan, and Baner."
    )
    got_it = (
        "Got it — I've passed your terms and availability to the client. As soon "
        "as they confirm a time, I'll connect you two."
    )
    messages = [
        SystemMessage(content="broker"),
        AIMessage(content=welcome),
        AIMessage(content=thanks),
        HumanMessage(content="site visit terms"),
        AIMessage(
            content="",
            tool_calls=[{"name": "message_party", "args": {}, "id": "c1"}],
        ),
        ToolMessage(content='{"ok": true}', tool_call_id="c1"),
        AIMessage(content=got_it),
    ]
    assert collect_turn_replies(messages, start=4) == [got_it]


async def test_tool_loop_does_not_republish_history_assistant_text() -> None:
    prior = (
        "Thanks for reaching out. I've noted your electrical services covering "
        "Aundh, Pimple Nilakh, Pashan, and Baner."
    )
    got_it = (
        "Got it — I've passed your terms and availability to the client. As soon "
        "as they confirm a time, I'll connect you two."
    )
    llm = FakeLLM([AIMessage(content=got_it)])
    _, final_text, replies = await run_tool_loop(
        llm,
        [],
        [
            SystemMessage(content="broker"),
            AIMessage(content=prior),
            HumanMessage(content="I'm okay with doing the site visit"),
        ],
        max_steps=2,
    )
    assert final_text == got_it
    assert replies == [got_it]


async def test_run_broker_turn_persists_tool_step_content_at_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from app.agents import runtime as runtime_mod
    from app.agents.context import ToolContext

    stool = (
        "Good news: the electrician is available tomorrow and his quote is around "
        "₹2,000. He needs a stool. Can you provide one?"
    )
    ack = "That's all for now — just let me know on the stool and I'll sort out the rest."

    async def fake_loop(_llm, _tools, messages, **_kwargs):
        start = len(messages)
        messages.append(
            AIMessage(
                content=stool,
                tool_calls=[{"name": "update_notebook", "args": {}, "id": "1"}],
            )
        )
        messages.append(ToolMessage(content="{}", tool_call_id="1"))
        messages.append(AIMessage(content=ack))
        return messages, ack, collect_turn_replies(messages, start=start)

    async def fake_packet(_ctx):
        return {"SESSION_ROLE": "source", "open_matches": [], "attention_pointer": "idle"}

    async def fake_history(*_args, **_kwargs):
        return []

    monkeypatch.setattr(runtime_mod, "run_tool_loop", fake_loop)
    monkeypatch.setattr(runtime_mod, "build_context_packet", fake_packet)
    monkeypatch.setattr(runtime_mod, "load_session_history", fake_history)
    monkeypatch.setattr(runtime_mod, "build_turn_human_content", lambda *_a, **_k: "human")
    monkeypatch.setattr(runtime_mod, "inline_history_in_packet", lambda _trigger: False)
    monkeypatch.setattr(
        runtime_mod, "llm_runtime_info", lambda: {"provider": "test", "model": "x"}
    )

    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    session = MagicMock()
    session.id = "sess-1"
    ctx = ToolContext(
        db=db,
        profile=MagicMock(),
        session=session,
        request=None,
        user_message=None,
        trigger="match_context",
    )
    replies = await runtime_mod.run_broker_turn(ctx, llm=object(), tools=[])
    assert [message.content for message in replies] == [stool]
    assert db.add.call_count == 1


async def test_run_broker_turn_does_not_republish_prior_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from app.agents import runtime as runtime_mod
    from app.agents.context import ToolContext

    welcome = "Looking for someone or something specific? Tell me, and I'll get started."
    thanks = (
        "Thanks for reaching out. I've noted your electrical services covering "
        "Aundh, Pimple Nilakh, Pashan, and Baner."
    )
    got_it = (
        "Got it — I've passed your terms and availability to the client. As soon "
        "as they confirm a time, I'll connect you two."
    )

    async def fake_loop(_llm, _tools, messages, **_kwargs):
        start = len(messages)
        messages.append(AIMessage(content=got_it))
        return messages, got_it, collect_turn_replies(messages, start=start)

    async def fake_packet(_ctx):
        return {
            "SESSION_ROLE": "counterparty",
            "open_matches": [],
            "attention_pointer": "idle",
        }

    async def fake_history(*_args, **_kwargs):
        return [
            AgentMessage(role="assistant", content=welcome),
            AgentMessage(role="assistant", content=thanks),
        ]

    monkeypatch.setattr(runtime_mod, "run_tool_loop", fake_loop)
    monkeypatch.setattr(runtime_mod, "build_context_packet", fake_packet)
    monkeypatch.setattr(runtime_mod, "load_session_history", fake_history)
    monkeypatch.setattr(runtime_mod, "build_turn_human_content", lambda *_a, **_k: "human")
    monkeypatch.setattr(runtime_mod, "inline_history_in_packet", lambda _trigger: False)
    monkeypatch.setattr(
        runtime_mod, "llm_runtime_info", lambda: {"provider": "test", "model": "x"}
    )

    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    session = MagicMock()
    session.id = "sess-1"
    ctx = ToolContext(
        db=db,
        profile=MagicMock(),
        session=session,
        request=None,
        user_message=None,
        trigger="user_message",
    )
    replies = await runtime_mod.run_broker_turn(ctx, llm=object(), tools=[])
    assert [message.content for message in replies] == [got_it]
    assert db.add.call_count == 1


def test_looks_like_process_dump_detects_tool_narration() -> None:
    assert looks_like_process_dump("I called save_request and then search_counterparties.")
    assert looks_like_process_dump("First I'll index the brief, then I'll evaluate pairs.")
    assert looks_like_process_dump("I will classify_attachment and then share_attachment.")
    assert looks_like_process_dump("I called offer_introduction.")
    assert not looks_like_process_dump("I'll look and update you.")
    assert not looks_like_process_dump("What's your budget and preferred area?")


def test_message_text_flattens_content_blocks() -> None:
    assert message_text(" Hello ") == "Hello"
    assert message_text([{"type": "text", "text": "Hi"}, {"type": "text", "text": "there"}]) == "Hi\nthere"


def test_model_thinking_text_reads_openrouter_and_groq_fields() -> None:
    empty = AIMessage(content="I'll look and update you.")
    assert model_thinking_text(empty) == ""
    openrouter = AIMessage(
        content="",
        additional_kwargs={
            "reasoning_content": "They uploaded photos, so classify then share.",
            "reasoning_details": [{"type": "reasoning.text", "text": "They uploaded photos, so classify then share."}],
        },
    )
    assert model_thinking_text(openrouter) == "They uploaded photos, so classify then share."
    groq = AIMessage(
        content=[{"type": "thinking", "thinking": "Need to record their go-ahead."}],
        additional_kwargs={},
    )
    assert model_thinking_text(groq) == "Need to record their go-ahead."


def test_clip_compacts_and_truncates() -> None:
    from app.core.logging import clip

    assert clip(None) == ""
    assert clip("  hello   world  ") == "hello world"
    assert clip({"ok": True, "echo": "saved"}) == '{"ok": true, "echo": "saved"}'
    assert clip("x" * 50, limit=10) == "xxxxxxxxxx..."


def test_match_context_inlines_history_after_outreach() -> None:
    assert inline_history_in_packet("match_context") is True
    assert inline_history_in_packet("user_message") is False
    history = [
        AgentMessage(role="user", content="I need a room in Kharadi"),
        AgentMessage(role="assistant", content="What's your budget?"),
    ]
    transcript = format_session_history_transcript(history)
    assert "earlier messages in this private thread" in transcript
    assert "user: I need a room in Kharadi" in transcript
    packet = {
        "SESSION_ROLE": "counterparty",
        "TRIGGER": "match_context",
        "LANE": "match",
        "focus_match_id": "match-1",
        "living_request": {"objective": "List a room"},
        "open_matches": [{"match_id": "match-1"}],
        "other_matches": [{"match_id": "match-2", "label": "housing"}],
        "recent_events": [],
        "attention_pointer": "idle",
        "attachments": [],
        "new_uploads": [],
        "outreach_context": "A tenant asked for photos of the room.",
        "current_user_message": None,
    }
    human = build_turn_human_content(
        packet,
        trigger_instruction="TRIGGER is match_context.",
        history=history,
        inline_history=True,
    )
    assert "LANE: match" in human
    assert "focus_match_id: match-1" in human
    assert "other_matches:" in human
    assert "match-2" in human
    assert human.index("outreach_context") < human.index("this_session_earlier_chat")
    assert human.index("A tenant asked for photos") < human.index("What's your budget?")
    assert "Classify each item this turn" not in human


def test_new_uploads_are_listed_without_forcing_a_tool() -> None:
    packet = {
        "SESSION_ROLE": "source",
        "TRIGGER": "user_message",
        "living_request": {},
        "open_matches": [],
        "recent_events": [],
        "attention_pointer": "idle",
        "attachments": [{"id": "a1"}],
        "new_uploads": [{"id": "a1", "filename": "IMG_6181.jpeg"}],
        "current_user_message": "Uploaded a file: IMG_6181.jpeg",
    }
    human = build_turn_human_content(
        packet,
        trigger_instruction="This person just wrote.",
        history=[],
        inline_history=False,
    )
    assert "IMG_6181.jpeg" in human
    assert "Classify each item this turn" not in human
    assert "new_uploads is non-empty" not in human
