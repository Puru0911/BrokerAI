from __future__ import annotations

import logging
from typing import Annotated, Any

from langchain_core.tools import BaseTool
from pydantic import BaseModel, BeforeValidator, Field

from app.agents.context import ToolContext
from app.agents.prompts import (
    TOOL_GET_REQUEST_SNAPSHOT,
    TOOL_INDEX_REQUEST,
    TOOL_SAVE_REQUEST,
    TOOL_UPDATE_REQUEST_DETAILS,
    TOOL_UPDATE_SEARCH_BRIEF,
)
from app.agents.tool_call_repair import coerce_optional_str_list, coerce_str_list
from app.agents.tools._common import make_tool
from app.core.logging import clip
from app.db.models import AgentRequest
from app.services.living_request import (
    apply_details_extra_patch,
    apply_search_brief_patch,
    extra_fields_of,
    living_request_from_model,
    search_brief_dict,
)
from app.services.privacy import json_result
from app.services.request_jobs import JOB_INDEX, JobRetryBlocked, enqueue_request_job
from app.services.titles import generate_request_copy
from app.services.workflow import REQUEST_OPEN, get_session_request, open_match_count

logger = logging.getLogger(__name__)


class SaveRequestArgs(BaseModel):
    objective: str = Field(
        max_length=2000,
        description="What this person wants another person to fill.",
    )
    hard_constraints: Annotated[list[str], BeforeValidator(coerce_str_list)] = Field(
        default_factory=list,
        description="Terms that have to hold for a match to work.",
    )
    soft_preferences: Annotated[list[str], BeforeValidator(coerce_str_list)] = Field(
        default_factory=list,
        description="Nice-to-haves that can be negotiated.",
    )
    domain: str = Field(
        default="",
        max_length=120,
        description="Short label for the kind of request.",
    )
    freeform_notes: str = Field(
        default="",
        max_length=2000,
        description="Short offer or who they are, for the search document.",
    )


class UpdateSearchBriefArgs(BaseModel):
    """Fields to change on the search brief. Omitted fields stay as they are."""

    model_config = {"extra": "ignore"}

    objective: str | None = Field(
        default=None,
        max_length=2000,
        description="Updated statement of what they want.",
    )
    hard_constraints: Annotated[list[str] | None, BeforeValidator(coerce_optional_str_list)] = Field(
        default=None,
        description="Replacement list of terms that have to hold.",
    )
    soft_preferences: Annotated[list[str] | None, BeforeValidator(coerce_optional_str_list)] = Field(
        default=None,
        description="Replacement list of negotiable preferences.",
    )
    domain: str | None = Field(
        default=None,
        max_length=120,
        description="Updated short label for the kind of request.",
    )
    freeform_notes: str | None = Field(
        default=None,
        max_length=2000,
        description="Updated offer notes for the search document.",
    )


class UpdateRequestDetailsArgs(BaseModel):
    fields: dict[str, Any] = Field(
        description=(
            "Named extras for this request: facts, answers, secondary constraints, "
            "or background. Not the search brief. Values are text or a list of text."
        ),
    )


class NoArgs(BaseModel):
    model_config = {"extra": "ignore"}


