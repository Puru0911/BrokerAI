from app.db.models import AgentRequest
from app.rag.indexer import living_input
from app.services.living_request import (
    SEARCH_CORE_KEYS,
    apply_details_extra_patch,
    apply_request_patch,
    apply_search_brief_patch,
    counterpart_brief_stub,
    extra_fields_of,
    living_request_dict,
    living_request_from_model,
    normalize_view_filters,
    search_brief_dict,
    view_filters_of,
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
    assert "budget" not in living
    assert "location" not in living


def test_search_brief_omits_extra_keys() -> None:
    details = {
        "objective": "Need a designer",
        "domain": "hiring",
        "hard_constraints": ["remote"],
        "soft_preferences": [],
        "freeform_notes": "SaaS",
        "budget": "2 lakh",
        "hometown": "Aurangabad",
    }
    brief = search_brief_dict(details)
    assert set(brief) == {
        "objective",
        "hard_constraints",
        "soft_preferences",
        "domain",
        "freeform_notes",
    }
    living = living_request_dict(details)
    assert living["budget"] == "2 lakh"
    assert living["hometown"] == "Aurangabad"


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


def test_apply_search_brief_patch_preserves_extra_keys() -> None:
    details = {
        "objective": "Buy a 1BHK in Pune",
        "domain": "real estate",
        "hard_constraints": [],
        "soft_preferences": [],
        "freeform_notes": "",
        "budget": "60 lakhs",
        "location": "Pune",
        "semantic": {"document": "secret"},
    }
    patched = apply_search_brief_patch(details, {"freeform_notes": "Owner occupied"})
    assert patched["freeform_notes"] == "Owner occupied"
    assert patched["objective"] == "Buy a 1BHK in Pune"
    assert patched["budget"] == "60 lakhs"
    assert patched["location"] == "Pune"
    assert patched["semantic"] == {"document": "secret"}
    assert apply_request_patch(details, {"domain": "housing"})["budget"] == "60 lakhs"


def test_apply_search_brief_patch_drops_a_legacy_possible_pair() -> None:
    details = {
        "objective": "Find a roommate in Pune",
        "domain": "",
        "hard_constraints": [],
        "soft_preferences": [],
        "freeform_notes": "",
        "possible_pair": {
            "other_request_id": "req-b",
            "question": "Confirm community",
            "waiting_on_request_id": "req-b",
            "asked_by_request_id": "req-a",
        },
    }
    patched = apply_search_brief_patch(details, {"domain": "housing"})
    assert patched["domain"] == "housing"
    assert "possible_pair" not in patched


def test_apply_details_extra_patch_adds_and_replaces_keys() -> None:
    details = {
        "objective": "Need a designer",
        "domain": "hiring",
        "hard_constraints": [],
        "soft_preferences": [],
        "freeform_notes": "",
        "semantic": {"document": "secret"},
    }
    patched, applied, refused = apply_details_extra_patch(
        details, {"rate": "$45/hour", "notice_period": "60 days"}
    )
    assert applied == ["rate", "notice_period"]
    assert refused == []
    assert patched["rate"] == "$45/hour"
    assert patched["notice_period"] == "60 days"
    assert patched["objective"] == "Need a designer"
    assert patched["semantic"] == {"document": "secret"}
    replaced, applied, refused = apply_details_extra_patch(patched, {"rate": "$50/hour"})
    assert replaced["rate"] == "$50/hour"
    assert replaced["notice_period"] == "60 days"


def test_apply_details_extra_patch_refuses_search_core_keys() -> None:
    details = {"objective": "Need a designer", "domain": "hiring"}
    patched, applied, refused = apply_details_extra_patch(
        details, {"objective": "Need a PM", "hometown": "Pune"}
    )
    assert "hometown" in applied
    assert "objective" in refused
    assert patched["objective"] == "Need a designer"
    assert patched["hometown"] == "Pune"


def test_apply_details_extra_patch_refuses_core_aliases() -> None:
    details = {"objective": "Need a designer", "domain": "hiring"}
    patched, applied, refused = apply_details_extra_patch(
        details, {"constraints": ["remote"], "kind": "work", "rate": "$45"}
    )
    assert applied == ["rate"]
    assert "constraints" in refused
    assert "kind" in refused
    assert patched["rate"] == "$45"
    assert "constraints" not in patched
    assert patched["objective"] == "Need a designer"


def test_apply_details_extra_patch_empty_value_deletes_the_key() -> None:
    details = {
        "objective": "Need a designer",
        "domain": "hiring",
        "rate": "$45/hour",
        "notice_period": "60 days",
    }
    patched, applied, refused = apply_details_extra_patch(details, {"rate": ""})
    assert applied == ["rate"]
    assert refused == []
    assert "rate" not in patched
    assert patched["notice_period"] == "60 days"


def test_extra_fields_skip_empty_values() -> None:
    details = {
        "objective": "Need a flat",
        "budget": "",
        "location": "Pune",
    }
    extras = extra_fields_of(details)
    assert "budget" not in extras
    assert extras["location"] == "Pune"
    living = living_request_dict(details)
    assert "budget" not in living
    assert living["location"] == "Pune"


def test_view_filters_are_not_part_of_the_living_brief() -> None:
    assert normalize_view_filters([" Kharadi ", "Kharadi", "furnished", ""]) == [
        "Kharadi",
        "furnished",
    ]
    request = AgentRequest(
        id="req-1",
        session_id="sess-1",
        user_id="user-1",
        title="Need a flat",
        summary="Looking",
        details={"objective": "2BHK in Pune", "location": "Pune"},
        status="open",
        view_filters=["Kharadi"],
    )
    living = living_request_from_model(request)
    assert living is not None
    assert "view_filters" not in living
    assert living["location"] == "Pune"
    assert view_filters_of(request) == ["Kharadi"]


def test_index_input_is_search_core_only() -> None:
    request = AgentRequest(
        id="req-1",
        session_id="sess-1",
        user_id="user-1",
        title="Need a designer",
        summary="Looking",
        details={
            "objective": "Need a designer",
            "domain": "hiring",
            "hard_constraints": ["remote"],
            "soft_preferences": [],
            "freeform_notes": "SaaS",
            "rate": "$45/hour",
            "hometown": "Pune",
        },
        status="open",
    )
    payload = living_input(request)
    assert set(payload) == set(SEARCH_CORE_KEYS)
    assert "rate" not in payload
    assert "hometown" not in payload


def test_counterpart_brief_stub_does_not_include_the_other_bio() -> None:
    view = counterpart_brief_stub("req-other")
    assert view == {
        "request_id": "req-other",
        "possible_counterpart": True,
        "objective": "A possible counterpart for this request.",
    }
