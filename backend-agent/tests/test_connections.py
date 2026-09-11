from __future__ import annotations

import json

from app.db.models import AgentConnection, AgentRequest, UserProfile
from app.services.connections import peer_user_id
from app.services.contact import _contact_card_message, parse_contact_card
from app.services.push import generate_vapid_keys
from app.services.push import preview_text as push_preview
from app.services.realtime import RealtimeHub


def test_contact_card_omits_mobile_number() -> None:
    profile = UserProfile(
        id="user-1",
        email="priya@example.com",
        name="Priya",
        location="Pune",
        mobile_number="9999999999",
    )
    request = AgentRequest(
        id="req-1",
        session_id="sess-1",
        user_id="user-1",
        title="1BHK in Baner",
        summary="Furnished 1BHK near the metro",
        details={"domain": "housing"},
        status="open",
    )
    message = _contact_card_message(
        session_id="other-session",
        match_id="match-1",
        contact_profile=profile,
        other_request=request,
    )
    payload = json.loads(message.content)
    assert payload["kind"] == "broker_contact_card"
    assert "mobile_number" not in payload["contact"]
    assert payload["contact"]["name"] == "Priya"
    assert payload["contact"]["location"] == "Pune"
    parsed = parse_contact_card(message.content)
    assert parsed is not None
    assert "mobile_number" not in parsed["contact"]


def test_peer_user_id_returns_the_other_party() -> None:
    connection = AgentConnection(
        id="c1",
        match_id="m1",
        source_user_id="source",
        candidate_user_id="candidate",
        status="open",
    )
    assert peer_user_id(connection, "source") == "candidate"
    assert peer_user_id(connection, "candidate") == "source"


def test_push_preview_prefers_text_then_media() -> None:
    assert push_preview("Hello there", has_image=True, has_file=False) == "Hello there"
    assert push_preview("", has_image=True, has_file=False) == "Sent a photo"
    assert push_preview("", has_image=False, has_file=True) == "Sent a file"
    assert push_preview("x" * 200, has_image=False, has_file=False).endswith("...")


def test_generate_vapid_keys_are_urlsafe() -> None:
    keys = generate_vapid_keys()
    assert keys["public_key"]
    assert "BEGIN PRIVATE KEY" in keys["private_key"]
    assert "+" not in keys["public_key"]
    assert "/" not in keys["public_key"]


async def test_realtime_hub_fans_out_to_registered_sockets() -> None:
    hub = RealtimeHub()

    class FakeSocket:
        def __init__(self) -> None:
            self.sent: list[dict] = []

        async def send_json(self, payload: dict) -> None:
            self.sent.append(payload)

    first = FakeSocket()
    second = FakeSocket()
    hub.register("user-a", first)  # type: ignore[arg-type]
    hub.register("user-a", second)  # type: ignore[arg-type]
    hub.register("user-b", FakeSocket())  # type: ignore[arg-type]

    await hub.send_to_user("user-a", {"type": "hello"})
    assert first.sent == [{"type": "hello"}]
    assert second.sent == [{"type": "hello"}]
    assert hub.is_online("user-a") is True
    hub.disconnect("user-a", first)  # type: ignore[arg-type]
    hub.disconnect("user-a", second)  # type: ignore[arg-type]
    assert hub.is_online("user-a") is False


def test_user_from_access_token_accepts_local_dev_token() -> None:
    from app.api.dependencies import user_from_access_token

    user = user_from_access_token("dev:ada@example.com")
    assert user.email == "ada@example.com"
    assert user.id == "dev:ada@example.com"