def build_request_tools(ctx: ToolContext) -> list[BaseTool]:
    async def save_request(args: SaveRequestArgs) -> str:
        request = ctx.request or await get_session_request(ctx.db, ctx.session.id)
        core = {
            "objective": args.objective.strip(),
            "hard_constraints": [item.strip() for item in args.hard_constraints if item.strip()],
            "soft_preferences": [item.strip() for item in args.soft_preferences if item.strip()],
            "domain": args.domain.strip(),
            "freeform_notes": args.freeform_notes.strip(),
        }
        extras = extra_fields_of(request.details) if request is not None else {}
        details = {**core, **extras}
        title, summary = await generate_request_copy(core)
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
        request.pending_questions = []
        request.view_filters = []
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
            searchable=False,
            outcome="Search brief saved. Not searchable until indexed.",
        )

    async def update_search_brief(args: UpdateSearchBriefArgs) -> str:
        request = ctx.request or await get_session_request(ctx.db, ctx.session.id)
        if request is None:
            return json_result(ok=False, error="No brief is saved for this session.")
        patch = args.model_dump(exclude_unset=True)
        if not patch:
            return json_result(ok=False, error="No fields to update.")
        details = apply_search_brief_patch(request.details, patch)
        request.details = details
        title, summary = await generate_request_copy(search_brief_dict(details))
        request.title = title
        request.summary = summary
        ctx.session.title = title
        ctx.session.summary = summary
        if request.status != "closed":
            request.status = REQUEST_OPEN
        request.indexed_at = None
        request.pending_questions = []
        request.view_filters = []
        ctx.request = request
        logger.info(
            "update_search_brief session=%s request_id=%s fields=%s",
            ctx.session.id,
            request.id,
            sorted(patch.keys()),
        )
        return json_result(
            ok=True,
            request_id=request.id,
            living_request=living_request_from_model(request),
            updated_fields=sorted(patch.keys()),
            searchable=False,
            outcome="Search brief patched. Not searchable until indexed.",
        )

    async def update_request_details(args: UpdateRequestDetailsArgs) -> str:
        request = ctx.request or await get_session_request(ctx.db, ctx.session.id)
        if request is None:
            return json_result(ok=False, error="No brief is saved for this session.")
        if not args.fields:
            return json_result(ok=False, error="No fields to update.")
        details, applied, refused = apply_details_extra_patch(request.details, args.fields)
        if not applied:
            return json_result(
                ok=False,
                error=(
                    "Those keys belong on the search brief. "
                    "Use update_search_brief for domain, objective, "
                    "hard_constraints, soft_preferences, and freeform_notes."
                    if refused
                    else "No fields to update."
                ),
                refused_fields=refused,
            )
        request.details = details
        ctx.request = request
        logger.info(
            "update_request_details session=%s request_id=%s fields=%s refused=%s",
            ctx.session.id,
            request.id,
            applied,
            refused,
        )
        return json_result(
            ok=True,
            request_id=request.id,
            living_request=living_request_from_model(request),
            updated_fields=applied,
            refused_fields=refused,
            searchable=request.indexed_at is not None,
            outcome="Request details updated. Search index unchanged.",
        )

    async def index_current(_args: NoArgs) -> str:
        request = ctx.request or await get_session_request(ctx.db, ctx.session.id)
        if request is None:
            logger.info("index_request blocked session=%s reason=no_request", ctx.session.id)
            return json_result(ok=False, error="No brief is saved for this session.")
        try:
            job = await enqueue_request_job(
                ctx.db,
                kind=JOB_INDEX,
                request=request,
                session_id=ctx.session.id,
                user_id=ctx.profile.id,
                ctx=ctx,
            )
        except JobRetryBlocked as exc:
            return json_result(ok=False, error=str(exc))
        ctx.request = request
        ctx.queued_jobs.append(job.id)
        logger.info(
            "index_request queued session=%s request_id=%s job_id=%s",
            ctx.session.id,
            request.id,
            job.id,
        )
        open_count = await open_match_count(ctx.db, request.id)
        outcome = (
            "Indexing started. Do not search until this request is indexed."
            if job.status == "queued"
            else "Indexing is already running."
        )
        return json_result(
            ok=True,
            accepted=True,
            job_id=job.id,
            request_id=request.id,
            indexed=request.indexed_at is not None,
            searchable=request.indexed_at is not None,
            open_match_count=open_count,
            outcome=outcome,
        )

    async def get_request_snapshot(_args: NoArgs) -> str:
        request = ctx.request or await get_session_request(ctx.db, ctx.session.id)
        if request is None:
            return json_result(ok=True, living_request=None, outcome="No brief saved.")
        return json_result(
            ok=True,
            living_request=living_request_from_model(request),
            outcome="Brief snapshot loaded.",
        )

    return [
        make_tool(
            name="save_request",
            description=TOOL_SAVE_REQUEST,
            args_model=SaveRequestArgs,
            handler=save_request,
        ),
        make_tool(
            name="update_search_brief",
            description=TOOL_UPDATE_SEARCH_BRIEF,
            args_model=UpdateSearchBriefArgs,
            handler=update_search_brief,
        ),
        make_tool(
            name="update_request_details",
            description=TOOL_UPDATE_REQUEST_DETAILS,
            args_model=UpdateRequestDetailsArgs,
            handler=update_request_details,
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
