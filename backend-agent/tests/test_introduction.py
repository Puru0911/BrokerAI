from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.tools.match_tools import OfferIntroductionArgs
from app.db.models import AgentConnectOffer
from app.schemas.broker import BrokerIntroductionAction, BrokerSessionDetail
from app.services.introduction import (
    CONNECT_OFFER_KIND,
    DEFAULT_PROMPT,
    OFFER_DISMISSED,
    OFFER_PENDING,
    dismiss_pending_offers_for_match,
    introduction_offer_is_live,
    parse_connect_offer,
)
from app.services.workflow import MATCH_ACCEPTED, MATCH_CLOSED, MATCH_OPEN


def test_parse_connect_offer_reads_card() -> None:
    raw = (
        '{"kind":"broker_connect_offer","version":1,"match_id":"m1",'
        '"prompt":"Ready to be introduced?","status":"pending","title":"Introduction"}'
    )
    payload = parse_connect_offer(raw)
    assert payload is not None
    assert payload["kind"] == CONNECT_OFFER_KIND
    assert payload["match_id"] == "m1"
    assert payload["prompt"] == DEFAULT_PROMPT
    assert parse_connect_offer("hello") is None


def test_offer_introduction_args_take_prompt() -> None:
    args = OfferIntroductionArgs(match_id="match-1", prompt="Want me to introduce you?")
    assert args.match_id == "match-1"
    assert "introduce" in args.prompt.lower()
    schema = OfferIntroductionArgs.model_json_schema()
    assert "match_id" in schema.get("properties", {})
    assert "prompt" in schema.get("properties", {})


def test_introduction_action_schema() -> None:
    assert BrokerIntroductionAction(action="accept").action == "accept"
    assert BrokerIntroductionAction(action="dismiss").action == "dismiss"


def test_session_detail_includes_connect_offer_field() -> None:
    fields = BrokerSessionDetail.model_fields
    assert "connect_offer" in fields


def test_introduction_offer_is_hidden_when_match_is_closed() -> None:
    assert introduction_offer_is_live(OFFER_PENDING, MATCH_OPEN) is True
    assert introduction_offer_is_live(OFFER_PENDING, MATCH_ACCEPTED) is True
    assert introduction_offer_is_live(OFFER_PENDING, MATCH_CLOSED) is False
    assert introduction_offer_is_live(OFFER_DISMISSED, MATCH_OPEN) is False


@pytest.mark.asyncio
async def test_dismiss_pending_offers_for_match_withdraws_both_parties() -> None:
    first = AgentConnectOffer(
        match_id="m1",
        user_id="user-a",
        session_id="sess-a",
        status=OFFER_PENDING,
    )
    second = AgentConnectOffer(
        match_id="m1",
        user_id="user-b",
        session_id="sess-b",
        status=OFFER_PENDING,
    )
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [first, second]
    db.execute = AsyncMock(return_value=result)

    withdrawn = await dismiss_pending_offers_for_match(db, "m1")

    assert withdrawn == [first, second]
    assert first.status == OFFER_DISMISSED
    assert second.status == OFFER_DISMISSED
