from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel
import pytest

from app.agents.runtime import (
    is_retryable_provider_error,
    looks_like_process_dump,
    message_text,
    run_tool_loop,
)
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
    messages, final_text = await run_tool_loop(
        llm,
        [tool],
        [SystemMessage(content="broker"), HumanMessage(content="I need a flat")],
        max_steps=6,
    )
    assert attempts == ["saved", "saved"]
    assert final_text == "Brief saved."
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
    _, final_text = await run_tool_loop(
        llm,
        [tool],
        [SystemMessage(content="broker"), HumanMessage(content="retry")],
        max_steps=4,
    )
    assert attempts == 2
    assert final_text == "Recovered."


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
    messages, final_text = await run_tool_loop(
        llm,
        [tool],
        [SystemMessage(content="broker"), HumanMessage(content="I need a flat")],
        max_steps=4,
    )
    assert seen == ["saved"]
    assert final_text == "Brief saved. What area are you looking in?"
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
    messages, final_text = await run_tool_loop(
        llm,
        [],
        [SystemMessage(content="broker"), HumanMessage(content="find a match")],
        max_steps=2,
    )
    assert llm.calls == 3
    assert final_text == "I'll look and update you."
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


def test_looks_like_process_dump_detects_tool_narration() -> None:
    assert looks_like_process_dump("I called save_request and then search_counterparties.")
    assert looks_like_process_dump("First I'll index the brief, then I'll evaluate pairs.")
    assert looks_like_process_dump("I will classify_attachment and then share_attachment.")
    assert not looks_like_process_dump("I'll look and update you.")
    assert not looks_like_process_dump("What's your budget and preferred area?")


def test_message_text_flattens_content_blocks() -> None:
    assert message_text(" Hello ") == "Hello"
    assert message_text([{"type": "text", "text": "Hi"}, {"type": "text", "text": "there"}]) == "Hi\nthere"


def test_clip_compacts_and_truncates() -> None:
    from app.core.logging import clip

    assert clip(None) == ""
    assert clip("  hello   world  ") == "hello world"
    assert clip({"ok": True, "echo": "saved"}) == '{"ok": true, "echo": "saved"}'
    assert clip("x" * 50, limit=10) == "xxxxxxxxxx..."
