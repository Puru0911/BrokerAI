from app.db.models import BrokerMatch, BrokerRequest
from app.services.broker_workflow import (
    clear_active_workflow,
    party_role_for_request,
    set_active_workflow,
    waiting_status_for,
)


def test_matching_workflow_pointer_routes_only_target_party() -> None:
    broker_match = BrokerMatch(
        id="match-1",
        source_request_id="source",
        candidate_request_id="candidate",
        status="discovered",
    )
    source_request = BrokerRequest(
        id="source",
        session_id="source-session",
        user_id="source-user",
        title="Need UI/UX designer",
        summary="Need a designer for a mobile app",
        structured_data={},
        status="ready_for_matching",
    )
    candidate_request = BrokerRequest(
        id="candidate",
        session_id="candidate-session",
        user_id="candidate-user",
        title="UI/UX freelancer",
        summary="Offers UI/UX services",
        structured_data={},
        status="ready_for_matching",
    )

    set_active_workflow(candidate_request, broker_match, "matching")

    assert source_request.active_graph is None
    assert source_request.active_match_id is None
    assert source_request.status == "ready_for_matching"
    assert candidate_request.active_graph == "matching"
    assert candidate_request.active_match_id == broker_match.id
    assert candidate_request.status == "matching"


def test_clear_active_workflow_reopens_non_terminal_request() -> None:
    broker_request = BrokerRequest(
        id="candidate",
        session_id="candidate-session",
        user_id="candidate-user",
        title="UI/UX freelancer",
        summary="Offers UI/UX services",
        structured_data={},
        status="matching",
        active_graph="matching",
        active_match_id="match-1",
    )

    clear_active_workflow(broker_request)

    assert broker_request.active_graph is None
    assert broker_request.active_match_id is None
    assert broker_request.status == "ready_for_matching"


def test_party_role_and_waiting_status_are_graph_specific() -> None:
    broker_match = BrokerMatch(
        id="match-1",
        source_request_id="source",
        candidate_request_id="candidate",
        status="discovered",
    )
    source_request = BrokerRequest(
        id="source",
        session_id="source-session",
        user_id="source-user",
        title="Need UI/UX designer",
        summary="Need a designer for a mobile app",
        structured_data={},
    )

    assert party_role_for_request(broker_match, source_request) == "source"
    assert waiting_status_for("matching", "source") == "waiting_source_screening"
    assert waiting_status_for("mediation", "candidate") == "waiting_candidate_mediation"
