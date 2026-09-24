from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from langchain_openrouter import ChatOpenRouter
from pydantic import BaseModel

from app.core.config import settings

# Groq reasoning models emit native XML tool calls inside the think stream unless
# reasoning_format=parsed splits thinking into message.reasoning and tools into
# JSON tool_calls. ChatOpenAI does not send that Groq field.
_GROQ_REASONING_MARKERS = ("qwen/", "qwen3", "gpt-oss", "minimax")


@dataclass(frozen=True)
class LLMRuntimeConfig:
    provider: str
    model: str
    base_url: str
    api_key: str | None
    default_headers: dict[str, str] | None = None


def resolve_llm_runtime_config() -> LLMRuntimeConfig:
    provider = settings.LLM_PROVIDER.strip().lower()
    if provider == "gemini":
        return LLMRuntimeConfig(
            provider="gemini",
            model=settings.GEMINI_LLM_MODEL,
            base_url=settings.GEMINI_BASE_URL.rstrip("/"),
            api_key=settings.GEMINI_API_KEY,
        )
    if provider == "groq":
        return LLMRuntimeConfig(
            provider="groq",
            model=settings.GROQ_LLM_MODEL,
            base_url=settings.GROQ_BASE_URL.rstrip("/"),
            api_key=settings.GROQ_API_KEY,
        )
    if provider == "openrouter":
        return LLMRuntimeConfig(
            provider="openrouter",
            model=settings.LLM_MODEL,
            base_url=settings.OPENROUTER_BASE_URL.rstrip("/"),
            api_key=settings.OPENROUTER_API_KEY,
            default_headers={
                "HTTP-Referer": settings.public_app_url,
                "X-Title": settings.APP_NAME,
            },
        )
    return LLMRuntimeConfig(
        provider=provider or "unknown",
        model="",
        base_url="",
        api_key=None,
    )


def is_llm_configured() -> bool:
    runtime_config = resolve_llm_runtime_config()
    return bool(runtime_config.api_key and runtime_config.model and runtime_config.base_url)


def llm_configuration_error() -> str:
    provider = settings.LLM_PROVIDER.strip().lower()
    if provider == "gemini":
        return "GEMINI_API_KEY is not configured"
    if provider == "groq":
        return "GROQ_API_KEY is not configured"
    if provider == "openrouter":
        return "OPENROUTER_API_KEY is not configured"
    return f"Unsupported LLM_PROVIDER '{settings.LLM_PROVIDER}'"


def llm_runtime_info() -> dict[str, str]:
    runtime_config = resolve_llm_runtime_config()
    return {
        "provider": runtime_config.provider,
        "model": runtime_config.model,
    }


def groq_model_uses_reasoning(model: str) -> bool:
    """True when Groq needs reasoning_format to keep tool calls as JSON."""
    lowered = model.strip().lower()
    return any(marker in lowered for marker in _GROQ_REASONING_MARKERS)


def openrouter_reasoning_config() -> dict[str, Any] | None:
    """OpenRouter reasoning object, or None when the toggle is off."""
    if not settings.OPENROUTER_REASONING_ENABLED:
        return None
    effort = (settings.OPENROUTER_REASONING_EFFORT or "medium").strip().lower()
    return {
        "enabled": True,
        "effort": effort,
        "exclude": bool(settings.OPENROUTER_REASONING_EXCLUDE),
    }


def build_chat_model(
    *,
    temperature: float,
    max_tokens: int = 1200,
    use_reasoning: bool = True,
) -> BaseChatModel:
    if not is_llm_configured():
        raise RuntimeError(llm_configuration_error())

    runtime_config = resolve_llm_runtime_config()
    if runtime_config.provider == "groq":
        return _build_groq_chat_model(
            model=runtime_config.model,
            api_key=runtime_config.api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            use_reasoning=use_reasoning,
        )
    if runtime_config.provider == "openrouter":
        return _build_openrouter_chat_model(
            model=runtime_config.model,
            api_key=runtime_config.api_key,
            base_url=runtime_config.base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            use_reasoning=use_reasoning,
        )

    return ChatOpenAI(
        api_key=runtime_config.api_key,
        base_url=runtime_config.base_url,
        model=runtime_config.model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS,
        default_headers=runtime_config.default_headers,
    )


