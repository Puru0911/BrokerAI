from unittest.mock import AsyncMock, patch

import pytest

from app.services.titles import (
    create_summary,
    create_title,
    generate_request_copy,
    welcome_message,
)


def test_create_title_truncates_long_requests() -> None:
    title = create_title("I need a designer " * 20)
    assert title.endswith("...")
    assert len(title) <= 76


def test_create_title_falls_back_when_empty() -> None:
    assert create_title(None) == "New broker request"
    assert create_title("   ") == "New broker request"


def test_create_summary_compacts_whitespace() -> None:
    assert create_summary("Need   a\nflat") == "Need a flat"


def test_welcome_message_uses_agent_name() -> None:
    assert welcome_message("BrokerAI") == (
        "Hi! I'm BrokerAI. Tell me what you're looking for and I'll find you the right people"
    )
    assert welcome_message("Ava") == (
        "Hi! I'm Ava. Tell me what you're looking for and I'll find you the right people"
    )


def test_welcome_message_reads_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "AGENT_NAME", "Nova")
    assert "Nova" in welcome_message()
    assert welcome_message().startswith("Hi! I'm Nova.")


@pytest.mark.asyncio
async def test_generate_request_copy_uses_llm() -> None:
    details = {
        "objective": "Need a 1BHK in Baner under 25k, from next month",
        "location": "Baner, Pune",
        "budget": "25000",
        "domain": "housing",
    }
    fake = AsyncMock(return_value=type("Copy", (), {
        "title": "1BHK Rental in Baner",
        "summary": "Looking for a 1BHK in Baner, Pune under 25k from next month.",
    })())
    with patch("app.services.titles.is_llm_configured", return_value=True), patch(
        "app.services.titles.invoke_structured_model", fake
    ):
        title, summary = await generate_request_copy(details)
    assert title == "1BHK Rental in Baner"
    assert "Baner" in summary
    fake.assert_awaited_once()
    kwargs = fake.await_args.kwargs
    assert kwargs["use_reasoning"] is False
    assert kwargs["max_tokens"] == 400
    assert kwargs["human_payload"]["objective"].startswith("Need a 1BHK")


@pytest.mark.asyncio
async def test_generate_request_copy_falls_back_when_llm_fails() -> None:
    details = {"objective": "Need a designer in Pune for a two-week sprint"}
    with patch("app.services.titles.is_llm_configured", return_value=True), patch(
        "app.services.titles.invoke_structured_model",
        AsyncMock(side_effect=RuntimeError("upstream")),
    ):
        title, summary = await generate_request_copy(details)
    assert title == create_title(details["objective"])
    assert summary == create_summary(details["objective"])


@pytest.mark.asyncio
async def test_generate_request_copy_skips_llm_without_objective() -> None:
    with patch("app.services.titles.is_llm_configured", return_value=True), patch(
        "app.services.titles.invoke_structured_model", AsyncMock()
    ) as fake:
        title, summary = await generate_request_copy({})
    assert title == "New broker request"
    assert summary == ""
    fake.assert_not_called()
