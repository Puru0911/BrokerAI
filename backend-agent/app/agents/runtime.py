from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool

from app.agents.context import ToolContext, build_context_packet, load_session_history
from app.agents.prompts import (
    BROKER_SYSTEM_PROMPT,
    MATCH_TIMEOUT_INSTRUCTION,
    NATURAL_FALLBACK_REPLY,
    REQUEST_READY_INSTRUCTION,
    UNAVAILABLE_REPLY,
)
from app.agents.tool_call_repair import repair_tool_message
from app.agents.tools.registry import build_broker_tools
from app.core.config import settings
from app.core.logging import clip
from app.db.models import AgentMessage
from app.llm.client import build_broker_chat_model, is_llm_configured, llm_runtime_info

logger = logging.getLogger(__name__)


def _tool_status(result: str) -> str:
    try:
        payload = json.loads(result)
    except json.JSONDecodeError:
        return "tool"
    if isinstance(payload, dict):
        return "ok" if payload.get("ok") else "error"
    return "tool"


_PROCESS_LEAK_MARKERS = (
    "save_request",
    "index_request",
    "search_counterparties",
    "evaluate_pair",
    "open_match",
    "message_party",
    "update_notebook",
    "record_facts",
    "skip_match",
    "reject_match",
    "accept_match",
    "share_contacts",
    "search_again",
    "get_match_events",
    "get_request_snapshot",
    "request_attachment",
    "classify_attachment",
    "share_attachment",
    "record_share_grant",
    "tool call",
    "i indexed",
    "i evaluated",
    "opened a match",
    "i will now",
    "i'll now",
    "first i'll",
    "next i will",
    "next i'll",
)


def looks_like_process_dump(text: str) -> bool:
    """True when a user-facing reply is narrating tools or internal steps."""
    lowered = text.lower()
    return any(marker in lowered for marker in _PROCESS_LEAK_MARKERS)


def message_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "\n".join(part for part in parts if part).strip()
    return str(content or "").strip()


def _history_as_lc(messages: list[AgentMessage]) -> list[BaseMessage]:
    converted: list[BaseMessage] = []
    for message in messages:
        if message.role == "user":
            converted.append(HumanMessage(content=message.content))
        elif message.role == "assistant":
            converted.append(AIMessage(content=message.content))
    return converted


def _trigger_instruction(ctx: ToolContext) -> str:
    if ctx.trigger == "request_ready":
        return REQUEST_READY_INSTRUCTION
    if ctx.trigger == "match_timeout":
        return MATCH_TIMEOUT_INSTRUCTION
    return (
        "Respond to the current user as their broker. The message they see must be "
        "natural conversation only — questions, a short acknowledgement, or that you "
        "will look and update them. Do not mention tools, steps, or methods."
    )


_RETRYABLE_PROVIDER_ERROR_NAMES = frozenset(
    {
        "ResponseValidationError",
        "BadGatewayResponseError",
        "ProviderOverloadedResponseError",
        "ServiceUnavailableResponseError",
    }
)
_RETRYABLE_PROVIDER_MARKERS = (
    "provider_unavailable",
    "provider overloaded",
    "validation errors for unmarshaller",
    "body.choices",
)
_PROVIDER_RETRY_NOTICE = (
    "The previous generation attempt failed because the model provider was "
    "temporarily unavailable. Continue from the current conversation and any "
    "tool results already in this turn. Do not repeat a tool that already "
    "succeeded. Take the next action now, or reply to the user if you are done."
)


