from app.db.models import AgentRequest
from app.services.privacy import anonymized_request, json_result, public_details, redact_identity


def test_redact_identity_hides_email_phone_and_handle() -> None:
    text = "Call Mira at mira@example.com or +91 98765 43210, also @mira_handle"
    redacted = redact_identity(text)
    assert "mira@example.com" not in redacted
    assert "98765" not in redacted
    assert "@mira_handle" not in redacted
    assert redacted.count("[hidden]") >= 3


def test_public_details_strips_semantic_document() -> None:
    details = {
        "objective": "Need a 1BHK",
        "semantic": {"profile": {"semantic_document": "secret-ish"}},
    }
    assert "semantic" not in public_details(details)
    assert public_details(details)["objective"] == "Need a 1BHK"


def test_anonymized_request_has_no_user_identity() -> None:
    request = AgentRequest(
        id="req-1",
        session_id="sess-1",
        user_id="user-secret",
        title="Need a designer",
        summary="Need UI help for a mobile app",
        details={"objective": "Hire a UI designer", "constraints": ["remote"]},
        status="open",
    )
    snapshot = anonymized_request(request)
    assert "user_id" not in snapshot
    assert "session_id" not in snapshot
    assert snapshot["title"] == "Need a designer"
    assert snapshot["hard_constraints"] == ["remote"]


def test_json_result_includes_error_only_when_present() -> None:
    ok = json_result(ok=True, match_id="m1")
    assert '"ok": true' in ok
    assert "error" not in ok
    err = json_result(ok=False, error="nope")
    assert "nope" in err