def build_broker_chat_model() -> BaseChatModel:
    """Chat model for the broker bind_tools loop."""
    provider = resolve_llm_runtime_config().provider
    if provider == "groq":
        return build_chat_model(
            temperature=1.0,
            max_tokens=settings.GROQ_MAX_COMPLETION_TOKENS,
        )
    if provider == "openrouter" and openrouter_reasoning_config() is not None:
        return build_chat_model(temperature=1.0, max_tokens=2048)
    return build_chat_model(temperature=0.35, max_tokens=4096)


def _build_groq_chat_model(
    *,
    model: str,
    api_key: str | None,
    temperature: float,
    max_tokens: int,
    use_reasoning: bool = True,
) -> ChatGroq:
    """Use ChatGroq so Groq returns JSON tool_calls instead of Qwen XML."""
    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": api_key,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "timeout": settings.LLM_REQUEST_TIMEOUT_SECONDS,
        "max_retries": 2,
    }
    if use_reasoning and groq_model_uses_reasoning(model):
        effort = (settings.GROQ_REASONING_EFFORT or "low").strip().lower()
        kwargs["max_tokens"] = min(max_tokens, settings.GROQ_MAX_COMPLETION_TOKENS)
        kwargs["reasoning_format"] = "parsed"
        kwargs["reasoning_effort"] = effort
        if effort != "none":
            kwargs["model_kwargs"] = {"top_p": 0.95}
    return ChatGroq(**kwargs)


def _build_openrouter_chat_model(
    *,
    model: str,
    api_key: str | None,
    base_url: str,
    temperature: float,
    max_tokens: int,
    use_reasoning: bool = True,
) -> ChatOpenRouter:
    """Use ChatOpenRouter so reasoning tokens stay out of tool JSON / content."""
    reasoning = openrouter_reasoning_config() if use_reasoning else None
    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "temperature": temperature,
        "max_tokens": max_tokens,
        # ChatOpenRouter.timeout is milliseconds (SDK timeout_ms).
        "timeout": int(settings.LLM_REQUEST_TIMEOUT_SECONDS * 1000),
        "max_retries": 2,
        "app_url": settings.public_app_url,
        "app_title": settings.APP_NAME,
    }
    if reasoning is not None:
        # Full OpenRouter object (enabled/effort/exclude). The SDK currently
        # serializes effort/summary; omit this dict entirely when the toggle is off.
        kwargs["reasoning"] = reasoning
        kwargs["top_p"] = 0.95
    return ChatOpenRouter(**kwargs)


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


async def invoke_text_model(
    system_prompt: str,
    human_payload: dict[str, Any],
    temperature: float,
    max_tokens: int = 800,
) -> str:
    """Call the chat model and return plain text (no JSON contract).

    Reasoning is off: index profile generation does not need a thinking budget,
    and sending one on free OpenRouter models has overloaded the upstream.
    """
    if not is_llm_configured():
        raise RuntimeError(llm_configuration_error())

    llm = build_chat_model(
        temperature=temperature,
        max_tokens=max_tokens,
        use_reasoning=False,
    )
    result = await llm.ainvoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(
                content=(
                    "INPUT:\n"
                    f"{json.dumps(human_payload, ensure_ascii=False)}\n\n"
                    "Output only the requested document."
                )
            ),
        ]
    )
    content = result.content if hasattr(result, "content") else str(result)
    if isinstance(content, list):
        content = "\n".join(
            block if isinstance(block, str) else str(block.get("text") or "")
            for block in content
        )
    return _strip_fences(str(content or ""))


async def invoke_structured_model(
    parser_model: type[BaseModel],
    system_prompt: str,
    human_payload: dict[str, Any],
    temperature: float,
) -> Any:
    """Call the chat model with a strict JSON / Pydantic contract."""
    if not is_llm_configured():
        raise RuntimeError(llm_configuration_error())

    parser = PydanticOutputParser(pydantic_object=parser_model)
    llm = build_chat_model(temperature=temperature, max_tokens=2000).bind(
        response_format={"type": "json_object"}
    )
    result = await llm.ainvoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(
                content=(
                    "Context packet:\n"
                    f"{json.dumps(human_payload, ensure_ascii=False)}\n\n"
                    "Return JSON that matches the schema exactly:\n"
                    f"{parser.get_format_instructions()}"
                )
            ),
        ]
    )
    content = result.content if hasattr(result, "content") else str(result)
    if isinstance(content, list):
        content = "\n".join(
            block if isinstance(block, str) else str(block.get("text") or "")
            for block in content
        )
    return parser.parse(_strip_fences(str(content or "")))
