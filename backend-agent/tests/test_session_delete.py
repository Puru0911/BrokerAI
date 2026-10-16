from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.routes import broker as broker_routes
from app.db.models import AgentMatch, AgentMessage, AgentRequest, AgentSession
from app.services.session_delete import (
    COUNTERPART_LEFT_MATCH_REPLY,
    SESSION_DELETED,
    delete_session_cascade,
)
from app.services.workflow import CLOSE_REQUEST_CLOSED, MATCH_CLOSED, MATCH_OPEN, REQUEST_CLOSED


def _session(**kwargs) -> AgentSession:
    values = {
        "id": "sess-a",
        "user_id": "user-a",
        "title": "Need a match",
        "status": "open",
    }
    values.update(kwargs)
    return AgentSession(**values)


def _request(**kwargs) -> AgentRequest:
    values = {
        "id": "req-a",
        "session_id": "sess-a",
        "user_id": "user-a",
        "title": "Need a match",
        "summary": "Looking",
        "details": {},
        "status": "open",
    }
    values.update(kwargs)
    return AgentRequest(**values)


def _match(**kwargs) -> AgentMatch:
    values = {
        "id": "match-1",
        "source_request_id": "req-a",
        "candidate_request_id": "req-b",
        "status": MATCH_OPEN,
    }
    values.update(kwargs)
    return AgentMatch(**values)


def _db_with_request(request: AgentRequest | None) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = request
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
async def test_delete_without_a_request_removes_the_session() -> None:
    session = _session()
    db = _db_with_request(None)
    with patch(
        "app.services.session_delete.delete_session_files", new_callable=AsyncMock
    ) as files:
        await delete_session_cascade(db, session)
    files.assert_awaited_once_with(db, session.id)
    db.delete.assert_awaited_once_with(session)


@pytest.mark.asyncio
async def test_delete_without_matches_hard_deletes_request_and_session() -> None:
    session = _session()
    request = _request()
    db = _db_with_request(request)
    with (
        patch(
            "app.services.session_delete.list_matches_for_request",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "app.services.session_delete._drop_request_from_index",
            new_callable=AsyncMock,
        ) as drop,
        patch(
            "app.services.session_delete.delete_session_files", new_callable=AsyncMock
        ) as files,
    ):
        await delete_session_cascade(db, session)
    drop.assert_awaited_once_with(request.id, session.id)
    files.assert_awaited_once_with(db, session.id)
    deleted = [call.args[0] for call in db.delete.await_args_list]
    assert request in deleted
    assert session in deleted


@pytest.mark.asyncio
async def test_delete_with_an_open_match_keeps_the_lane_for_the_other_party() -> None:
    session = _session()
    request = _request(waiting_match_id="match-1")
    other = _request(
        id="req-b",
        session_id="sess-b",
        user_id="user-b",
        waiting_match_id="match-1",
    )
    match = _match()
    remaining = AgentMessage(
        session_id="sess-b",
        role="assistant",
        content="Hi, I found a profile that looks like a good fit.",
        match_id=match.id,
    )
    db = _db_with_request(request)
    db.get = AsyncMock(return_value=other)
    added: list[object] = []
    db.add = MagicMock(side_effect=lambda obj: added.append(obj))

    with (
        patch(
            "app.services.session_delete.list_matches_for_request",
            new_callable=AsyncMock,
            return_value=[match],
        ),
        patch(
            "app.services.session_delete._drop_request_from_index",
            new_callable=AsyncMock,
        ) as drop,
        patch(
            "app.services.session_delete.delete_session_files", new_callable=AsyncMock
        ) as files,
        patch(
            "app.services.session_delete.dismiss_pending_offers_for_match",
            new_callable=AsyncMock,
        ) as dismiss,
        patch(
            "app.services.session_delete.clear_waiting_for_match",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.session_delete.add_event",
            new_callable=AsyncMock,
        ) as event,
    ):
        await delete_session_cascade(db, session)

    db.delete.assert_not_called()
    drop.assert_awaited_once_with(request.id, session.id)
    files.assert_awaited_once_with(db, session.id)
    dismiss.assert_awaited_once_with(db, match.id)
    event.assert_awaited()
    assert session.status == SESSION_DELETED
    assert request.status == REQUEST_CLOSED
    assert match.status == MATCH_CLOSED
    assert match.close_reason == CLOSE_REQUEST_CLOSED
    assert remaining.match_id == match.id
    assert request.waiting_match_id is None
    assert other.waiting_match_id is None
    assert len(added) == 1
    notice = added[0]
    assert isinstance(notice, AgentMessage)
    assert notice.session_id == other.session_id
    assert notice.match_id == match.id
    assert notice.role == "assistant"
    assert notice.content == COUNTERPART_LEFT_MATCH_REPLY


@pytest.mark.asyncio
async def test_delete_with_an_already_closed_match_does_not_repost_notice() -> None:
    session = _session()
    request = _request()
    other = _request(id="req-b", session_id="sess-b", user_id="user-b")
    match = _match(status=MATCH_CLOSED, close_reason="skip")
    db = _db_with_request(request)
    db.get = AsyncMock(return_value=other)
    db.add = MagicMock()

    with (
        patch(
            "app.services.session_delete.list_matches_for_request",
            new_callable=AsyncMock,
            return_value=[match],
        ),
        patch(
            "app.services.session_delete._drop_request_from_index",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.session_delete.delete_session_files", new_callable=AsyncMock
        ),
        patch(
            "app.services.session_delete.dismiss_pending_offers_for_match",
            new_callable=AsyncMock,
        ) as dismiss,
        patch(
            "app.services.session_delete.add_event",
            new_callable=AsyncMock,
        ) as event,
    ):
        await delete_session_cascade(db, session)

    db.delete.assert_not_called()
    db.add.assert_not_called()
    dismiss.assert_not_called()
    event.assert_not_called()
    assert session.status == SESSION_DELETED
    assert request.status == REQUEST_CLOSED
    assert match.status == MATCH_CLOSED
    assert match.close_reason == "skip"


def test_deleted_sessions_are_hidden_from_list_and_get() -> None:
    get_source = inspect.getsource(broker_routes._get_owned_session)
    list_source = inspect.getsource(broker_routes.list_sessions)
    requests_source = inspect.getsource(broker_routes.list_requests)
    match_source = inspect.getsource(broker_routes._get_owned_match)
    assert "SESSION_DELETED" in get_source
    assert "SESSION_DELETED" in list_source
    assert "SESSION_DELETED" in requests_source
    assert "SESSION_DELETED" in match_source
    assert "AgentSession.status != SESSION_DELETED" in match_source
