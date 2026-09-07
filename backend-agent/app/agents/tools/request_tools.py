from __future__ import annotations

import logging
from typing import Annotated

from langchain_core.tools import BaseTool
from pydantic import BaseModel, BeforeValidator, Field

from app.agents.context import ToolContext
from app.agents.prompts import (
    TOOL_GET_REQUEST_SNAPSHOT,
    TOOL_INDEX_REQUEST,
    TOOL_SAVE_REQUEST,
    TOOL_UPDATE_REQUEST,
)
from app.agents.tool_call_repair import coerce_optional_str_list, coerce_str_list
from app.agents.tools._common import make_tool
from app.core.logging import clip
from app.db.models import AgentRequest
from app.rag.indexer import index_request
from app.services.living_request import apply_request_patch, living_request_from_model
from app.services.privacy import json_result
from app.services.titles import create_title
from app.services.workflow import REQUEST_OPEN, get_session_request, open_match_count

logger = logging.getLogger(__name__)


class SaveRequestArgs(BaseModel):
    objective: str = Field(max_length=2000)
    hard_constraints: Annotated[list[str], BeforeValidator(coerce_str_list)] = Field(
        default_factory=list
    )
    soft_preferences: Annotated[list[str], BeforeValidator(coerce_str_list)] = Field(
        default_factory=list
    )
    budget: str = Field(default="", max_length=240)
    domain: str = Field(default="", max_length=120)
    location: str = Field(default="", max_length=160)
    timeline: str = Field(default="", max_length=160)
    freeform_notes: str = Field(default="", max_length=2000)


class UpdateRequestArgs(BaseModel):
    """Patch only the fields that changed. Omitted fields stay as they are."""

    model_config = {"extra": "ignore"}

    objective: str | None = Field(default=None, max_length=2000)
    hard_constraints: Annotated[list[str] | None, BeforeValidator(coerce_optional_str_list)] = None
    soft_preferences: Annotated[list[str] | None, BeforeValidator(coerce_optional_str_list)] = None
    budget: str | None = Field(default=None, max_length=240)
    domain: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=160)
    timeline: str | None = Field(default=None, max_length=160)
    freeform_notes: str | None = Field(default=None, max_length=2000)


class NoArgs(BaseModel):
    model_config = {"extra": "ignore"}


def build_request_tools(ctx: ToolContext) -> list[BaseTool]:
    async def save_request(args: SaveRequestArgs) -> str:
        details = {
            "objective": args.objective.strip(),
            "hard_constraints": [item.strip() for item in args.hard_constraints if item.strip()],
            "soft_preferences": [item.strip() for item in args.soft_preferences if item.strip()],
            "budget": args.budget.strip(),
            "domain": args.domain.strip(),
            "location": args.location.strip(),
            "timeline": args.timeline.strip(),
            "freeform_notes": args.freeform_notes.strip(),
        }
        title = create_title(args.objective) if args.objective.strip() else "New broker request"
        summary = args.objective.strip()
        request = ctx.request or await get_session_request(ctx.db, ctx.session.id)
        if request is None:
            request = AgentRequest(
                session_id=ctx.session.id,
                user_id=ctx.profile.id,
                status=REQUEST_OPEN,
                title=title,
                summary=summary,
                details=details,
            )
            ctx.db.add(request)
            await ctx.db.flush()
        else:
            request.title = title
            request.summary = summary
            request.details = details
            if request.status != "closed":
                request.status = REQUEST_OPEN
            request.indexed_at = None
        ctx.request = request
        ctx.saved_this_turn = True
        ctx.session.title = title
        ctx.session.summary = summary
        ctx.session.status = "open"
        logger.info(
            "save_request session=%s request_id=%s objective=%s",
            ctx.session.id,
            request.id,
            clip(args.objective, 160),
        )
        return json_result(
            ok=True,
            request_id=request.id,
            living_request=living_request_from_model(request),
            hint=(
                "Call index_request only when you have no further questions for this "
                "user right now. If you still need an answer from them, ask in your "
                "reply and index later."
            ),
        )

    async def update_request(args: UpdateRequestArgs) -> str:
        request = ctx.request or await get_session_request(ctx.db, ctx.session.id)
        if request is None:
            return json_result(ok=False, error="Save the request before updating it.")
        patch = args.model_dump(exclude_unset=True)
        if not patch:
            return json_result(ok=False, error="No fields to update.")
        details = apply_request_patch(request.details, patch)
        request.details = details
        if details.get("objective"):
            request.title = create_title(details["objective"])
            request.summary = details["objective"]
            ctx.session.title = request.title
            ctx.session.summary = request.summary
        if request.status != "closed":
            request.status = REQUEST_OPEN
        request.indexed_at = None
        ctx.request = request
        logger.info(
            "update_request session=%s request_id=%s fields=%s",
            ctx.session.id,
            request.id,
            sorted(patch.keys()),
        )
        return json_result(
            ok=True,
            request_id=request.id,
            living_request=living_request_from_model(request),
            updated_fields=sorted(patch.keys()),
            hint=(
                "Call index_request only when you have no further questions for this "
                "user right now. An open match does not require indexing by itself."
            ),
        )

    async def index_current(_args: NoArgs) -> str:
        request = ctx.request or await get_session_request(ctx.db, ctx.session.id)
        if request is None:
            logger.info("index_request blocked session=%s reason=no_request", ctx.session.id)
            return json_result(ok=False, error="Save the request before indexing.")
        try:
            await index_request(request)
        except Exception as exc:  # noqa: BLE001
            logger.warning("index_request failed session=%s request_id=%s error=%s", ctx.session.id, request.id, exc)
            return json_result(ok=False, error=str(exc))
        ctx.request = request
        ctx.indexed_this_turn = request.indexed_at is not None
        logger.info(
            "index_request session=%s request_id=%s indexed=%s",
            ctx.session.id,
            request.id,
            ctx.indexed_this_turn,
        )
        open_count = await open_match_count(ctx.db, request.id)
        if open_count:
            hint = (
                "An open match already exists. Use update_notebook and message_party "
                "(to='source' or to='candidate') as needed. Search again only if this "
                "brief change requires new counterparties."
            )
        else:
            hint = (
                "Search counterparties only if you have no further questions for this "
                "user right now."
            )
        return json_result(
            ok=True,
            request_id=request.id,
            indexed=ctx.indexed_this_turn,
            hint=hint,
        )

    async def get_request_snapshot(_args: NoArgs) -> str:
        request = ctx.request or await get_session_request(ctx.db, ctx.session.id)
        if request is None:
            return json_result(ok=True, living_request=None)
        return json_result(ok=True, living_request=living_request_from_model(request))

    return [
        make_tool(
            name="save_request",
            description=TOOL_SAVE_REQUEST,
            args_model=SaveRequestArgs,
            handler=save_request,
        ),
        make_tool(
            name="update_request",
            description=TOOL_UPDATE_REQUEST,
            args_model=UpdateRequestArgs,
            handler=update_request,
        ),
        make_tool(
            name="index_request",
            description=TOOL_INDEX_REQUEST,
            args_model=NoArgs,
            handler=index_current,
        ),
        make_tool(
            name="get_request_snapshot",
            description=TOOL_GET_REQUEST_SNAPSHOT,
            args_model=NoArgs,
            handler=get_request_snapshot,
        ),
    ]
