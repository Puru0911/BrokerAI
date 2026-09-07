from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.core.config import settings
from app.llm.client import (
    build_broker_chat_model,
    build_chat_model,
    groq_model_uses_reasoning,
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


def test_build_chat_model_openrouter_still_uses_chat_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openrouter")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(settings, "LLM_MODEL", "deepseek/deepseek-chat-v3-0324")
    monkeypatch.setattr(settings, "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

    fake = MagicMock()
    with (
        patch("app.llm.client.ChatOpenAI", return_value=fake) as openai_cls,
        patch("app.llm.client.ChatGroq") as groq_cls,
    ):
        model = build_chat_model(temperature=0.35, max_tokens=1200)

    assert model is fake
    groq_cls.assert_not_called()
    assert openai_cls.call_args.kwargs["model"] == "deepseek/deepseek-chat-v3-0324"
    assert "reasoning_format" not in openai_cls.call_args.kwargs
