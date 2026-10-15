"""Match lanes: isolated transcripts for each pair under one request session."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AgentConnection,
    AgentMatch,
    AgentMatchReadState,
    AgentMessage,
    AgentRequest,
    AgentSession,
    UserProfile,
)
from app.db.models.broker import utc_now
from app.schemas.broker import (
    BrokerConnectOfferRead,
    BrokerMatchLaneRead,
    BrokerSessionRead,
)
from app.services.living_request import living_request_dict
from app.services.privacy import redact_identity
from app.services.workflow import (
    MATCH_ACCEPTED,
    MATCH_CONNECTED,
    MATCH_OPEN,
    counterpart_request_id,
    list_matches_for_request,
    load_pair_requests,
    match_notebook,
    party_role,
)

LIVE_LANE_STATUSES = {MATCH_OPEN, MATCH_ACCEPTED, MATCH_CONNECTED}
_GENERIC_TITLES = {"new broker request", "new request", "possible match"}
_HEAD_LIMIT = 28
_PLACE_LIMIT = 24
_TRAILING_GLUE = {"a", "an", "and", "at", "for", "from", "in", "near", "of", "or", "the", "to", "with"}


class MatchLaneError(ValueError):
    """Raised when a match_id does not belong to this session's request."""


async def require_request_match(
    db: AsyncSession,
    request: AgentRequest | None,
    match_id: str | None,
) -> AgentMatch | None:
    """Validate an optional match lane against this request. None is the request lane."""
    if not match_id:
        return None
    if request is None:
        raise MatchLaneError("A brief is needed before talking on a match.")
    match = await db.get(AgentMatch, match_id)
    if match is None:
        raise MatchLaneError("Match not found.")
    if request.id not in {match.source_request_id, match.candidate_request_id}:
        raise MatchLaneError("This match does not belong to this request.")
    return match


def match_lane_label(
    *,
    other: AgentRequest,
    other_profile: UserProfile | None,
    identity_open: bool,
) -> str:
    """Compact tab title for a counterpart. Prefer living brief over the session title dump."""
    living = living_request_dict(other.details)
    location = _short_place(redact_identity((living.get("location") or "").strip()))
    domain = redact_identity((living.get("domain") or "").strip())
    objective = redact_identity((living.get("objective") or "").strip())
    head = _display_domain(domain) if domain else _short_phrase(objective, _HEAD_LIMIT)

    if identity_open and other_profile and (other_profile.name or "").strip():
        name = other_profile.name.strip()
        return f"{name} · {location}" if location else name
    if head and location:
        return f"{head} · {location}"
    if head:
        return head
    if location:
        return location
    title = (other.title or "").strip()
    if title and title.lower() not in _GENERIC_TITLES:
        return _short_phrase(redact_identity(title), _HEAD_LIMIT)
    return "Possible match"


def _short_place(location: str) -> str:
    text = location.strip()
    if "," in text:
        first = text.split(",", 1)[0].strip()
        if len(first) >= 3:
            text = first
    return _short_phrase(text, _PLACE_LIMIT)


def _display_domain(domain: str) -> str:
    text = " ".join(domain.replace("_", " ").replace("-", " ").split())
    if text.islower() or text.isupper():
        text = text.title()
    return _short_phrase(text, _HEAD_LIMIT)


def _short_phrase(text: str, limit: int) -> str:
    compact = " ".join((text or "").split())
    if not compact:
        return ""
    for sep in (". ", "? ", "! ", "; "):
        head, _, rest = compact.partition(sep)
        if rest and 8 <= len(head) < len(compact):
            compact = head
            break
    if len(compact) <= limit:
        return compact
    window = compact[:limit]
    if " " in window:
        clipped = window.rsplit(" ", 1)[0].rstrip(" .,;:-")
    else:
        clipped = window.rstrip(" .,;:-")
    if not clipped:
        clipped = window.rstrip(" .,;:-")
    words = clipped.split()
    while words and words[-1].lower() in _TRAILING_GLUE:
        words.pop()
    if words:
        clipped = " ".join(words)
    return f"{clipped}…"


def match_lane_summary(other: AgentRequest) -> str:
    text = (other.summary or "").strip()
    if not text:
        living = living_request_dict(other.details)
        text = (living.get("objective") or "").strip()
    return redact_identity(text)[:220]


async def mark_match_read(
    db: AsyncSession,
    *,
    match_id: str,
    user_id: str,
    message_id: str | None = None,
) -> AgentMatchReadState:
    result = await db.execute(
        select(AgentMatchReadState).where(
            AgentMatchReadState.match_id == match_id,
            AgentMatchReadState.user_id == user_id,
        )
    )
    state = result.scalar_one_or_none()
    now = utc_now()
    if state is None:
        state = AgentMatchReadState(
            match_id=match_id,
            user_id=user_id,
            last_read_at=now,
            last_read_message_id=message_id,
        )
        db.add(state)
        await db.flush()
        return state
    state.last_read_at = now
    if message_id:
        state.last_read_message_id = message_id
    return state


