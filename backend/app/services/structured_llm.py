from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.core.config import settings


@dataclass(frozen=True)
class LLMRuntimeConfig:
    """Resolved OpenAI-compatible chat model settings for the active provider."""

    provider: str
    model: str
    base_url: str
    api_key: str | None
    default_headers: dict[str, str] | None = None


def resolve_llm_runtime_config() -> LLMRuntimeConfig:
    """Return the active provider's OpenAI-compatible runtime config."""
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
                "HTTP-Referer": "http://localhost:3000",
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
    """Return whether the selected LLM provider has enough config to run."""
    runtime_config = resolve_llm_runtime_config()
    return bool(runtime_config.api_key and runtime_config.model and runtime_config.base_url)


def llm_configuration_error() -> str:
    """Return a human-readable configuration error for the selected provider."""
    provider = settings.LLM_PROVIDER.strip().lower()
    if provider == "gemini":
        return "GEMINI_API_KEY is not configured"
    if provider == "groq":
        return "GROQ_API_KEY is not configured"
    if provider == "openrouter":
        return "OPENROUTER_API_KEY is not configured"
    return f"Unsupported LLM_PROVIDER '{settings.LLM_PROVIDER}'"


def llm_audit_info() -> dict[str, str]:
    """Return non-secret provider details for logs and audit records."""
    runtime_config = resolve_llm_runtime_config()
    return {
        "provider": runtime_config.provider,
        "model": runtime_config.model,
    }


async def invoke_structured_openrouter_model(
    parser_model: type[BaseModel],
    system_prompt: str,
    human_payload: dict[str, Any],
    temperature: float,
) -> Any:
    """Invoke the configured OpenAI-compatible chat model with a Pydantic JSON contract."""
    if not is_llm_configured():
        raise RuntimeError(llm_configuration_error())

    runtime_config = resolve_llm_runtime_config()
    parser = PydanticOutputParser(pydantic_object=parser_model)
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            (
                "human",
                (
                    "Context packet:\n{context}\n\n"
                    "Return JSON that matches the schema exactly:\n"
                    "{format_instructions}"
                ),
            ),
        ]
    )
    llm = ChatOpenAI(
        api_key=runtime_config.api_key,
        base_url=runtime_config.base_url,
        model=runtime_config.model,
        temperature=temperature,
        timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS,
        default_headers=runtime_config.default_headers,
    ).bind(response_format={"type": "json_object"})
    chain = prompt | llm | parser
    return await chain.ainvoke(
        {
            "context": json.dumps(human_payload, ensure_ascii=False),
            "format_instructions": parser.get_format_instructions(),
        }
    )
