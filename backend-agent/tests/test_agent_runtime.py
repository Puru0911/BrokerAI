from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from app.agents.runtime import looks_like_process_dump, message_text, run_tool_loop


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
