from __future__ import annotations

import logging
from typing import Annotated

from langchain_core.tools import BaseTool
from pydantic import BaseModel, BeforeValidator, Field, model_validator

from app.agents.context import ToolContext
from app.agents.prompts import (
    TOOL_EVALUATE_PAIR,
    TOOL_PRESENT_CANDIDATES,
    TOOL_SEARCH_COUNTERPARTIES,
)
from app.agents.tool_call_repair import coerce_optional_str_list, coerce_str_list
from app.agents.tools._common import make_tool
from app.agents.tools.request_tools import NoArgs
from app.db.models import AgentMessage
from app.services.living_request import normalize_view_filters, view_filters_of
from app.services.privacy import json_result
from app.services.request_jobs import (
    JOB_EVALUATE,
    JOB_SCREEN,
    enqueue_request_job,
    resolve_evaluate_ids,
)
from app.services.suggestions import SuggestionError, max_pairs, present_candidates

logger = logging.getLogger(__name__)


class EvaluatePairArgs(BaseModel):
    candidate_ids: Annotated[
        list[str] | None,
        Field(
            default=None,
            description="Candidate briefs to screen together, up to the suggestion cap. Omit to use the last search.",
        ),
    ] = None
    candidate_id: str | None = Field(
        default=None,
        min_length=8,
        max_length=36,
        description="A single candidate brief. Prefer candidate_ids when screening several.",
    )
    filters: Annotated[
        list[str] | None,
        BeforeValidator(coerce_optional_str_list),
    ] = Field(
        default=None,
        description=(
            "View overlay for this screen only. Does not change the saved brief. "
            "Empty list clears the overlay. Omit to keep the current overlay."
        ),
    )

    @model_validator(mode="after")
    def collect_ids(self) -> EvaluatePairArgs:
        ids = coerce_str_list(self.candidate_ids)
        extra = (self.candidate_id or "").strip()
        if extra and extra not in ids:
            ids.append(extra)
        self.candidate_ids = ids
        return self


class PresentCandidateItem(BaseModel):
    candidate_id: str = Field(min_length=8, max_length=36)
    preview: str = Field(
        default="",
        max_length=800,
        description="Ignored. The server writes the complementary preview.",
    )


class PresentCandidatesArgs(BaseModel):
    model_config = {"extra": "ignore"}

    candidate_ids: Annotated[
        list[str] | None,
        Field(
            default=None,
            description="Strong fit or Close fit candidates to show. Omit to show every ready card.",
        ),
    ] = None
    candidates: list[PresentCandidateItem] | None = Field(
        default=None,
        description="Legacy list of candidate_id rows. Preview is ignored.",
    )


async def _enqueue_screen(ctx: ToolContext, *, replace: bool = False) -> str:
    if ctx.request is None:
        logger.info("search blocked session=%s reason=no_request", ctx.session.id)
        return json_result(ok=False, error="No brief is saved for this session.")
    if ctx.request.indexed_at is None:
        logger.info("search blocked session=%s request_id=%s reason=not_indexed", ctx.session.id, ctx.request.id)
        return json_result(ok=False, error="This brief is not indexed.")
    job = await enqueue_request_job(
        ctx.db,
        kind=JOB_SCREEN,
        request=ctx.request,
        session_id=ctx.session.id,
        user_id=ctx.profile.id,
        replace=replace,
    )
    ctx.queued_jobs.append(job.id)
    ctx.searched_this_turn = True
    logger.info(
        "search queued session=%s request_id=%s job_id=%s",
        ctx.session.id,
        ctx.request.id,
        job.id,
    )
    outcome = (
        "Search started. Candidates are not listed here."
        if job.status == "queued"
        else "Search is already running."
    )
    return json_result(
        ok=True,
        accepted=True,
        job_id=job.id,
        count=None,
        view_filters=view_filters_of(ctx.request),
        outcome=outcome,
    )


def build_search_tools(ctx: ToolContext) -> list[BaseTool]:
    async def search_counterparties(_args: NoArgs) -> str:
        return await _enqueue_screen(ctx)

    async def evaluate_pair_tool(args: EvaluatePairArgs) -> str:
        if ctx.request is None:
            return json_result(ok=False, error="No brief is saved for this session.")
        if "filters" in args.model_fields_set and args.filters is not None:
            ctx.request.view_filters = normalize_view_filters(args.filters)
        ids = await resolve_evaluate_ids(ctx.db, ctx.request.id, args.candidate_ids)
        if not ids:
            return json_result(ok=False, error="No candidates could be screened.")
        job = await enqueue_request_job(
            ctx.db,
            kind=JOB_EVALUATE,
            request=ctx.request,
            session_id=ctx.session.id,
            user_id=ctx.profile.id,
            candidate_ids=ids,
        )
        ctx.queued_jobs.append(job.id)
        logger.info(
            "evaluate_pair queued session=%s job_id=%s count=%s filters=%s",
            ctx.session.id,
            job.id,
            len(ids),
            view_filters_of(ctx.request),
        )
        return json_result(
            ok=True,
            accepted=True,
            job_id=job.id,
            count=len(ids),
            cap=max_pairs(),
            view_filters=view_filters_of(ctx.request),
            outcome="Screening started. Counterpart briefs are not listed here.",
        )

    async def present_candidates_tool(args: PresentCandidatesArgs) -> str:
        if ctx.request is None:
            return json_result(ok=False, error="No brief is saved for this session.")
        ids = coerce_str_list(args.candidate_ids)
        if args.candidates:
            for item in args.candidates:
                if item.candidate_id not in ids:
                    ids.append(item.candidate_id)
        items = [{"candidate_id": item, "preview": ""} for item in ids[: max_pairs()]]
        try:
            rows = await present_candidates(
                ctx.db,
                session_id=ctx.session.id,
                request=ctx.request,
                items=items or None,
            )
        except SuggestionError as exc:
            return json_result(ok=False, error=str(exc))
        seen_messages: set[str] = set()
        for row in rows:
            if not row.card_message_id or row.card_message_id in seen_messages:
                continue
            seen_messages.add(row.card_message_id)
            message = await ctx.db.get(AgentMessage, row.card_message_id)
            if message is not None:
                ctx.track(message)
        ctx.presented_this_turn = True
        logger.info(
            "present_candidates session=%s count=%s",
            ctx.session.id,
            len(rows),
        )
        return json_result(
            ok=True,
            suggestion_ids=[row.id for row in rows],
            candidate_ids=[row.candidate_request_id for row in rows],
            outcome=(
                f"Showed {len(rows)} candidate card(s) together on this request. "
                "The other person was not notified."
            ),
        )

    return [
        make_tool(
            name="search_counterparties",
            description=TOOL_SEARCH_COUNTERPARTIES,
            args_model=NoArgs,
            handler=search_counterparties,
        ),
        make_tool(
            name="evaluate_pair",
            description=TOOL_EVALUATE_PAIR,
            args_model=EvaluatePairArgs,
            handler=evaluate_pair_tool,
        ),
        make_tool(
            name="present_candidates",
            description=TOOL_PRESENT_CANDIDATES,
            args_model=PresentCandidatesArgs,
            handler=present_candidates_tool,
        ),
    ]
