from __future__ import annotations

import logging
from typing import Annotated

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, model_validator

from app.agents.context import ToolContext
from app.agents.prompts import (
    TOOL_EVALUATE_PAIR,
    TOOL_PRESENT_CANDIDATES,
    TOOL_SEARCH_AGAIN,
    TOOL_SEARCH_COUNTERPARTIES,
)
from app.agents.tool_call_repair import coerce_str_list
from app.agents.tools._common import make_tool
from app.agents.tools.request_tools import NoArgs
from app.db.models import AgentMessage, AgentRequest
from app.rag.retriever import retrieve_similar_requests
from app.services.evaluate import evaluate_pairs
from app.services.living_request import redacted_living_request
from app.services.privacy import json_result
from app.services.suggestions import (
    SuggestionError,
    all_pending_questions,
    known_candidate_ids,
    max_pairs,
    present_candidates,
    upsert_from_evaluations,
)
from app.services.workflow import (
    MATCH_ACCEPTED,
    MATCH_CONNECTED,
    MATCH_OPEN,
    get_pair_match,
    load_events,
)

logger = logging.getLogger(__name__)


class EvaluatePairArgs(BaseModel):
    candidate_ids: Annotated[
        list[str] | None,
        Field(
            default=None,
            description="Candidate briefs to screen together, up to the suggestion cap.",
        ),
    ] = None
    candidate_id: str | None = Field(
        default=None,
        min_length=8,
        max_length=36,
        description="A single candidate brief. Prefer candidate_ids when screening several.",
    )

    @model_validator(mode="after")
    def collect_ids(self) -> EvaluatePairArgs:
        ids = coerce_str_list(self.candidate_ids)
        extra = (self.candidate_id or "").strip()
        if extra and extra not in ids:
            ids.append(extra)
        if not ids:
            raise ValueError("Pass candidate_ids (or candidate_id) to screen.")
        self.candidate_ids = ids
        return self


class PresentCandidateItem(BaseModel):
    candidate_id: str = Field(min_length=8, max_length=36)
    preview: str = Field(
        min_length=1,
        max_length=800,
        description="Anonymized complementary brief for this person's request.",
    )


class PresentCandidatesArgs(BaseModel):
    candidates: list[PresentCandidateItem] = Field(min_length=1)


async def _run_search(ctx: ToolContext) -> str:
    if ctx.request is None:
        logger.info("search blocked session=%s reason=no_request", ctx.session.id)
        return json_result(ok=False, error="No brief is saved for this session.")
    if ctx.request.indexed_at is None:
        logger.info("search blocked session=%s request_id=%s reason=not_indexed", ctx.session.id, ctx.request.id)
        return json_result(ok=False, error="This brief is not indexed.")
    known = await known_candidate_ids(ctx.db, ctx.request.id)
    raw = await retrieve_similar_requests(ctx.db, ctx.request, 8)
    matches: list[tuple[AgentRequest, float | None]] = []
    for candidate, distance in raw:
        if candidate.id in known:
            continue
        existing = await get_pair_match(ctx.db, ctx.request.id, candidate.id)
        if existing is not None and existing.status in {MATCH_OPEN, MATCH_ACCEPTED, MATCH_CONNECTED}:
            continue
        matches.append((candidate, distance))
        if len(matches) >= 5:
            break
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
        outcome=f"Retrieved {len(matches)} candidate(s).",
    )


def build_search_tools(ctx: ToolContext) -> list[BaseTool]:
    async def search_counterparties(_args: NoArgs) -> str:
        return await _run_search(ctx)

    async def search_again(_args: NoArgs) -> str:
        return await _run_search(ctx)

    async def evaluate_pair_tool(args: EvaluatePairArgs) -> str:
        if ctx.request is None:
            return json_result(ok=False, error="No brief is saved for this session.")
        ids = list(dict.fromkeys(args.candidate_ids or []))[: max_pairs()]
        candidates: list[AgentRequest] = []
        errors: list[str] = []
        prior_by_id: dict[str, list[dict]] = {}
        for candidate_id in ids:
            if candidate_id == ctx.request.id:
                errors.append(f"{candidate_id}: cannot screen this brief against itself.")
                continue
            candidate = await ctx.db.get(AgentRequest, candidate_id)
            if candidate is None:
                errors.append(f"{candidate_id}: candidate request not found.")
                continue
            if candidate.user_id == ctx.request.user_id:
                errors.append(f"{candidate_id}: a user cannot be matched with their own request.")
                continue
            existing = await get_pair_match(ctx.db, ctx.request.id, candidate.id)
            if existing is not None and existing.status in {
                MATCH_OPEN,
                MATCH_ACCEPTED,
                MATCH_CONNECTED,
            }:
                errors.append(f"{candidate_id}: this pair is already open.")
                continue
            if existing is not None:
                events = await load_events(ctx.db, existing.id, limit=20)
                prior_by_id[candidate.id] = [
                    {"type": event.event_type, "message": event.message_text}
                    for event in events
                ]
            candidates.append(candidate)
        if not candidates:
            return json_result(
                ok=False,
                error="No candidates could be screened.",
                errors=errors,
            )
        evaluations = await evaluate_pairs(
            ctx.request,
            candidates,
            prior_events_by_id=prior_by_id,
        )
        rows = await upsert_from_evaluations(
            ctx.db,
            request_id=ctx.request.id,
            evaluations=evaluations,
        )
        by_status: dict[str, list[str]] = {}
        for row in rows:
            by_status.setdefault(row.status, []).append(row.candidate_request_id)
        logger.info(
            "evaluate_pair session=%s count=%s statuses=%s",
            ctx.session.id,
            len(evaluations),
            {key: len(value) for key, value in by_status.items()},
        )
        strong = by_status.get("strong_match") or by_status.get("ready") or []
        pending = by_status.get("pending_clarify") or []
        questions = all_pending_questions(rows)
        return json_result(
            ok=True,
            evaluations=[item.model_dump() for item in evaluations],
            strong_match=strong,
            pending_clarify=pending,
            pending_questions=questions,
            skipped=by_status.get("skipped") or [],
            presented=by_status.get("presented") or [],
            errors=errors,
            cap=max_pairs(),
            hold_cards=bool(pending),
            outcome=(
                f"Screened {len(evaluations)} candidate(s). "
                f"strong_match {len(strong)}; "
                f"pending_clarify {len(pending)}."
                + (
                    " Ask the pending questions before presenting any cards."
                    if pending
                    else " Present every strong_match candidate together."
                )
            ),
        )

    async def present_candidates_tool(args: PresentCandidatesArgs) -> str:
        if ctx.request is None:
            return json_result(ok=False, error="No brief is saved for this session.")
        items = [
            {"candidate_id": item.candidate_id, "preview": item.preview}
            for item in args.candidates[: max_pairs()]
        ]
        try:
            rows = await present_candidates(
                ctx.db,
                session_id=ctx.session.id,
                request=ctx.request,
                items=items,
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
        make_tool(
            name="present_candidates",
            description=TOOL_PRESENT_CANDIDATES,
            args_model=PresentCandidatesArgs,
            handler=present_candidates_tool,
        ),
    ]
