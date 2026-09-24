from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import settings
from app.llm.client import (
    build_broker_chat_model,
    build_chat_model,
    groq_model_uses_reasoning,
    invoke_structured_model,
    invoke_text_model,
    openrouter_reasoning_config,
)


def test_groq_qwen_is_a_reasoning_model() -> None:
    assert groq_model_uses_reasoning("qwen/qwen3.8-27b")
    assert groq_model_uses_reasoning("qwen/qwen3.6-27b")
    assert not groq_model_uses_reasoning("llama-3.3-70b-versatile")


def test_build_chat_model_uses_chatgroq_with_parsed_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk_test")
    monkeypatch.setattr(settings, "GROQ_LLM_MODEL", "qwen/qwen3.8-27b")
    monkeypatch.setattr(settings, "GROQ_REASONING_EFFORT", "low")
    monkeypatch.setattr(settings, "GROQ_MAX_COMPLETION_TOKENS", 2048)
    monkeypatch.setattr(settings, "LLM_REQUEST_TIMEOUT_SECONDS", 30.0)

    fake = MagicMock()
    with patch("app.llm.client.ChatGroq", return_value=fake) as mock_cls:
        model = build_chat_model(temperature=0.35, max_tokens=4096)

    assert model is fake
    kwargs = mock_cls.call_args.kwargs
    assert kwargs["model"] == "qwen/qwen3.8-27b"
    assert kwargs["reasoning_format"] == "parsed"
    assert kwargs["reasoning_effort"] == "low"
    assert kwargs["max_tokens"] == 2048
    assert kwargs["model_kwargs"] == {"top_p": 0.95}
    assert "base_url" not in kwargs


def test_build_chat_model_groq_llama_skips_reasoning_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk_test")
    monkeypatch.setattr(settings, "GROQ_LLM_MODEL", "llama-3.3-70b-versatile")

    with patch("app.llm.client.ChatGroq") as mock_cls:
        mock_cls.return_value = MagicMock()
        build_chat_model(temperature=0.35, max_tokens=1200)

    kwargs = mock_cls.call_args.kwargs
    assert kwargs["model"] == "llama-3.3-70b-versatile"
    assert "reasoning_format" not in kwargs
    assert "reasoning_effort" not in kwargs


def test_build_broker_chat_model_uses_thinking_sampling_on_groq(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk_test")
    monkeypatch.setattr(settings, "GROQ_LLM_MODEL", "qwen/qwen3.8-27b")
    monkeypatch.setattr(settings, "GROQ_REASONING_EFFORT", "low")
    monkeypatch.setattr(settings, "GROQ_MAX_COMPLETION_TOKENS", 2048)

    with patch("app.llm.client.ChatGroq") as mock_cls:
        mock_cls.return_value = MagicMock()
        build_broker_chat_model()

    kwargs = mock_cls.call_args.kwargs
    assert kwargs["temperature"] == 1.0
    assert kwargs["reasoning_format"] == "parsed"
    assert kwargs["reasoning_effort"] == "low"


def test_openrouter_reasoning_config_follows_toggle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "OPENROUTER_REASONING_ENABLED", True)
    monkeypatch.setattr(settings, "OPENROUTER_REASONING_EFFORT", "medium")
    monkeypatch.setattr(settings, "OPENROUTER_REASONING_EXCLUDE", False)
    assert openrouter_reasoning_config() == {
        "enabled": True,
        "effort": "medium",
        "exclude": False,
    }

    monkeypatch.setattr(settings, "OPENROUTER_REASONING_ENABLED", False)
    assert openrouter_reasoning_config() is None


