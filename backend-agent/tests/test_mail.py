from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.context import MailJob
from app.agents.prompts import NATURAL_FALLBACK_REPLY, UNAVAILABLE_REPLY
from app.core.config import settings
from app.db.models import (
    AgentMailLog,
    AgentMatch,
    AgentMessage,
    AgentRequest,
    AgentSession,
    UserProfile,
)
from app.services import notify
from app.services.mail_templates import contacts_mail, preview_for_mail
from app.services.mailer import send_email
from app.services.notify import (
    STATUS_SENT,
    STATUS_SKIPPED_DISABLED,
    STATUS_SKIPPED_NO_EMAIL,
    STATUS_SKIPPED_ONLINE,
    STATUS_SKIPPED_UNCONFIGURED,
    deliver_mail,
    mail_jobs_for_contacts,
    mail_jobs_for_outreach,
    parse_unsubscribe_token,
    schedule_mail,
    unsubscribe_token,
)


def _profile(**kwargs: object) -> UserProfile:
    return UserProfile(
        id=str(kwargs.get("id", "user-1")),
        email=kwargs.get("email", "ada@example.com"),  # type: ignore[arg-type]
        name="Ada",
        location="Pune",
        mobile_number="9999999999",
        notify_email=bool(kwargs.get("notify_email", True)),
    )


def _job(**kwargs: object) -> MailJob:
    return MailJob(
        kind=kwargs.get("kind", "broker_outreach"),  # type: ignore[arg-type]
        user_id=str(kwargs.get("user_id", "user-1")),
        session_id=str(kwargs.get("session_id", "session-1")),
        source_id=str(kwargs.get("source_id", "msg-1")),
        title="Find a flat",
        preview="Are you still looking this week?",
    )


def test_preview_collapses_contact_json() -> None:
    raw = json.dumps(
        {
            "kind": "broker_contact_card",
            "version": 1,
            "contact": {"name": "Sam", "email": "sam@example.com"},
        }
    )
    preview = preview_for_mail(raw)
    assert "Sam" in preview
    assert "{" not in preview
    assert "sam@example.com" not in preview


def test_contacts_template_is_human_copy() -> None:
    content = contacts_mail(
        peer_name="Sam",
        session_id="session-1",
        unsubscribe_url="http://localhost:3000/mail/unsubscribe?token=x",
    )
    assert "You're introduced" in content.subject or "You're introduced" in content.text
    assert "Sam" in content.text
    assert "broker_contact_card" not in content.text
    assert "{" not in content.text


def test_unsubscribe_token_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MAIL_UNSUBSCRIBE_SECRET", "test-secret")
    token = unsubscribe_token("user-1")
    assert parse_unsubscribe_token(token) == "user-1"
    assert parse_unsubscribe_token("user-1:1:deadbeef") is None


def test_unsubscribe_token_rejects_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MAIL_UNSUBSCRIBE_SECRET", "test-secret")
    token = unsubscribe_token("user-1", ttl_seconds=-10)
    assert parse_unsubscribe_token(token) is None


@pytest.mark.asyncio
async def test_send_email_skips_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MAIL_ENABLED", True)
    monkeypatch.setattr(settings, "RESEND_API_KEY", None)
    monkeypatch.setattr(settings, "MAIL_FROM", None)
    result = await send_email(
        to="ada@example.com",
        subject="Hi",
        text="Hi",
        html="<p>Hi</p>",
    )
    assert result is None


@pytest.mark.asyncio
async def test_send_email_posts_to_resend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MAIL_ENABLED", True)
    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test")
    monkeypatch.setattr(settings, "MAIL_FROM", "broker@example.com")
    monkeypatch.setattr(settings, "MAIL_FROM_NAME", "BrokerAI")

    response = MagicMock()
    response.status_code = 200
    response.content = b'{"id":"re_123"}'
    response.json.return_value = {"id": "re_123"}

    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.mailer.httpx.AsyncClient", return_value=client):
        provider_id = await send_email(
            to="ada@example.com",
            subject="Update",
            text="Hello",
            html="<p>Hello</p>",
            unsubscribe_url="http://localhost:3000/mail/unsubscribe?token=x",
        )

    assert provider_id == "re_123"
    payload = client.post.await_args.kwargs["json"]
    assert payload["to"] == ["ada@example.com"]
    assert "List-Unsubscribe" in payload["headers"]


