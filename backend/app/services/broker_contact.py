from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    BrokerMatch,
    BrokerMediationEvent,
    BrokerMessage,
    BrokerPartyConnection,
    BrokerRequest,
    UserProfile,
)

CONTACT_CARD_KIND = "broker_contact_card"
CONTACT_CARD_VERSION = 1


async def share_match_contacts(
    db: AsyncSession,
    broker_match: BrokerMatch,
) -> list[BrokerMessage]:
    """Share contact cards with both parties after a match is accepted."""
    if broker_match.status != "accepted":
        raise ValueError("Contact details can only be shared after both parties accept.")

    source_request = await db.get(BrokerRequest, broker_match.source_request_id)
    candidate_request = await db.get(BrokerRequest, broker_match.candidate_request_id)
    if source_request is None or candidate_request is None:
        raise ValueError("Cannot share contacts because one request is unavailable.")

    source_profile = await db.get(UserProfile, source_request.user_id)
    candidate_profile = await db.get(UserProfile, candidate_request.user_id)
    if source_profile is None or candidate_profile is None:
        raise ValueError("Cannot share contacts because one profile is unavailable.")

    if await _contact_cards_already_shared(db, broker_match.id):
        return []

    messages = [
        _contact_card_message(
            session_id=source_request.session_id,
            match_id=broker_match.id,
            contact_profile=candidate_profile,
            other_request=candidate_request,
        ),
        _contact_card_message(
            session_id=candidate_request.session_id,
            match_id=broker_match.id,
            contact_profile=source_profile,
            other_request=source_request,
        ),
    ]
    db.add_all(messages)
    await db.flush()
    for message in messages:
        db.add(
            BrokerMediationEvent(
                match_id=broker_match.id,
                session_id=message.session_id,
                user_id=None,
                event_type="contact_card_shared",
                message_text=message.content,
                payload={"message_id": message.id},
            )
        )
    return messages


async def _contact_cards_already_shared(db: AsyncSession, match_id: str) -> bool:
    result = await db.execute(
        select(BrokerMediationEvent).where(
            BrokerMediationEvent.match_id == match_id,
            BrokerMediationEvent.event_type == "contact_card_shared",
        )
    )
    return result.scalar_one_or_none() is not None


async def create_party_connection(
    db: AsyncSession,
    broker_match: BrokerMatch,
) -> BrokerPartyConnection:
    """Create the party-to-party connection record for a matched pair."""
    source_request = await db.get(BrokerRequest, broker_match.source_request_id)
    candidate_request = await db.get(BrokerRequest, broker_match.candidate_request_id)
    if source_request is None or candidate_request is None:
        raise ValueError("Cannot connect parties because one request is unavailable.")

    result = await db.execute(
        select(BrokerPartyConnection).where(BrokerPartyConnection.match_id == broker_match.id)
    )
    existing_connection = result.scalar_one_or_none()
    if existing_connection is not None:
        return existing_connection

    connection = BrokerPartyConnection(
        match_id=broker_match.id,
        source_user_id=source_request.user_id,
        candidate_user_id=candidate_request.user_id,
        status="open",
    )
    db.add(connection)
    await db.flush()
    db.add(
        BrokerMediationEvent(
            match_id=broker_match.id,
            session_id=None,
            user_id=None,
            event_type="party_connection_created",
            payload={"connection_id": connection.id},
        )
    )
    return connection


def _contact_card_message(
    session_id: str,
    match_id: str,
    contact_profile: UserProfile,
    other_request: BrokerRequest,
) -> BrokerMessage:
    payload = {
        "kind": CONTACT_CARD_KIND,
        "version": CONTACT_CARD_VERSION,
        "match_id": match_id,
        "title": "Contact shared",
        "contact": {
            "name": contact_profile.name,
            "email": contact_profile.email,
            "mobile_number": contact_profile.mobile_number,
            "location": contact_profile.location,
        },
        "request": {
            "title": other_request.title,
            "summary": other_request.summary,
            "category": other_request.category,
            "request_type": other_request.request_type,
        },
    }
    return BrokerMessage(
        session_id=session_id,
        role="assistant",
        content=json.dumps(payload, ensure_ascii=False),
    )


def parse_contact_card(content: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None
    if (
        isinstance(payload, dict)
        and payload.get("kind") == CONTACT_CARD_KIND
        and payload.get("version") == CONTACT_CARD_VERSION
    ):
        return payload
    return None
