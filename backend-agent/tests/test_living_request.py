from app.db.models import AgentRequest
from app.services.living_request import (
    apply_request_patch,
    counterpart_brief_stub,
    living_request_dict,
    living_request_from_model,
)
from app.services.privacy import anonymized_request


def test_living_request_reads_new_and_legacy_keys() -> None:
    details = {
        "objective": "Buy premium used bikes",
        "constraints": ["Mumbai"],
        "preferences": ["BMW"],
        "notes": "Dealer",
        "semantic": {"document": "secret"},
    }
    living = living_request_dict(details)
    assert living["objective"] == "Buy premium used bikes"
    assert living["hard_constraints"] == ["Mumbai"]
    assert living["soft_preferences"] == ["BMW"]
    assert living["freeform_notes"] == "Dealer"
    assert "semantic" not in living


def test_anonymized_request_exposes_living_fields() -> None:
    request = AgentRequest(
        id="req-1",
        session_id="sess-1",
        user_id="user-secret",
        title="Need a designer",
        summary="Need UI help",
        details={"objective": "Hire a UI designer", "hard_constraints": ["remote"]},
        status="open",
    )
    snapshot = anonymized_request(request)
    assert snapshot["objective"] == "Hire a UI designer"
    assert snapshot["hard_constraints"] == ["remote"]
    assert living_request_from_model(request)["indexed"] is False


def test_apply_request_patch_updates_only_provided_fields() -> None:
    details = {
        "objective": "Buy a 1BHK in Pune",
        "budget": "60 lakhs",
        "location": "Pune",
        "timeline": "",
        "hard_constraints": [],
        "soft_preferences": [],
        "domain": "real estate",
        "freeform_notes": "",
    }
    patched = apply_request_patch(details, {"timeline": "within 2 months"})
    assert patched["timeline"] == "within 2 months"
    assert patched["budget"] == "60 lakhs"
    assert patched["objective"] == "Buy a 1BHK in Pune"
    budget_only = apply_request_patch(details, {"budget": "70 lakhs"})
    assert budget_only["budget"] == "70 lakhs"
    assert budget_only["timeline"] == ""


def test_apply_request_patch_keeps_a_possible_pair() -> None:
    details = {
        "objective": "Find a roommate in Pune",
        "budget": "",
        "location": "Pune",
        "timeline": "",
        "hard_constraints": [],
        "soft_preferences": [],
        "domain": "",
        "freeform_notes": "",
        "possible_pair": {
            "other_request_id": "req-b",
            "question": "Confirm community",
            "waiting_on_request_id": "req-b",
            "asked_by_request_id": "req-a",
        },
    }
    patched = apply_request_patch(details, {"budget": "15k"})
    assert patched["budget"] == "15k"
    assert patched["possible_pair"]["other_request_id"] == "req-b"


def test_counterpart_brief_stub_does_not_include_the_other_bio() -> None:
    view = counterpart_brief_stub("req-other")
    assert view == {
        "request_id": "req-other",
        "possible_counterpart": True,
        "objective": "A possible counterpart for this request.",
    }