def test_schedule_mail_does_not_deliver_inline() -> None:
    created: list[object] = []

    def fake_create_task(coro, name=None):
        created.append(name)
        coro.close()

    with (
        patch("app.services.notify.asyncio.create_task", side_effect=fake_create_task),
        patch("app.services.notify.deliver_mail", new_callable=AsyncMock) as deliver,
    ):
        schedule_mail([_job()])
    assert created == ["mail-broker_outreach-msg-1"]
    deliver.assert_not_called()


@pytest.mark.asyncio
async def test_outreach_jobs_skip_fallback_and_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notify, "pending_offer_for_session", AsyncMock(return_value=None))
    session = AgentSession(id="session-1", user_id="user-1", title="Flat")
    profile = _profile()
    replies = [
        AgentMessage(id="1", session_id="session-1", role="assistant", content=NATURAL_FALLBACK_REPLY),
        AgentMessage(id="2", session_id="session-1", role="assistant", content=UNAVAILABLE_REPLY),
        AgentMessage(
            id="3",
            session_id="session-1",
            role="assistant",
            content=json.dumps({"kind": "broker_contact_card", "version": 1, "contact": {"name": "Sam"}}),
        ),
    ]
    jobs = await mail_jobs_for_outreach(
        AsyncMock(),
        session=session,
        profile=profile,
        replies=replies,
    )
    assert jobs == []


@pytest.mark.asyncio
async def test_outreach_jobs_use_last_prose_and_offer(monkeypatch: pytest.MonkeyPatch) -> None:
    offer = MagicMock(id="offer-1", prompt="Ready to be introduced?")
    monkeypatch.setattr(notify, "pending_offer_for_session", AsyncMock(return_value=offer))
    session = AgentSession(id="session-1", user_id="user-1", title="Flat in Pune")
    profile = _profile()
    replies = [
        AgentMessage(id="msg-1", session_id="session-1", role="assistant", content="Still looking?"),
    ]
    jobs = await mail_jobs_for_outreach(
        AsyncMock(),
        session=session,
        profile=profile,
        replies=replies,
    )
    assert len(jobs) == 1
    assert jobs[0].kind == "broker_outreach"
    assert jobs[0].source_id == "msg-1"
    assert jobs[0].offer_prompt == "Ready to be introduced?"
    assert jobs[0].title == "Flat in Pune"


@pytest.mark.asyncio
async def test_outreach_jobs_intro_when_no_prose(monkeypatch: pytest.MonkeyPatch) -> None:
    offer = MagicMock(id="offer-1", prompt="Ready to be introduced?")
    monkeypatch.setattr(notify, "pending_offer_for_session", AsyncMock(return_value=offer))
    session = AgentSession(id="session-1", user_id="user-1", title="Flat")
    jobs = await mail_jobs_for_outreach(
        AsyncMock(),
        session=session,
        profile=_profile(),
        replies=[],
    )
    assert len(jobs) == 1
    assert jobs[0].kind == "intro_offered"
    assert jobs[0].source_id == "offer-1"


@pytest.mark.asyncio
async def test_deliver_skips_online_no_email_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[str] = []

    async def fake_existing(*_args, **_kwargs):
        return None

    async def fake_record(_db, _job, *, status, resend_id=None, error=None):
        recorded.append(status)
        return AgentMailLog(
            user_id="user-1",
            kind="broker_outreach",
            source_id="msg-1",
            status=status,
        )

    monkeypatch.setattr(notify, "_existing_log", fake_existing)
    monkeypatch.setattr(notify, "_record", fake_record)
    db = AsyncMock()

    db.get = AsyncMock(return_value=_profile(email=None))
    await deliver_mail(db, _job())
    assert recorded[-1] == STATUS_SKIPPED_NO_EMAIL

    db.get = AsyncMock(return_value=_profile(notify_email=False))
    await deliver_mail(db, _job())
    assert recorded[-1] == STATUS_SKIPPED_DISABLED

    db.get = AsyncMock(return_value=_profile())
    monkeypatch.setattr(notify.hub, "is_online", lambda _uid: True)
    await deliver_mail(db, _job())
    assert recorded[-1] == STATUS_SKIPPED_ONLINE


