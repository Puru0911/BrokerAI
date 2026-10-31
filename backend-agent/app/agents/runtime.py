from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool

from app.agents.context import (
    ToolContext,
    build_context_packet,
    focused_match_id,
    load_session_history,
    reply_lane_id,
)
from app.agents.prompts import (
    BROKER_SYSTEM_PROMPT,
    MATCH_CONTEXT_INSTRUCTION,
    MATCH_TIMEOUT_INSTRUCTION,
    NATURAL_FALLBACK_REPLY,
    REQUEST_LANE_OPENED_MATCH_REPLY,
    REQUEST_LANE_OPENED_MATCHES_REPLY,
    REQUEST_READY_INSTRUCTION,
    UNAVAILABLE_REPLY,
    USER_MESSAGE_INSTRUCTION,
)
from app.agents.tool_call_repair import repair_tool_message
from app.agents.tools.registry import build_broker_tools
from app.core.config import settings
from app.core.logging import clip
from app.db.models import AgentMessage
from app.db.models.broker import utc_now
from app.llm.client import build_broker_chat_model, is_llm_configured, llm_runtime_info

logger = logging.getLogger(__name__)


async def _persist_assistant_reply(
    ctx: ToolContext, text: str, *, match_id: str | None
) -> AgentMessage:
    message = AgentMessage(
        session_id=ctx.session.id,
        role="assistant",
        content=text,
        match_id=match_id,
    )
    ctx.db.add(message)
    await ctx.db.flush()
    ctx.track(message)
    return message


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
    "update_search_brief",
    "update_request_details",
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
    "offer_introduction",
    "share_contacts",
    "get_match_events",
    "get_match_brief",
    "answer_match_question",
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


# Short closer after a longer update in the same turn ("All set", "That's all for now").
_TRAILING_ACK_MAX = 120

_QUIET_RETRY_ACK_MARKERS = (
    "searching",
    "restarted",
    "still working",
    "started a new search",
    "looking again",
    "i'll look again",
    "i will look again",
)


def user_facing_reply_text(content: Any) -> str:
    """Ordinary assistant prose that should be shown. Empty when none or a process dump."""
    text = message_text(content)
    if not text or looks_like_process_dump(text):
        return ""
    return text


def _quiet_retry_turn(ctx: ToolContext) -> bool:
    job = ctx.background_job or {}
    return (
        ctx.trigger == "request_ready"
        and str(job.get("status") or "") == "failed"
        and bool(ctx.queued_jobs)
    )


def _is_quiet_retry_ack(text: str) -> bool:
    lowered = text.lower()
    if text == NATURAL_FALLBACK_REPLY:
        return True
    return len(text) <= 200 and any(marker in lowered for marker in _QUIET_RETRY_ACK_MARKERS)


def drop_quiet_retry_acks(ctx: ToolContext, replies: list[str]) -> list[str]:
    """Drop short process acks when a failed job already queued a retry."""
    if not _quiet_retry_turn(ctx):
        return replies
    kept = [text for text in replies if not _is_quiet_retry_ack(text)]
    if len(kept) != len(replies):
        ctx.suppress_empty_fallback = True
        logger.info(
            "dropped quiet retry ack session=%s dropped=%s kept=%s",
            ctx.session.id,
            len(replies) - len(kept),
            len(kept),
        )
    return kept


async def maybe_queue_clarify_followup(ctx: ToolContext) -> None:
    """After presenting Strong/Close fit cards, wake again to ask this person's questions."""
    if not ctx.presented_this_turn or ctx.request is None:
        return
    job = ctx.background_job or {}
    if job.get("kind") == "clarify":
        return
    from app.services.request_jobs import JOB_CLARIFY, JobRetryBlocked, enqueue_request_job
    from app.services.suggestions import all_pending_questions, list_suggestions

    rows = await list_suggestions(ctx.db, ctx.request.id)
    if not all_pending_questions(rows):
        return
    try:
        follow = await enqueue_request_job(
            ctx.db,
            kind=JOB_CLARIFY,
            request=ctx.request,
            session_id=ctx.session.id,
            user_id=ctx.profile.id,
            ctx=ctx,
        )
    except JobRetryBlocked:
        return
    ctx.queued_jobs.append(follow.id)
    logger.info(
        "clarify follow-up queued session=%s job_id=%s",
        ctx.session.id,
        follow.id,
    )


