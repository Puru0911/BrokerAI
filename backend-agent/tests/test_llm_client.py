from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import settings
from app.llm.client import (
    STRUCTURED_INSTANCE_HINT,
    build_broker_chat_model,
    build_chat_model,
    groq_model_uses_reasoning,
    invoke_structured_model,
    invoke_text_model,
    openrouter_reasoning_config,
    parse_structured_output,
    required_instance_fields,
    structured_retry_instruction,
    unwrap_schema_echo,
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
    assert kwargs["model_kwargs"] == {"top_p": 0.8}
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
    assert kwargs["temperature"] == 0.3
    assert kwargs["model_kwargs"] == {"top_p": 0.8}
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
    assert kwargs["top_p"] == 0.8
    assert kwargs["openrouter_provider"] == {
        "order": ["deepinfra", "novita", "coreweave", "parasail"],
        "allow_fallbacks": True,
        "require_parameters": True,
    }
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
    assert kwargs["top_p"] == 0.8
    assert kwargs["openrouter_provider"]["order"][0] == "deepinfra"


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
    assert kwargs["top_p"] == 0.8


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
    human = fake.ainvoke.await_args.args[0][1].content
    assert STRUCTURED_INSTANCE_HINT in human
    assert "The output should be formatted as a JSON instance" not in human
    assert "format_instructions" not in human.lower()


@pytest.mark.asyncio
async def test_invoke_structured_model_can_skip_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openrouter")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(settings, "LLM_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
    monkeypatch.setattr(settings, "OPENROUTER_REASONING_ENABLED", True)

    from pydantic import BaseModel, Field

    class Copy(BaseModel):
        title: str = Field(min_length=1)
        summary: str = Field(min_length=1)

    fake = MagicMock()
    fake.bind.return_value = fake
    fake.ainvoke = AsyncMock(
        return_value=MagicMock(
            content='{"title": "1BHK in Baner", "summary": "Looking for a 1BHK in Baner."}'
        )
    )
    with patch("app.llm.client.ChatOpenRouter", return_value=fake) as openrouter_cls:
        copy = await invoke_structured_model(
            parser_model=Copy,
            system_prompt="Return JSON.",
            human_payload={"objective": "1BHK Baner"},
            temperature=0.1,
            max_tokens=400,
            use_reasoning=False,
        )

    assert copy.title == "1BHK in Baner"
    kwargs = openrouter_cls.call_args.kwargs
    assert "reasoning" not in kwargs
    assert kwargs["top_p"] == 0.8
    assert kwargs["max_tokens"] == 400


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
    assert kwargs["top_p"] == 0.8


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
    assert kwargs["temperature"] == 0.3
    assert kwargs["top_p"] == 0.8
    assert kwargs["max_tokens"] == 2048
    assert kwargs["reasoning"]["effort"] == "medium"
    assert kwargs["openrouter_provider"]["allow_fallbacks"] is True


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


def test_unwrap_schema_echo_lifts_const_values() -> None:
    payload = {
        "properties": {
            "verdict": {"const": "no_match", "title": "Verdict", "type": "string"},
            "score": {"const": 5, "title": "Score", "type": "integer"},
            "matched": ["Both in the same domain"],
            "recommended_action": "skip",
            "rationale": "Same-side pair.",
            "negotiation_room": False,
        }
    }
    lifted = unwrap_schema_echo(payload)
    assert lifted["verdict"] == "no_match"
    assert lifted["score"] == 5
    assert lifted["recommended_action"] == "skip"
    assert lifted["matched"] == ["Both in the same domain"]
    assert "properties" not in lifted


def test_parse_structured_output_salvages_schema_echo() -> None:
    from app.services.evaluate import PairEvaluation

    raw = json.dumps(
        {
            "properties": {
                "verdict": {"const": "no_match", "title": "Verdict", "type": "string"},
                "score": {"const": 5, "title": "Score", "type": "integer"},
                "matched": ["Both professionals"],
                "mismatched": [],
                "missing_info": [],
                "risk_flags": [],
                "negotiation_room": False,
                "recommended_action": "skip",
                "clarifying_question": "",
                "clarifying_questions": [],
                "next_questions": [],
                "rationale": "Same-side pair.",
                "source_relative_brief": "",
            }
        }
    )
    evaluation = parse_structured_output(PairEvaluation, raw)
    assert evaluation.verdict == "no_match"
    assert evaluation.score == 5
    assert evaluation.recommended_action == "skip"


def test_parse_structured_output_rejects_pure_schema() -> None:
    from app.services.evaluate import PairEvaluation

    raw = json.dumps(
        {
            "properties": {
                "verdict": {
                    "title": "Verdict",
                    "type": "string",
                    "enum": ["strong_match", "possible_match", "weak_match", "no_match"],
                },
                "score": {"title": "Score", "type": "integer"},
                "recommended_action": {
                    "title": "Recommended Action",
                    "enum": ["open_match", "skip"],
                    "type": "string",
                },
            },
            "required": ["verdict", "score", "recommended_action"],
        }
    )
    with pytest.raises(ValueError, match="Failed to parse PairEvaluation"):
        parse_structured_output(PairEvaluation, raw)


def test_parse_structured_output_keeps_a_filled_instance() -> None:
    from app.services.evaluate import PairEvaluation

    evaluation = parse_structured_output(
        PairEvaluation,
        json.dumps(
            {
                "verdict": "possible_match",
                "score": 70,
                "recommended_action": "ask_clarifying_question",
                "clarifying_question": "Can you relocate?",
            }
        ),
    )
    assert evaluation.verdict == "possible_match"
    assert evaluation.clarifying_question == "Can you relocate?"


def test_required_instance_fields_lists_pair_keys() -> None:
    from app.services.evaluate import PairEvaluation

    required = required_instance_fields(PairEvaluation)
    assert "verdict" in required
    assert "score" in required
    assert "recommended_action" in required


def test_structured_retry_instruction_includes_output_error_and_keys() -> None:
    from app.services.evaluate import PairEvaluation

    instruction = structured_retry_instruction(
        PairEvaluation,
        "{}",
        ValueError(
            "Failed to parse PairEvaluation from completion {}. Got: 3 validation errors"
        ),
    )
    assert "Previous output:" in instruction
    assert "{}" in instruction
    assert "3 validation errors" in instruction
    assert "Required keys: verdict, score, recommended_action." in instruction
    assert "Do not return a JSON Schema." in instruction


@pytest.mark.asyncio
async def test_invoke_structured_model_retries_parse_with_correction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openrouter")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(settings, "LLM_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
    monkeypatch.setattr(settings, "OPENROUTER_REASONING_ENABLED", True)

    from pydantic import BaseModel, Field

    class Plan(BaseModel):
        query_text: str = Field(min_length=20)

    fake = MagicMock()
    fake.bind.return_value = fake
    fake.ainvoke = AsyncMock(
        side_effect=[
            MagicMock(content="{}"),
            MagicMock(
                content='{"query_text": "A woman in Mumbai looking for casual dating nearby."}'
            ),
        ]
    )
    with patch("app.llm.client.ChatOpenRouter", return_value=fake):
        plan = await invoke_structured_model(
            parser_model=Plan,
            system_prompt="Return JSON.",
            human_payload={"objective": "date"},
            temperature=0.1,
        )

    assert "Mumbai" in plan.query_text
    assert fake.ainvoke.await_count == 2
    first = fake.ainvoke.await_args_list[0].args[0][1].content
    second = fake.ainvoke.await_args_list[1].args[0][1].content
    assert STRUCTURED_INSTANCE_HINT in first
    assert "Previous output:" not in first
    assert "Previous output:" in second
    assert "Required keys: query_text." in second
    assert "Failed to parse Plan" in second


@pytest.mark.asyncio
async def test_invoke_structured_model_does_not_retry_provider_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openrouter")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(settings, "LLM_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
    monkeypatch.setattr(settings, "OPENROUTER_REASONING_ENABLED", False)

    from pydantic import BaseModel

    class Plan(BaseModel):
        query_text: str

    fake = MagicMock()
    fake.bind.return_value = fake
    fake.ainvoke = AsyncMock(side_effect=RuntimeError("provider unavailable"))
    with (
        patch("app.llm.client.ChatOpenRouter", return_value=fake),
        pytest.raises(RuntimeError, match="provider unavailable"),
    ):
        await invoke_structured_model(
            parser_model=Plan,
            system_prompt="Return JSON.",
            human_payload={"objective": "date"},
            temperature=0.1,
        )
    assert fake.ainvoke.await_count == 1


@pytest.mark.asyncio
async def test_invoke_structured_model_reraises_after_two_parse_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openrouter")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(settings, "LLM_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
    monkeypatch.setattr(settings, "OPENROUTER_REASONING_ENABLED", False)

    from pydantic import BaseModel, Field

    class Plan(BaseModel):
        query_text: str = Field(min_length=20)

    fake = MagicMock()
    fake.bind.return_value = fake
    fake.ainvoke = AsyncMock(return_value=MagicMock(content="{}"))
    with (
        patch("app.llm.client.ChatOpenRouter", return_value=fake),
        pytest.raises(ValueError, match="Failed to parse Plan"),
    ):
        await invoke_structured_model(
            parser_model=Plan,
            system_prompt="Return JSON.",
            human_payload={"objective": "date"},
            temperature=0.1,
        )
    assert fake.ainvoke.await_count == 2
