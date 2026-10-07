"""Introduction offers: a tap-to-connect control in broker chat."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context import OutreachJob
from app.db.models import (
    AgentConnectOffer,
    AgentMatch,
    AgentMessage,
    AgentRequest,
)
from app.services.contact import share_match_contacts
from app.services.workflow import (
    MATCH_ACCEPTED,
    MATCH_CLOSED,
    MATCH_CONNECTED,
    MATCH_OPEN,
    add_event,
    clear_waiting_for_match,
    expiry_from_now,
    party_has_accepted,
    party_role,
)
from app.db.models.broker import utc_now

CONNECT_OFFER_KIND = "broker_connect_offer"
CARD_VERSION = 1
OFFER_PENDING = "pending"
OFFER_ACCEPTED = "accepted"
OFFER_DISMISSED = "dismissed"
DEFAULT_PROMPT = "Ready to be introduced?"
LIVE_INTRODUCTION_STATUSES = {MATCH_OPEN, MATCH_ACCEPTED}


class IntroductionError(ValueError):
    """Raised when an introduction offer cannot be shown or acted on."""


@dataclass
class GoAheadResult:
    match_complete: bool
    already_connected: bool = False
    already_accepted: bool = False
    contact_messages: list[AgentMessage] = field(default_factory=list)
    outreach: OutreachJob | None = None


def parse_connect_offer(content: str) -> dict | None:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None
    if (
        isinstance(payload, dict)
        and payload.get("kind") == CONNECT_OFFER_KIND
        and payload.get("version") == CARD_VERSION
        and isinstance(payload.get("match_id"), str)
    ):
        return payload
    return None


def _card_payload(offer: AgentConnectOffer) -> dict:
    return {
        "kind": CONNECT_OFFER_KIND,
        "version": CARD_VERSION,
        "offer_id": offer.id,
        "match_id": offer.match_id,
        "prompt": offer.prompt,
        "status": offer.status,
        "title": "Introduction",
    }


async def get_offer(
    db: AsyncSession, match_id: str, user_id: str
) -> AgentConnectOffer | None:
    result = await db.execute(
        select(AgentConnectOffer).where(
            AgentConnectOffer.match_id == match_id,
            AgentConnectOffer.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


def introduction_offer_is_live(offer_status: str, match_status: str) -> bool:
    return offer_status == OFFER_PENDING and match_status in LIVE_INTRODUCTION_STATUSES


async def pending_offer_for_session(
    db: AsyncSession, session_id: str
) -> AgentConnectOffer | None:
    result = await db.execute(
        select(AgentConnectOffer)
        .join(AgentMatch, AgentMatch.id == AgentConnectOffer.match_id)
        .where(
            AgentConnectOffer.session_id == session_id,
            AgentConnectOffer.status == OFFER_PENDING,
            AgentMatch.status.in_(LIVE_INTRODUCTION_STATUSES),
        )
        .order_by(AgentConnectOffer.updated_at.desc())
    )
    return result.scalars().first()


async def dismiss_pending_offers_for_match(
    db: AsyncSession, match_id: str
) -> list[AgentConnectOffer]:
    result = await db.execute(
        select(AgentConnectOffer).where(
            AgentConnectOffer.match_id == match_id,
            AgentConnectOffer.status == OFFER_PENDING,
        )
    )
    offers = list(result.scalars().all())
    now = utc_now()
    for offer in offers:
        offer.status = OFFER_DISMISSED
        offer.updated_at = now
    return offers


async def upsert_connect_offer(
    db: AsyncSession,
    *,
    match: AgentMatch,
    user_id: str,
    session_id: str,
    prompt: str,
    write_card: bool = False,
) -> tuple[AgentConnectOffer, AgentMessage | None]:
    if match.status not in {MATCH_OPEN, MATCH_ACCEPTED}:
        raise IntroductionError("This match is not open for an introduction.")
    if await party_has_accepted(db, match.id, user_id):
        raise IntroductionError("This person already recorded a go-ahead.")
    text = (prompt or "").strip() or DEFAULT_PROMPT
    if len(text) > 280:
        text = text[:280]
    offer = await get_offer(db, match.id, user_id)
    created_card = None
    was_pending = offer is not None and offer.status == OFFER_PENDING
    if offer is None:
        offer = AgentConnectOffer(
            match_id=match.id,
            user_id=user_id,
            session_id=session_id,
            prompt=text,
            status=OFFER_PENDING,
        )
        db.add(offer)
        await db.flush()
    else:
        offer.prompt = text
        offer.status = OFFER_PENDING
        offer.session_id = session_id
        offer.updated_at = utc_now()
    if write_card and not was_pending:
        message = AgentMessage(
            session_id=session_id,
            role="assistant",
            content=json.dumps(_card_payload(offer), ensure_ascii=False),
        )
        db.add(message)
        await db.flush()
        offer.message_id = message.id
        created_card = message
    return offer, created_card


async def dismiss_connect_offer(
    db: AsyncSession, match: AgentMatch, user_id: str
) -> AgentConnectOffer | None:
    offer = await get_offer(db, match.id, user_id)
    if offer is None:
        return None
    offer.status = OFFER_DISMISSED
    offer.updated_at = utc_now()
    return offer


async def record_party_go_ahead(
    db: AsyncSession,
    *,
    match: AgentMatch,
    current: AgentRequest,
    other: AgentRequest,
    session_id: str,
) -> GoAheadResult:
    if match.status == MATCH_CONNECTED:
        return GoAheadResult(match_complete=True, already_connected=True)
    if match.status == MATCH_CLOSED:
        raise IntroductionError("A closed match cannot be accepted.")

    already = await party_has_accepted(db, match.id, current.user_id)
    if not already:
        await add_event(
            db,
            match_id=match.id,
            event_type="party_accepted",
            session_id=session_id,
            user_id=current.user_id,
        )
    offer = await get_offer(db, match.id, current.user_id)
    if offer is not None:
        offer.status = OFFER_ACCEPTED
        offer.updated_at = utc_now()

    other_accepted = await party_has_accepted(db, match.id, other.user_id)
    if not other_accepted:
        match.last_activity_at = utc_now()
        match.expires_at = expiry_from_now()
        await upsert_connect_offer(
            db,
            match=match,
            user_id=other.user_id,
            session_id=other.session_id,
            prompt=DEFAULT_PROMPT,
            write_card=False,
        )
        outreach = OutreachJob(
            match_id=match.id,
            to=party_role(match, other),
            context=(
                "They are ready to be introduced. An introduction control is "
                "already in this chat. Ask if they are happy to be introduced. "
                "Do not invent contact details."
            ),
            from_session_id=session_id,
        )
        return GoAheadResult(
            match_complete=False,
            already_accepted=already,
            outreach=outreach,
        )

    match.status = MATCH_ACCEPTED
    match.last_activity_at = utc_now()
    await clear_waiting_for_match(db, match)
    other_offer = await get_offer(db, match.id, other.user_id)
    if other_offer is not None:
        other_offer.status = OFFER_ACCEPTED
        other_offer.updated_at = utc_now()
    cards = await share_match_contacts(db, match)
    return GoAheadResult(
        match_complete=True,
        already_accepted=already,
        contact_messages=cards,
    )
