from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from app.agents.context import ToolContext
from app.db.models import AgentMatch, AgentRequest
from app.services.privacy import json_result
from app.services.workflow import load_pair_requests, party_role


def make_tool(
    *,
    name: str,
    description: str,
    args_model: type[BaseModel],
    handler: Callable[[BaseModel], Awaitable[str]],
) -> StructuredTool:
    async def _run(*args: Any, **kwargs: Any) -> str:
        if args and isinstance(args[0], args_model):
            payload = args[0]
        elif args and isinstance(args[0], dict) and not kwargs:
            payload = args_model.model_validate(args[0])
        else:
            payload = args_model.model_validate(kwargs)
        try:
            return await handler(payload)
        except Exception as exc:  # noqa: BLE001
            return json_result(ok=False, error=str(exc))

    return StructuredTool.from_function(
        name=name,
        description=description,
        coroutine=_run,
        args_schema=args_model,
    )


async def owned_match(
    ctx: ToolContext,
    match_id: str,
) -> tuple[AgentMatch, AgentRequest, AgentRequest, AgentRequest]:
    if ctx.request is None:
        raise ValueError("No brief is saved for this session.")
    match = await ctx.db.get(AgentMatch, match_id)
    if match is None:
        raise ValueError("Match not found.")
    source, candidate = await load_pair_requests(ctx.db, match)
    if source is None or candidate is None:
        raise ValueError("One side of this match is no longer available.")
    if ctx.request.id not in {source.id, candidate.id}:
        raise ValueError("This match does not belong to the current request.")
    party_role(match, ctx.request)
    other = candidate if ctx.request.id == source.id else source
    return match, ctx.request, other, source