async def _unread_counts(
    db: AsyncSession,
    *,
    user_id: str,
    session_id: str,
    match_ids: list[str],
) -> dict[str, int]:
    if not match_ids:
        return {}
    reads = await db.execute(
        select(AgentMatchReadState).where(
            AgentMatchReadState.user_id == user_id,
            AgentMatchReadState.match_id.in_(match_ids),
        )
    )
    last_read = {row.match_id: row.last_read_at for row in reads.scalars().all()}
    counts: dict[str, int] = {match_id: 0 for match_id in match_ids}
    conditions = []
    for match_id in match_ids:
        cutoff = last_read.get(match_id)
        if cutoff is None:
            conditions.append(AgentMessage.match_id == match_id)
        else:
            conditions.append(
                and_(
                    AgentMessage.match_id == match_id,
                    AgentMessage.created_at > cutoff,
                )
            )
    result = await db.execute(
        select(
            AgentMessage.match_id,
            func.count(AgentMessage.id),
        )
        .where(
            AgentMessage.session_id == session_id,
            AgentMessage.role == "assistant",
            or_(*conditions),
        )
        .group_by(AgentMessage.match_id)
    )
    for match_id, count in result.all():
        if match_id in counts:
            counts[match_id] = int(count or 0)
    return counts


async def _connections_by_match(
    db: AsyncSession, match_ids: list[str]
) -> dict[str, str]:
    if not match_ids:
        return {}
    result = await db.execute(
        select(AgentConnection).where(AgentConnection.match_id.in_(match_ids))
    )
    return {row.match_id: row.id for row in result.scalars().all()}


async def serialize_match_lanes(
    db: AsyncSession,
    *,
    request: AgentRequest,
    profile: UserProfile,
    offers_by_match: dict[str, Any] | None = None,
) -> list[BrokerMatchLaneRead]:
    matches = await list_matches_for_request(db, request.id, limit=20)
    if not matches:
        return []
    match_ids = [match.id for match in matches]
    unread = await _unread_counts(
        db,
        user_id=profile.id,
        session_id=request.session_id,
        match_ids=match_ids,
    )
    connections = await _connections_by_match(db, match_ids)
    offers = offers_by_match or {}
    lanes: list[BrokerMatchLaneRead] = []
    for match in matches:
        source, candidate = await load_pair_requests(db, match)
        if source is None or candidate is None:
            continue
        other_id = counterpart_request_id(match, request)
        other = candidate if other_id == candidate.id else source
        other_profile = await db.get(UserProfile, other.user_id)
        identity_open = match.status in {MATCH_ACCEPTED, MATCH_CONNECTED}
        notebook = match_notebook(match)
        outstanding = notebook.get("outstanding") or {}
        waiting_on = str(outstanding.get("waiting_on") or "").strip()
        your_role = party_role(match, request)
        offer = offers.get(match.id)
        lanes.append(
            BrokerMatchLaneRead(
                id=match.id,
                status=match.status,
                close_reason=match.close_reason,
                your_role=your_role,
                label=match_lane_label(
                    other=other,
                    other_profile=other_profile,
                    identity_open=identity_open,
                ),
                summary=match_lane_summary(other),
                last_activity_at=match.last_activity_at or match.updated_at or match.created_at,
                unread_count=unread.get(match.id, 0),
                waiting=waiting_on == your_role or request.waiting_match_id == match.id,
                connect_offer=(
                    BrokerConnectOfferRead.model_validate(offer) if offer is not None else None
                ),
                connection_id=connections.get(match.id),
            )
        )
    return lanes


async def serialize_session_read(
    db: AsyncSession,
    session: AgentSession,
    profile: UserProfile,
    *,
    request: AgentRequest | None = None,
    lanes: list[BrokerMatchLaneRead] | None = None,
) -> BrokerSessionRead:
    if lanes is None:
        if request is None:
            from app.services.workflow import get_session_request

            request = await get_session_request(db, session.id)
        if request is not None:
            from app.services.introduction import pending_offers_for_session

            offers = {
                offer.match_id: offer
                for offer in await pending_offers_for_session(db, session.id)
            }
            lanes = await serialize_match_lanes(
                db, request=request, profile=profile, offers_by_match=offers
            )
        else:
            lanes = []
    live = [lane for lane in lanes if lane.status in LIVE_LANE_STATUSES]
    return BrokerSessionRead(
        id=session.id,
        title=session.title,
        status=session.status,
        summary=session.summary,
        created_at=session.created_at,
        updated_at=session.updated_at,
        open_match_count=len([lane for lane in live if lane.status == MATCH_OPEN]),
        match_unread_count=sum(lane.unread_count for lane in lanes),
        matches=lanes,
    )


async def serialize_session_list(
    db: AsyncSession,
    profile: UserProfile,
    sessions: list[AgentSession],
) -> list[BrokerSessionRead]:
    if not sessions:
        return []
    from app.services.workflow import get_session_request

    reads: list[BrokerSessionRead] = []
    for session in sessions:
        request = await get_session_request(db, session.id)
        reads.append(
            await serialize_session_read(db, session, profile, request=request)
        )
    return reads


def roster_entry(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Compact match row for the agent packet (not a full notebook dump)."""
    other = snapshot.get("other_brief") or snapshot.get("other_party") or {}
    notebook = snapshot.get("notebook") or {}
    return {
        "match_id": snapshot.get("match_id"),
        "status": snapshot.get("status"),
        "your_role": snapshot.get("your_role"),
        "label": other.get("domain") or other.get("objective") or snapshot.get("match_id"),
        "other_brief": {
            "request_id": other.get("request_id"),
            "objective": other.get("objective"),
            "domain": other.get("domain"),
            "location": other.get("location"),
            "budget": other.get("budget"),
        },
        "outstanding": notebook.get("outstanding"),
        "next_action": notebook.get("next_action"),
    }