def collapse_turn_replies(texts: list[str]) -> list[str]:
    """Keep step updates; drop a short trailing ack once a longer reply exists."""
    out: list[str] = []
    for text in texts:
        if out and len(text) <= _TRAILING_ACK_MAX and len(text) < len(out[-1]):
            continue
        out.append(text)
    return out


def collect_turn_replies(messages: list[BaseMessage], *, start: int = 0) -> list[str]:
    """User-facing assistant content from this tool loop, including text sent with tool calls.

    `start` is the index where this turn's model steps begin. Earlier items are
    session history converted to LangChain messages and must not be saved again.
    """
    replies: list[str] = []
    for message in messages[start:]:
        if not isinstance(message, AIMessage):
            continue
        text = user_facing_reply_text(getattr(message, "content", ""))
        if text:
            replies.append(text)
    return collapse_turn_replies(replies)


def split_open_match_lane_replies(
    messages: list[BaseMessage], *, start: int = 0
) -> tuple[list[str], list[str]]:
    """Prose with or before open_match stays on Your request; later prose is the match tab."""
    request_texts: list[str] = []
    match_texts: list[str] = []
    opened = False
    for message in messages[start:]:
        if not isinstance(message, AIMessage):
            continue
        text = user_facing_reply_text(getattr(message, "content", ""))
        names = _tool_names(getattr(message, "tool_calls", None) or [])
        if "open_match" in names:
            if text:
                request_texts.append(text)
            opened = True
            continue
        if not text:
            continue
        if opened:
            match_texts.append(text)
        else:
            request_texts.append(text)
    return collapse_turn_replies(request_texts), collapse_turn_replies(match_texts)


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


def _text_from_reasoning_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "summary", "content", "thinking", "reasoning"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()
        return ""
    if isinstance(value, list):
        parts = [_text_from_reasoning_value(item) for item in value]
        return "\n".join(part for part in parts if part)
    return ""


def model_thinking_text(message: Any) -> str:
    """Model reasoning stream (OpenRouter/Groq), not the think tool."""
    parts: list[str] = []
    kwargs = getattr(message, "additional_kwargs", None) or {}
    for key in ("reasoning_content", "reasoning", "thinking"):
        text = _text_from_reasoning_value(kwargs.get(key))
        if text:
            parts.append(text)
    details = kwargs.get("reasoning_details")
    if details is not None:
        text = _text_from_reasoning_value(details)
        if text:
            parts.append(text)
    content = getattr(message, "content", None)
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") in {"reasoning", "thinking", "thought"}:
                text = _text_from_reasoning_value(block)
                if text:
                    parts.append(text)
    seen: set[str] = set()
    unique: list[str] = []
    for part in parts:
        if part not in seen:
            seen.add(part)
            unique.append(part)
    return "\n".join(unique).strip()


_STRUCTURED_HISTORY_LABELS = {
    "broker_candidate_cards": "[candidate cards shown]",
    "broker_candidate_card": "[candidate card shown]",
    "broker_contact_card": "[contact card shown]",
    "broker_connect_offer": "[introduction control shown]",
    "broker_attachment_request": "[upload request shown]",
    "broker_attachment_permission": "[share permission shown]",
    "broker_attachment_share": "[files shared]",
}


def history_visible_content(content: str | None) -> str:
    """Plain chat text for the model. Structured cards become placeholders."""
    text = (content or "").strip()
    if not text.startswith("{"):
        return text
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(payload, dict) and payload.get("kind"):
        kind = str(payload.get("kind") or "")
        return _STRUCTURED_HISTORY_LABELS.get(kind, "[card shown]")
    return text


def _history_as_lc(messages: list[AgentMessage]) -> list[BaseMessage]:
    converted: list[BaseMessage] = []
    for message in messages:
        if message.role == "user":
            converted.append(HumanMessage(content=history_visible_content(message.content)))
        elif message.role == "assistant":
            converted.append(AIMessage(content=history_visible_content(message.content)))
    return converted


