from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AgentConnection,
    AgentEvent,
    AgentMatch,
    AgentMessage,
    AgentRequest,
    UserProfile,
)
from app.services.workflow import (
    MATCH_ACCEPTED,
    MATCH_CONNECTED,
    add_event,
    clear_waiting_for_match,
)

CONTACT_CARD_KIND = "broker_contact_card"
CONTACT_CARD_VERSION = 1


async def share_match_contacts(
    db: AsyncSession,
    match: AgentMatch,
) -> list[AgentMessage]:
    if match.status not in {MATCH_ACCEPTED, MATCH_CONNECTED}:
        raise ValueError("Contact details can only be shared after both parties accept.")

    source_request = await db.get(AgentRequest, match.source_request_id)
    candidate_request = await db.get(AgentRequest, match.candidate_request_id)
    if source_request is None or candidate_request is None:
        raise ValueError("Cannot share contacts because one request is unavailable.")

    source_profile = await db.get(UserProfile, source_request.user_id)
    candidate_profile = await db.get(UserProfile, candidate_request.user_id)
    if source_profile is None or candidate_profile is None:
        raise ValueError("Cannot share contacts because one profile is unavailable.")

    if await _contact_cards_already_shared(db, match.id):
        return []

    messages = [
        _contact_card_message(
            session_id=source_request.session_id,
            match_id=match.id,
            contact_profile=candidate_profile,
            other_request=candidate_request,
        ),
        _contact_card_message(
            session_id=candidate_request.session_id,
            match_id=match.id,
            contact_profile=source_profile,
            other_request=source_request,
        ),
    ]
    db.add_all(messages)
    await db.flush()
    for message in messages:
        await add_event(
            db,
            match_id=match.id,
            event_type="contact_card_shared",
            session_id=message.session_id,
            message_text=message.content,
            payload={"message_id": message.id},
        )
    return messages


async def create_party_connection(
    db: AsyncSession,
    match: AgentMatch,
) -> AgentConnection:
    source_request = await db.get(AgentRequest, match.source_request_id)
    candidate_request = await db.get(AgentRequest, match.candidate_request_id)
    if source_request is None or candidate_request is None:
        raise ValueError("Cannot connect parties because one request is unavailable.")
    if match.status not in {MATCH_ACCEPTED, MATCH_CONNECTED}:
        raise ValueError("Both parties must accept before a direct connection can be created.")

    result = await db.execute(
        select(AgentConnection).where(AgentConnection.match_id == match.id)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        match.status = MATCH_CONNECTED
        await clear_waiting_for_match(db, match)
        return existing

    connection = AgentConnection(
        match_id=match.id,
        source_user_id=source_request.user_id,
        candidate_user_id=candidate_request.user_id,
        status="open",
    )
    db.add(connection)
    await db.flush()
    match.status = MATCH_CONNECTED
    await clear_waiting_for_match(db, match)
    await add_event(
        db,
        match_id=match.id,
        event_type="party_connection_created",
        payload={"connection_id": connection.id},
    )
    return connection


async def _contact_cards_already_shared(db: AsyncSession, match_id: str) -> bool:
    result = await db.execute(
        select(AgentEvent).where(
            AgentEvent.match_id == match_id,
            AgentEvent.event_type == "contact_card_shared",
        )
    )
    return result.scalars().first() is not None


def _contact_card_message(
    session_id: str,
    match_id: str,
    contact_profile: UserProfile,
    other_request: AgentRequest,
) -> AgentMessage:
    from app.services.living_request import living_request_dict

    living = living_request_dict(other_request.details)
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
            "category": living.get("domain") or None,
            "request_type": living.get("domain") or "general",
        },
    }
    return AgentMessage(
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
