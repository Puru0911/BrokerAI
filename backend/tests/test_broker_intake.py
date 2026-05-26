from app.services.broker_orchestrator import _decision_title_or_fallback


def test_placeholder_decision_title_keeps_request_title_fallback() -> None:
    assert (
        _decision_title_or_fallback(
            "New broker request",
            "I'm looking for a girl to date",
        )
        == "I'm looking for a girl to date"
    )