def format_session_history_transcript(messages: list[AgentMessage]) -> str:
    """This person's earlier private thread, labeled so it cannot look like live turns."""
    if not messages:
        return ""
    lines: list[str] = []
    for message in messages:
        if message.role == "user":
            speaker = "user"
        elif message.role == "assistant":
            speaker = "broker"
        else:
            continue
        text = history_visible_content(message.content)
        if not text:
            continue
        lines.append(f"{speaker}: {text}")
    if not lines:
        return ""
    return (
        "this_session_earlier_chat (earlier messages in this private thread):\n"
        + "\n".join(lines)
    )


def inline_history_in_packet(trigger: str) -> bool:
    """True when session history must not compete with outreach as prior turns."""
    return trigger == "match_context"


def build_turn_human_content(
    packet: dict[str, Any],
    *,
    trigger_instruction: str,
    history: list[AgentMessage],
    inline_history: bool,
) -> str:
    """Assemble the current-turn packet. Outreach and new work sit above history."""
    parts = [
        f"TRIGGER: {packet.get('TRIGGER')}",
        f"LANE: {packet.get('LANE') or 'request'}",
    ]
    if packet.get("focus_match_id"):
        parts.append(f"focus_match_id: {packet.get('focus_match_id')}")
    parts.extend(
        [
            "",
            trigger_instruction,
            "",
        ]
    )
    outreach = packet.get("outreach_context")
    if outreach:
        parts.extend(
            [
                (
                    "outreach_context (why this turn exists; what this person needs "
                    "to hear or answer):"
                ),
                str(outreach),
                "",
            ]
        )
    parts.extend(
        [
            f"living_request:\n{json.dumps(packet.get('living_request'), ensure_ascii=False, default=str)}",
            "",
            f"open_matches:\n{json.dumps(packet.get('open_matches'), ensure_ascii=False, default=str)}",
            "",
            f"open_match_count: {packet.get('open_match_count', 0)}",
            "",
            f"suggested_matches:\n{json.dumps(packet.get('suggested_matches'), ensure_ascii=False, default=str)}",
            "",
            f"pending_questions:\n{json.dumps(packet.get('pending_questions') or [], ensure_ascii=False, default=str)}",
            "",
            f"background_job:\n{json.dumps(packet.get('background_job'), ensure_ascii=False, default=str)}",
            "",
            f"recent_events:\n{json.dumps(packet.get('recent_events'), ensure_ascii=False, default=str)}",
            "",
            f"attention_pointer: {packet.get('attention_pointer')}",
            "",
            "attachments (this person's files in this session):",
            json.dumps(packet.get("attachments"), ensure_ascii=False, default=str),
            "",
            "new_uploads (this person's new files this turn):",
            json.dumps(packet.get("new_uploads"), ensure_ascii=False, default=str),
        ]
    )
    user_text = packet.get("current_user_message")
    if user_text:
        parts.extend(["", f"user_message:\n{user_text}"])
    if inline_history:
        transcript = format_session_history_transcript(history)
        if transcript:
            parts.extend(["", transcript])
    return "\n".join(parts)


def _trigger_instruction(ctx: ToolContext) -> str:
    if ctx.trigger == "request_ready":
        return REQUEST_READY_INSTRUCTION
    if ctx.trigger == "match_timeout":
        return MATCH_TIMEOUT_INSTRUCTION
    if ctx.trigger == "match_context":
        return MATCH_CONTEXT_INSTRUCTION
    return USER_MESSAGE_INSTRUCTION


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
    "tool results already in this turn. Do not repeat a tool that already succeeded."
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


def tool_bind_kwargs(provider: str | None = None) -> dict[str, Any]:
    """Extra bind_tools kwargs that OpenRouter endpoints actually advertise.

    `parallel_tool_calls` is a distinct OpenRouter parameter. No qwen/qwen3.8-27b
    host (DeepInfra, Novita, CoreWeave, Parasail, or fallbacks) lists it. With
    `require_parameters: true` that 404s: "No endpoints found that can handle
    the requested parameters." Python still runs tool calls one at a time.
    """
    name = (provider or llm_runtime_info()["provider"]).strip().lower()
    if name == "openrouter":
        return {}
    return {"parallel_tool_calls": False}


def _tool_names(tool_calls: list[Any]) -> list[str]:
    names: list[str] = []
    for call in tool_calls:
        if isinstance(call, dict):
            names.append(str(call.get("name") or ""))
        else:
            names.append(str(getattr(call, "name", "") or ""))
    return names


