from __future__ import annotations

import logging

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from app.agents.context import ToolContext
from app.agents.prompts import (
    TOOL_EVALUATE_PAIR,
    TOOL_SEARCH_AGAIN,
    TOOL_SEARCH_COUNTERPARTIES,
)
from app.agents.tools._common import make_tool
from app.agents.tools.request_tools import NoArgs
from app.db.models import AgentRequest
from app.rag.retriever import retrieve_similar_requests
from app.services.evaluate import evaluate_pair
from app.services.living_request import redacted_living_request
from app.services.privacy import json_result
from app.services.workflow import get_pair_match, load_events

logger = logging.getLogger(__name__)


class EvaluatePairArgs(BaseModel):
    candidate_id: str = Field(min_length=8, max_length=36)


async def _run_search(ctx: ToolContext) -> str:
    if ctx.request is None:
        logger.info("search blocked session=%s reason=no_request", ctx.session.id)
        return json_result(ok=False, error="Save the request before searching.")
    if ctx.request.indexed_at is None:
        logger.info("search blocked session=%s request_id=%s reason=not_indexed", ctx.session.id, ctx.request.id)
        return json_result(ok=False, error="Call index_request before searching.")
    matches = await retrieve_similar_requests(ctx.db, ctx.request, 5)
    ctx.searched_this_turn = True
    logger.info(
        "search_counterparties session=%s request_id=%s count=%s",
        ctx.session.id,
        ctx.request.id,
        len(matches),
    )
    return json_result(
        ok=True,
        count=len(matches),
        candidates=[
            {
                "candidate_id": candidate.id,
                **redacted_living_request(candidate),
                "distance": distance,
            }
            for candidate, distance in matches
        ],
        hint="Call evaluate_pair on each new candidate_id before open_match.",
    )


def build_search_tools(ctx: ToolContext) -> list[BaseTool]:
    async def search_counterparties(_args: NoArgs) -> str:
        return await _run_search(ctx)

    async def search_again(_args: NoArgs) -> str:
        return await _run_search(ctx)

    async def evaluate_pair_tool(args: EvaluatePairArgs) -> str:
        if ctx.request is None:
            return json_result(ok=False, error="Save the request before evaluating a pair.")
        candidate = await ctx.db.get(AgentRequest, args.candidate_id)
        if candidate is None:
            return json_result(ok=False, error="Candidate request not found.")
        if candidate.user_id == ctx.request.user_id:
            return json_result(ok=False, error="A user cannot be matched with their own request.")
        existing = await get_pair_match(ctx.db, ctx.request.id, candidate.id)
        prior: list[dict] = []
        if existing is not None:
            events = await load_events(ctx.db, existing.id, limit=20)
            prior = [
                {"type": event.event_type, "message": event.message_text}
                for event in events
            ]
        evaluation = await evaluate_pair(
            ctx.request,
            candidate,
            prior_events=prior,
        )
        logger.info(
            "evaluate_pair session=%s candidate_id=%s verdict=%s action=%s negotiation_room=%s",
            ctx.session.id,
            candidate.id,
            evaluation.verdict,
            evaluation.recommended_action,
            evaluation.negotiation_room,
        )
        return json_result(
            ok=True,
            candidate_id=candidate.id,
            evaluation=evaluation.model_dump(),
        )

    return [
        make_tool(
            name="search_counterparties",
            description=TOOL_SEARCH_COUNTERPARTIES,
            args_model=NoArgs,
            handler=search_counterparties,
        ),
        make_tool(
            name="search_again",
            description=TOOL_SEARCH_AGAIN,
            args_model=NoArgs,
            handler=search_again,
        ),
        make_tool(
            name="evaluate_pair",
            description=TOOL_EVALUATE_PAIR,
            args_model=EvaluatePairArgs,
            handler=evaluate_pair_tool,
        ),
    ]