def test_build_chat_model_openrouter_uses_chat_openrouter_with_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openrouter")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(settings, "LLM_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
    monkeypatch.setattr(settings, "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(settings, "OPENROUTER_REASONING_ENABLED", True)
    monkeypatch.setattr(settings, "OPENROUTER_REASONING_EFFORT", "medium")
    monkeypatch.setattr(settings, "OPENROUTER_REASONING_EXCLUDE", False)
    monkeypatch.setattr(settings, "LLM_REQUEST_TIMEOUT_SECONDS", 60.0)
    monkeypatch.setattr(settings, "APP_NAME", "BrokerAI")

    fake = MagicMock()
    with (
        patch("app.llm.client.ChatOpenRouter", return_value=fake) as openrouter_cls,
        patch("app.llm.client.ChatOpenAI") as openai_cls,
        patch("app.llm.client.ChatGroq") as groq_cls,
    ):
        model = build_chat_model(temperature=0.35, max_tokens=1200)

    assert model is fake
    groq_cls.assert_not_called()
    openai_cls.assert_not_called()
    kwargs = openrouter_cls.call_args.kwargs
    assert kwargs["model"] == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert kwargs["reasoning"] == {
        "enabled": True,
        "effort": "medium",
        "exclude": False,
    }
    assert kwargs["timeout"] == 60_000
    assert kwargs["top_p"] == 0.95
    assert kwargs["app_title"] == "BrokerAI"
    assert kwargs["app_url"] == settings.public_app_url
    assert "reasoning_format" not in kwargs


def test_build_chat_model_openrouter_can_omit_reasoning_per_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openrouter")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(settings, "LLM_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
    monkeypatch.setattr(settings, "OPENROUTER_REASONING_ENABLED", True)
    monkeypatch.setattr(settings, "OPENROUTER_REASONING_EFFORT", "medium")

    with patch("app.llm.client.ChatOpenRouter") as openrouter_cls:
        openrouter_cls.return_value = MagicMock()
        build_chat_model(temperature=0.1, max_tokens=800, use_reasoning=False)

    kwargs = openrouter_cls.call_args.kwargs
    assert "reasoning" not in kwargs
    assert "top_p" not in kwargs


def test_build_chat_model_groq_can_omit_reasoning_per_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk_test")
    monkeypatch.setattr(settings, "GROQ_LLM_MODEL", "qwen/qwen3.8-27b")

    with patch("app.llm.client.ChatGroq") as groq_cls:
        groq_cls.return_value = MagicMock()
        build_chat_model(temperature=0.1, max_tokens=800, use_reasoning=False)

    kwargs = groq_cls.call_args.kwargs
    assert "reasoning_format" not in kwargs
    assert "reasoning_effort" not in kwargs


@pytest.mark.asyncio
async def test_invoke_text_model_disables_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openrouter")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(settings, "LLM_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
    monkeypatch.setattr(settings, "OPENROUTER_REASONING_ENABLED", True)

    fake = MagicMock()
    fake.ainvoke = AsyncMock(return_value=MagicMock(content="DOMAIN: dating\nLOOKING FOR: a match"))
    with patch("app.llm.client.ChatOpenRouter", return_value=fake) as openrouter_cls:
        text = await invoke_text_model(
            system_prompt="Write a profile.",
            human_payload={"objective": "date"},
            temperature=0.1,
        )

    assert "LOOKING FOR" in text
    kwargs = openrouter_cls.call_args.kwargs
    assert "reasoning" not in kwargs
    assert "top_p" not in kwargs


@pytest.mark.asyncio
async def test_invoke_structured_model_keeps_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openrouter")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(settings, "LLM_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
    monkeypatch.setattr(settings, "OPENROUTER_REASONING_ENABLED", True)
    monkeypatch.setattr(settings, "OPENROUTER_REASONING_EFFORT", "medium")
    monkeypatch.setattr(settings, "OPENROUTER_REASONING_EXCLUDE", False)

    from pydantic import BaseModel, Field

    class Plan(BaseModel):
        query_text: str = Field(min_length=20)

    fake = MagicMock()
    fake.bind.return_value = fake
    fake.ainvoke = AsyncMock(
        return_value=MagicMock(
            content='{"query_text": "A woman in Mumbai looking for casual dating nearby."}'
        )
    )
    with patch("app.llm.client.ChatOpenRouter", return_value=fake) as openrouter_cls:
        plan = await invoke_structured_model(
            parser_model=Plan,
            system_prompt="Return JSON.",
            human_payload={"objective": "date"},
            temperature=0.1,
        )

    assert "Mumbai" in plan.query_text
    kwargs = openrouter_cls.call_args.kwargs
    assert kwargs["reasoning"]["effort"] == "medium"


def test_build_chat_model_openrouter_omits_reasoning_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openrouter")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(settings, "LLM_MODEL", "deepseek/deepseek-chat-v3-0324")
    monkeypatch.setattr(settings, "OPENROUTER_REASONING_ENABLED", False)

    with patch("app.llm.client.ChatOpenRouter") as openrouter_cls:
        openrouter_cls.return_value = MagicMock()
        build_chat_model(temperature=0.35, max_tokens=1200)

    kwargs = openrouter_cls.call_args.kwargs
    assert kwargs["model"] == "deepseek/deepseek-chat-v3-0324"
    assert "reasoning" not in kwargs
    assert "top_p" not in kwargs


def test_build_broker_chat_model_uses_thinking_sampling_on_openrouter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openrouter")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(settings, "LLM_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
    monkeypatch.setattr(settings, "OPENROUTER_REASONING_ENABLED", True)
    monkeypatch.setattr(settings, "OPENROUTER_REASONING_EFFORT", "medium")

    with patch("app.llm.client.ChatOpenRouter") as openrouter_cls:
        openrouter_cls.return_value = MagicMock()
        build_broker_chat_model()

    kwargs = openrouter_cls.call_args.kwargs
    assert kwargs["temperature"] == 1.0
    assert kwargs["max_tokens"] == 4096
    assert kwargs["reasoning"]["effort"] == "medium"


def test_build_chat_model_gemini_still_uses_chat_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "gemini-test")
    monkeypatch.setattr(settings, "GEMINI_LLM_MODEL", "gemini-2.5-flash")
    monkeypatch.setattr(
        settings, "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"
    )

    fake = MagicMock()
    with (
        patch("app.llm.client.ChatOpenAI", return_value=fake) as openai_cls,
        patch("app.llm.client.ChatOpenRouter") as openrouter_cls,
        patch("app.llm.client.ChatGroq") as groq_cls,
    ):
        model = build_chat_model(temperature=0.35, max_tokens=1200)

    assert model is fake
    groq_cls.assert_not_called()
    openrouter_cls.assert_not_called()
    assert openai_cls.call_args.kwargs["model"] == "gemini-2.5-flash"