def _call_signature(name: str, args: Any) -> str:
    """Skip key for this turn. Identical name+args is not run twice."""
    return json.dumps({"name": name, "args": args or {}}, sort_keys=True, default=str)


async def run_tool_loop(
    llm: Any,
    tools: list[BaseTool],
    messages: list[BaseMessage],
    *,
    max_steps: int,
    on_tool: Any | None = None,
    session_id: str | None = None,
) -> tuple[list[BaseMessage], str | None, list[str]]:
    """Run bind_tools until the model replies or the step budget is spent.

    The third value is user-facing prose from this loop only (tool-step content
    included). Session history already in `messages` is not part of that list.
    """
    tool_map = {tool.name: tool for tool in tools}
    if hasattr(llm, "bind_tools"):
        bound = llm.bind_tools(tools, **tool_bind_kwargs())
    else:
        bound = llm
    final_text: str | None = None
    seen_calls: set[str] = set()
    sid = session_id or "-"
    loop_start = len(messages)

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
        thinking = model_thinking_text(response)
        if thinking:
            logger.info(
                "model thinking session=%s step=%s thinking=%s",
                sid,
                step + 1,
                clip(thinking, 8000),
            )
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
            signature = _call_signature(str(name or ""), args)
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
                try:
                    result = await tool.ainvoke(args or {})
                except Exception as exc:  # noqa: BLE001
                    logger.warning("tool crashed session=%s tool=%s error=%s", sid, name, exc)
                    result = json.dumps({"ok": False, "error": str(exc)})
            latency_ms = round((time.perf_counter() - started) * 1000)
            status = _tool_status(result)
            if not skip_reason and status != "error":
                seen_calls.add(signature)
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

    return messages, final_text, collect_turn_replies(messages, start=loop_start)


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
            match_id=reply_lane_id(ctx),
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
        match_id=focused_match_id(ctx),
    )
    logger.debug(
        "broker context session=%s lane=%s focus=%s open_matches=%s attention=%s history=%s",
        ctx.session.id,
        packet.get("LANE"),
        packet.get("focus_match_id"),
        len(packet.get("open_matches") or []),
        packet.get("attention_pointer"),
        len(history),
    )
    inline_history = inline_history_in_packet(ctx.trigger)
    human = build_turn_human_content(
        packet,
        trigger_instruction=_trigger_instruction(ctx),
        history=history,
        inline_history=inline_history,
    )
    history_turns = [] if inline_history else _history_as_lc(history)
    messages: list[BaseMessage] = [
        SystemMessage(content=BROKER_SYSTEM_PROMPT),
        *history_turns,
        HumanMessage(content=human),
    ]

    prefix_len = len(messages)
    replies: list[str] = []
    try:
        messages, final_text, replies = await run_tool_loop(
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
        replies = collect_turn_replies(messages, start=prefix_len)
    if not replies:
        if not final_text or looks_like_process_dump(final_text):
            logger.debug(
                "using fallback reply session=%s process_dump=%s original=%s",
                ctx.session.id,
                bool(final_text) and looks_like_process_dump(final_text),
                clip(final_text, 200),
            )
            if not ctx.current_user_messages:
                replies = [NATURAL_FALLBACK_REPLY]
        else:
            replies = [final_text]
    replies = drop_quiet_retry_acks(ctx, replies)

    lane_id = focused_match_id(ctx)
    opened_from_request = reply_lane_id(ctx) is None and lane_id is not None
    if opened_from_request:
        request_texts, match_texts = split_open_match_lane_replies(
            messages, start=prefix_len
        )
        already_on_request = any(
            message.role == "assistant" and not message.match_id
            for message in ctx.current_user_messages
        )
        if not request_texts and not already_on_request:
            count = len(ctx.opened_match_ids) or 1
            request_texts = [
                REQUEST_LANE_OPENED_MATCHES_REPLY
                if count > 1
                else REQUEST_LANE_OPENED_MATCH_REPLY
            ]
        for text in request_texts:
            await _persist_assistant_reply(ctx, text, match_id=None)
        for text in match_texts:
            await _persist_assistant_reply(ctx, text, match_id=lane_id)
    else:
        for text in replies:
            await _persist_assistant_reply(ctx, text, match_id=lane_id)
    await maybe_queue_clarify_followup(ctx)
    ctx.session.updated_at = utc_now()

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
