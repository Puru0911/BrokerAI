from datetime import UTC, datetime, timedelta

from app.db.models import BrokerMatch, BrokerRequest
from app.services.broker_matching import _should_reevaluate_match


def test_skipped_match_is_reevaluated_after_request_update() -> None:
    skipped_at = datetime(2026, 5, 26, 6, 19, tzinfo=UTC)
    source_request = BrokerRequest(
        id="source",
        session_id="source-session",
        user_id="source-user",
        title="Room to rent in Pune",
        summary="Budget updated to 10k-12k",
        structured_data={},
        updated_at=skipped_at + timedelta(minutes=5),
    )
    candidate_request = BrokerRequest(
        id="candidate",
        session_id="candidate-session",
        user_id="candidate-user",
        title="Flatmate in Baner",
        summary="Single room for 12k",
        structured_data={},
        updated_at=skipped_at - timedelta(minutes=5),
    )
    broker_match = BrokerMatch(
        source_request_id=source_request.id,
        candidate_request_id=candidate_request.id,
        status="skipped",
        updated_at=skipped_at,
    )

    assert _should_reevaluate_match(broker_match, source_request, candidate_request)


def test_skipped_match_is_not_reevaluated_without_new_request_context() -> None:
    skipped_at = datetime(2026, 5, 26, 6, 19, tzinfo=UTC)
    source_request = BrokerRequest(
        id="source",
        session_id="source-session",
        user_id="source-user",
        title="Room to rent in Pune",
        summary="Budget around 10k",
        structured_data={},
        updated_at=skipped_at - timedelta(minutes=5),
    )
    candidate_request = BrokerRequest(
        id="candidate",
        session_id="candidate-session",
        user_id="candidate-user",
        title="Flatmate in Baner",
        summary="Single room for 12k",
        structured_data={},
        updated_at=skipped_at - timedelta(minutes=5),
    )
    broker_match = BrokerMatch(
        source_request_id=source_request.id,
        candidate_request_id=candidate_request.id,
        status="skipped",
        updated_at=skipped_at,
    )

    assert not _should_reevaluate_match(broker_match, source_request, candidate_request)