def is_retryable_provider_error(exc: BaseException) -> bool:
    """True for OpenRouter 200+error bodies and upstream unavailability."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if type(current).__name__ in _RETRYABLE_PROVIDER_ERROR_NAMES:
            return True
        text = str(current).lower()
        if any(marker in text for marker in _RETRYABLE_PROVIDER_MARKERS):
            return True
        current = current.__cause__ or current.__context__
    return False


def _tool_names(tool_calls: list[Any]) -> list[str]:
    names: list[str] = []
    for call in tool_calls:
        if isinstance(call, dict):
            names.append(str(call.get("name") or ""))
        else:
            names.append(str(getattr(call, "name", "") or ""))
    return names


async def run_tool_loop(
    llm: Any,
    tools: list[BaseTool],
    messages: list[BaseMessage],
    *,
    max_steps: int,
    on_tool: Any | None = None,
    session_id: str | None = None,
) -> tuple[list[BaseMessage], str | None]:
    """Run bind_tools until the model replies or the step budget is spent."""
    tool_map = {tool.name: tool for tool in tools}
    if hasattr(llm, "bind_tools"):
        bound = llm.bind_tools(tools, parallel_tool_calls=False)
    else:
        bound = llm
    final_text: str | None = None
    seen_calls: set[str] = set()
    sid = session_id or "-"

    max_retries = max(0, int(settings.AGENT_MODEL_INVOKE_RETRIES))
    for step in range(max_steps):
        logger.debug("tool loop step %s/%s session=%s", step + 1, max_steps, sid)
        response = None
        provider_failures = 0
        while True:
            try:
                response = await bound.ainvoke(messages)
                break
            except Exception as exc:
                repaired = repair_tool_message(exc)
                if repaired is not None:
                    logger.warning(
                        "provider rejected tool JSON; repaired XML session=%s step=%s tools=%s",
                        sid,
                        step + 1,
                        _tool_names(getattr(repaired, "tool_calls", None) or []),
                    )
                    response = repaired
                    break
                if is_retryable_provider_error(exc) and provider_failures < max_retries:
                    provider_failures += 1
                    logger.warning(
                        "model invoke retry session=%s step=%s attempt=%s/%s error=%s",
                        sid,
                        step + 1,
                        provider_failures,
                        max_retries,
                        clip(str(exc), 240),
                    )
                    if provider_failures == 1:
                        messages.append(HumanMessage(content=_PROVIDER_RETRY_NOTICE))
                    await asyncio.sleep(min(2 * provider_failures, 6))
                    continue
                logger.warning(
                    "model invoke failed session=%s step=%s error=%s",
                    sid,
                    step + 1,
                    exc,
                )
                raise
        if response is None:
            raise RuntimeError("model invoke returned no response")
        messages.append(response)
        tool_calls = getattr(response, "tool_calls", None) or []
        content_preview = clip(message_text(getattr(response, "content", "")), 300)
        if not tool_calls:
            final_text = message_text(getattr(response, "content", ""))
            logger.info(
                "model returned no tool calls session=%s step=%s content=%s",
                sid,
                step + 1,
                clip(final_text, 300),
            )
            break
        logger.info(
            "model tool calls session=%s step=%s tools=%s content=%s",
            sid,
            step + 1,
            _tool_names(tool_calls),
            content_preview,
        )

        for call in tool_calls:
            name = call.get("name") if isinstance(call, dict) else getattr(call, "name", "")
            args = call.get("args") if isinstance(call, dict) else getattr(call, "args", {})
            call_id = call.get("id") if isinstance(call, dict) else getattr(call, "id", "")
            signature = json.dumps({"name": name, "args": args}, sort_keys=True, default=str)
            tool = tool_map.get(name)
            started = time.perf_counter()
            skip_reason = None
            if signature in seen_calls:
                skip_reason = "duplicate"
                result = json.dumps({"ok": False, "error": "Duplicate tool call skipped."})
            elif tool is None:
                skip_reason = "unknown"
                result = json.dumps({"ok": False, "error": f"Unknown tool '{name}'"})
            else:
                seen_calls.add(signature)
                try:
                    result = await tool.ainvoke(args or {})
                except Exception as exc:  # noqa: BLE001
                    logger.warning("tool crashed session=%s tool=%s error=%s", sid, name, exc)
                    result = json.dumps({"ok": False, "error": str(exc)})
            latency_ms = round((time.perf_counter() - started) * 1000)
            status = _tool_status(result)
            if skip_reason:
                logger.info(
                    "tool skipped session=%s tool=%s reason=%s",
                    sid,
                    name,
                    skip_reason,
                )
            else:
                logger.info(
                    "tool %s status=%s latency_ms=%s session=%s",
                    name,
                    status,
                    latency_ms,
                    sid,
                )
            logger.debug("tool %s args=%s result=%s session=%s", name, clip(args), clip(result), sid)
            if on_tool is not None:
                await on_tool(name, args, result, latency_ms, status)
            messages.append(ToolMessage(content=str(result), tool_call_id=call_id or name))

    return messages, final_text


async def run_broker_turn(
    ctx: ToolContext,
    *,
    llm: Any | None = None,
    tools: list[BaseTool] | None = None,
) -> list[AgentMessage]:
    """Run one broker turn and persist user-facing assistant messages for this session."""
    living = (ctx.request.details or {}) if ctx.request else {}
    runtime = llm_runtime_info()
    logger.info(
        "broker turn start session=%s trigger=%s provider=%s model=%s has_request=%s indexed=%s objective=%s user_message=%s",
        ctx.session.id,
        ctx.trigger,
        runtime["provider"],
        runtime["model"],
        ctx.request is not None,
        ctx.request.indexed_at is not None if ctx.request else False,
        clip(living.get("objective"), 160),
        clip(ctx.user_message.content if ctx.user_message else "", 200),
    )

    if llm is None and not is_llm_configured():
        logger.warning("broker turn skipped, llm not configured session=%s", ctx.session.id)
        message = AgentMessage(
            session_id=ctx.session.id,
            role="assistant",
            content=UNAVAILABLE_REPLY,
        )
        ctx.db.add(message)
        await ctx.db.flush()
        ctx.track(message)
        return ctx.current_user_messages

    tools = tools if tools is not None else build_broker_tools(ctx)
    model = llm if llm is not None else build_broker_chat_model()
    packet = await build_context_packet(ctx)
    history = await load_session_history(
        ctx.db,
        ctx.session.id,
        exclude_message_id=ctx.user_message.id if ctx.user_message else None,
    )
    user_text = ctx.user_message.content if ctx.user_message else ""
    logger.debug(
        "broker context session=%s role=%s open_matches=%s attention=%s history=%s",
        ctx.session.id,
        packet.get("SESSION_ROLE"),
        len(packet.get("open_matches") or []),
        packet.get("attention_pointer"),
        len(history),
    )
    human = (
        f"SESSION_ROLE: {packet.get('SESSION_ROLE')}\n"
        f"TRIGGER: {packet.get('TRIGGER')}\n\n"
        f"{_trigger_instruction(ctx)}\n\n"
    )
    human += (
        f"living_request:\n{json.dumps(packet.get('living_request'), ensure_ascii=False, default=str)}\n\n"
        f"open_matches:\n{json.dumps(packet.get('open_matches'), ensure_ascii=False, default=str)}\n\n"
        f"recent_events:\n{json.dumps(packet.get('recent_events'), ensure_ascii=False, default=str)}\n\n"
        f"attention_pointer: {packet.get('attention_pointer')}\n"
    )
    human += (
        f"attachments:\n{json.dumps(packet.get('attachments'), ensure_ascii=False, default=str)}\n\n"
        f"new_uploads:\n{json.dumps(packet.get('new_uploads'), ensure_ascii=False, default=str)}\n"
    )
    if packet.get("new_uploads"):
        human += (
            "\nThe user just uploaded file(s) or link(s). Classify each new_uploads "
            "item now from conversation history, caption, and filename. Prefer public "
            "or personal. Pending is a last resort.\n"
        )
    if user_text:
        human += f"\nuser_message:\n{user_text}\n"

    messages: list[BaseMessage] = [
        SystemMessage(content=BROKER_SYSTEM_PROMPT),
        *_history_as_lc(history),
        HumanMessage(content=human),
    ]

    try:
        messages, final_text = await run_tool_loop(
            model,
            tools,
            messages,
            max_steps=settings.AGENT_MAX_TOOL_STEPS,
            session_id=ctx.session.id,
        )
    except Exception as exc:
        logger.warning("broker tool loop failed session=%s trigger=%s", ctx.session.id, ctx.trigger, exc_info=exc)
        final_text = (
            "I hit a problem while working this request. Please send that last "
            "message again in a moment."
        )

    if not ctx.current_user_messages:
        if not final_text or looks_like_process_dump(final_text):
            logger.debug(
                "using fallback reply session=%s process_dump=%s original=%s",
                ctx.session.id,
                bool(final_text) and looks_like_process_dump(final_text),
                clip(final_text, 200),
            )
            final_text = NATURAL_FALLBACK_REPLY
        assistant = AgentMessage(
            session_id=ctx.session.id,
            role="assistant",
            content=final_text,
        )
        ctx.db.add(assistant)
        await ctx.db.flush()
        ctx.track(assistant)

    logger.info(
        "broker turn complete session=%s trigger=%s replies=%s saved=%s indexed=%s searched=%s opened=%s reply=%s",
        ctx.session.id,
        ctx.trigger,
        len(ctx.current_user_messages),
        ctx.saved_this_turn,
        ctx.indexed_this_turn,
        ctx.searched_this_turn,
        ctx.opened_match_ids,
        clip(ctx.current_user_messages[-1].content if ctx.current_user_messages else "", 200),
    )
    return ctx.current_user_messages