@pytest.mark.asyncio
async def test_deliver_skips_unconfigured_and_sends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[str] = []

    async def fake_existing(*_args, **_kwargs):
        return None

    async def fake_record(_db, _job, *, status, resend_id=None, error=None):
        recorded.append(status)
        return AgentMailLog(
            user_id="user-1",
            kind="broker_outreach",
            source_id="msg-1",
            status=status,
            resend_id=resend_id,
        )

    monkeypatch.setattr(notify, "_existing_log", fake_existing)
    monkeypatch.setattr(notify, "_record", fake_record)
    monkeypatch.setattr(notify.hub, "is_online", lambda _uid: False)
    db = AsyncMock()
    db.get = AsyncMock(return_value=_profile())

    monkeypatch.setattr(settings, "MAIL_ENABLED", True)
    monkeypatch.setattr(settings, "RESEND_API_KEY", None)
    monkeypatch.setattr(settings, "MAIL_FROM", None)
    await deliver_mail(db, _job())
    assert recorded[-1] == STATUS_SKIPPED_UNCONFIGURED

    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test")
    monkeypatch.setattr(settings, "MAIL_FROM", "broker@example.com")
    monkeypatch.setattr(notify, "send_email", AsyncMock(return_value="re_99"))
    await deliver_mail(db, _job())
    assert recorded[-1] == STATUS_SENT


@pytest.mark.asyncio
async def test_contact_jobs_one_per_party() -> None:
    match = AgentMatch(
        id="match-1",
        source_request_id="req-1",
        candidate_request_id="req-2",
    )
    source = AgentRequest(
        id="req-1",
        session_id="session-1",
        user_id="user-1",
        title="Need a flat",
        summary="",
    )
    candidate = AgentRequest(
        id="req-2",
        session_id="session-2",
        user_id="user-2",
        title="Have a flat",
        summary="",
    )
    source_profile = _profile(id="user-1")
    source_profile.name = "Ada"
    candidate_profile = _profile(id="user-2")
    candidate_profile.name = "Sam"

    async def fake_get(model, ident):
        if ident == "req-1":
            return source
        if ident == "req-2":
            return candidate
        if ident == "user-1":
            return source_profile
        if ident == "user-2":
            return candidate_profile
        return None

    db = AsyncMock()
    db.get = fake_get
    messages = [
        AgentMessage(id="c1", session_id="session-1", role="assistant", content="{}"),
        AgentMessage(id="c2", session_id="session-2", role="assistant", content="{}"),
    ]
    jobs = await mail_jobs_for_contacts(db, match, messages)
    assert {job.user_id for job in jobs} == {"user-1", "user-2"}
    assert all(job.kind == "contacts_delivered" for job in jobs)
    by_user = {job.user_id: job for job in jobs}
    assert by_user["user-1"].peer_name == "Sam"
    assert by_user["user-2"].peer_name == "Ada"
    assert by_user["user-1"].source_id == "match-1:user-1"


@pytest.mark.asyncio
async def test_deliver_does_not_resend(monkeypatch: pytest.MonkeyPatch) -> None:
    existing = AgentMailLog(
        user_id="user-1",
        kind="broker_outreach",
        source_id="msg-1",
        status=STATUS_SENT,
        resend_id="re_old",
    )
    monkeypatch.setattr(notify, "_existing_log", AsyncMock(return_value=existing))
    send = AsyncMock(return_value="re_new")
    monkeypatch.setattr(notify, "send_email", send)
    result = await deliver_mail(AsyncMock(), _job())
    assert result is existing
    send.assert_not_called()
