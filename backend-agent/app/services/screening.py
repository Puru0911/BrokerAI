"""Retrieve and screen counterpart requests without exposing briefs to the broker."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.prompts import ANSWER_MATCH_QUESTION_PROMPT, SOURCE_RELATIVE_BRIEF_PROMPT
from app.db.models import AgentRequest
from app.llm.client import invoke_structured_model
from app.rag.retriever import retrieve_similar_requests
from app.services.evaluate import PairEvaluation, evaluate_pairs
from app.services.living_request import living_request_dict, view_filters_of
from app.services.privacy import redact_identity as _redact
from app.services.suggestions import (
    all_pending_questions,
    live_counterpart_user_ids,
    max_pairs,
    set_request_pending_questions,
    skipped_candidate_ids,
    suggestion_user_map,
    unpresented_reeval_ids,
    upsert_from_evaluations,
    user_ids_for_request_ids,
)
from app.services.workflow import (
    MATCH_ACCEPTED,
    MATCH_CONNECTED,
    MATCH_OPEN,
    get_pair_match,
    load_events,
)

logger = logging.getLogger(__name__)

LIVE_MATCH_STATUSES = {MATCH_OPEN, MATCH_ACCEPTED, MATCH_CONNECTED}


class SourceRelativeBrief(BaseModel):
    model_config = {"extra": "ignore"}
    brief: str = Field(default="", max_length=800)


class MatchQuestionAnswer(BaseModel):
    model_config = {"extra": "ignore"}
    found: bool = False
    answer: str = Field(default="", max_length=800)


def screening_summary(
    *,
    candidate_ids: list[str],
    rows,
    errors: list[str] | None = None,
    request: AgentRequest | None = None,
) -> dict[str, Any]:
    by_status: dict[str, list[str]] = {}
    for row in rows:
        by_status.setdefault(row.status, []).append(row.candidate_request_id)
    strong = by_status.get("strong_match") or by_status.get("ready") or []
    pending = by_status.get("pending_clarify") or []
    possible = by_status.get("possible_match") or []
    return {
        "count": len(candidate_ids),
        "candidate_ids": candidate_ids,
        "strong_match": strong,
        "possible_match": possible,
        "pending_clarify": pending,
        "pending_questions": all_pending_questions(rows),
        "skipped": by_status.get("skipped") or [],
        "presented": by_status.get("presented") or [],
        "errors": errors or [],
        "cap": max_pairs(),
        "hold_cards": False,
        "view_filters": view_filters_of(request),
    }


async def retrieve_candidates(
    db: AsyncSession,
    request: AgentRequest,
    *,
    limit: int | None = None,
) -> list[tuple[AgentRequest, float | None]]:
    overlay = view_filters_of(request)
    pool = 16 if overlay else 8
    cap = limit or pool
    skipped = await skipped_candidate_ids(db, request.id)
    skipped_users = set((await user_ids_for_request_ids(db, skipped)).values())
    taken_users = set(await live_counterpart_user_ids(db, request))
    taken_users.update(skipped_users)
    raw = await retrieve_similar_requests(db, request, pool)
    matches: list[tuple[AgentRequest, float | None]] = []
    for candidate, distance in raw:
        if candidate.id in skipped:
            continue
        if candidate.user_id in taken_users:
            continue
        existing = await get_pair_match(db, request.id, candidate.id)
        if existing is not None and existing.status in LIVE_MATCH_STATUSES:
            continue
        matches.append((candidate, distance))
        taken_users.add(candidate.user_id)
        if len(matches) >= cap:
            break
    return matches


async def _prior_events_for(
    db: AsyncSession,
    source_id: str,
    candidates: list[AgentRequest],
) -> dict[str, list[dict[str, Any]]]:
    prior: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        existing = await get_pair_match(db, source_id, candidate.id)
        if existing is None:
            continue
        events = await load_events(db, existing.id, limit=20)
        prior[candidate.id] = [
            {"type": event.event_type, "message": event.message_text}
            for event in events
        ]
    return prior


async def load_candidates_by_id(
    db: AsyncSession,
    source: AgentRequest,
    candidate_ids: list[str],
) -> tuple[list[AgentRequest], list[str]]:
    candidates: list[AgentRequest] = []
    errors: list[str] = []
    known_users = await suggestion_user_map(db, source.id)
    live_users = await live_counterpart_user_ids(db, source)
    skipped = await skipped_candidate_ids(db, source.id)
    seen_users: set[str] = set()
    for candidate_id in list(dict.fromkeys(candidate_ids))[: max_pairs()]:
        if candidate_id == source.id:
            errors.append(f"{candidate_id}: cannot screen this brief against itself.")
            continue
        if candidate_id in skipped:
            errors.append(f"{candidate_id}: this person already skipped that candidate.")
            continue
        candidate = await db.get(AgentRequest, candidate_id)
        if candidate is None:
            errors.append(f"{candidate_id}: candidate request not found.")
            continue
        if candidate.user_id == source.user_id:
            errors.append(f"{candidate_id}: a user cannot be matched with their own request.")
            continue
        if candidate.user_id in seen_users:
            errors.append(f"{candidate_id}: another request from this person is already in the set.")
            continue
        mapped = known_users.get(candidate.user_id)
        if mapped and mapped != candidate.id:
            errors.append(f"{candidate_id}: another request from this person is already screened.")
            continue
        if candidate.user_id in live_users:
            errors.append(f"{candidate_id}: a live match with this person already exists.")
            continue
        existing = await get_pair_match(db, source.id, candidate.id)
        if existing is not None and existing.status in LIVE_MATCH_STATUSES:
            errors.append(f"{candidate_id}: this pair is already open.")
            continue
        seen_users.add(candidate.user_id)
        candidates.append(candidate)
    return candidates, errors


async def screen_request(
    db: AsyncSession,
    request: AgentRequest,
    job: Any | None = None,
) -> dict[str, Any]:
    stored_ids = await unpresented_reeval_ids(db, request.id)
    stored, stored_errors = await load_candidates_by_id(db, request, stored_ids)
    matches = await retrieve_candidates(db, request)
    seen = {item.id for item in stored}
    candidates = list(stored)
    for candidate, _distance in matches:
        if candidate.id in seen:
            continue
        candidates.append(candidate)
        seen.add(candidate.id)
    candidate_ids = [item.id for item in candidates]
    if job is not None:
        payload = dict(job.payload or {})
        payload["candidate_ids"] = candidate_ids
        payload["count"] = len(candidate_ids)
        job.payload = payload
        await db.flush()
    if not candidates:
        logger.info("screen empty request_id=%s", request.id)
        set_request_pending_questions(request, [])
        return screening_summary(
            candidate_ids=[],
            rows=[],
            errors=stored_errors,
            request=request,
        )
    prior = await _prior_events_for(db, request.id, candidates)
    evaluations, parse_errors = await evaluate_pairs(
        request,
        candidates,
        prior_events_by_id=prior,
        view_filters=view_filters_of(request),
    )
    errors = [*stored_errors, *parse_errors]
    if candidates and not evaluations and parse_errors:
        raise RuntimeError("; ".join(parse_errors))
    rows = await _store_screen_results(db, request, evaluations)
    logger.info("screen complete request_id=%s count=%s", request.id, len(candidate_ids))
    return screening_summary(
        candidate_ids=candidate_ids,
        rows=rows,
        errors=errors,
        request=request,
    )


async def evaluate_candidate_ids(
    db: AsyncSession,
    request: AgentRequest,
    candidate_ids: list[str],
) -> dict[str, Any]:
    candidates, errors = await load_candidates_by_id(db, request, candidate_ids)
    if not candidates:
        return screening_summary(candidate_ids=[], rows=[], errors=errors, request=request)
    prior = await _prior_events_for(db, request.id, candidates)
    evaluations, parse_errors = await evaluate_pairs(
        request,
        candidates,
        prior_events_by_id=prior,
        view_filters=view_filters_of(request),
    )
    errors = [*errors, *parse_errors]
    if candidates and not evaluations and parse_errors:
        raise RuntimeError("; ".join(parse_errors))
    rows = await _store_screen_results(
        db, request, evaluations, promote_pending=True
    )
    return screening_summary(
        candidate_ids=[item.id for item in candidates],
        rows=rows,
        errors=errors,
        request=request,
    )


async def _store_screen_results(
    db: AsyncSession,
    request: AgentRequest,
    evaluations: list[PairEvaluation],
    *,
    promote_pending: bool = False,
) -> list:
    rows = await upsert_from_evaluations(
        db,
        request_id=request.id,
        evaluations=evaluations,
        promote_pending=promote_pending,
    )
    set_request_pending_questions(request, all_pending_questions(rows))
    return rows


def brief_from_suggestion(evaluation: dict[str, Any] | None) -> str:
    data = evaluation if isinstance(evaluation, dict) else {}
    text = str(data.get("source_relative_brief") or "").strip()
    if text:
        return _redact(text)
    matched = [
        _redact(str(item).strip())
        for item in (data.get("matched") or [])
        if str(item).strip()
    ]
    if matched:
        return " · ".join(matched[:4])
    return ""


async def build_source_relative_brief(
    source: AgentRequest,
    candidate: AgentRequest,
    *,
    stored: str = "",
) -> str:
    text = _redact((stored or "").strip())
    if text:
        return text
    result = await invoke_structured_model(
        parser_model=SourceRelativeBrief,
        system_prompt=SOURCE_RELATIVE_BRIEF_PROMPT,
        human_payload={
            "source_request": living_request_dict(source.details),
            "candidate_profile": living_request_dict(candidate.details),
        },
        temperature=0.1,
    )
    return _redact((result.brief or "").strip()) or "A possible counterpart for this request."


async def answer_from_briefs(
    source: AgentRequest,
    candidate: AgentRequest,
    question: str,
    *,
    evaluation: dict[str, Any] | None = None,
    notebook: dict[str, Any] | None = None,
) -> MatchQuestionAnswer:
    result = await invoke_structured_model(
        parser_model=MatchQuestionAnswer,
        system_prompt=ANSWER_MATCH_QUESTION_PROMPT,
        human_payload={
            "source_request": living_request_dict(source.details),
            "candidate_profile": living_request_dict(candidate.details),
            "screening_notes": {
                "matched": (evaluation or {}).get("matched") or [],
                "source_relative_brief": (evaluation or {}).get("source_relative_brief") or "",
            },
            "notebook": notebook or {},
            "question": question,
        },
        temperature=0.1,
    )
    result.answer = _redact((result.answer or "").strip())
    if not result.found:
        result.answer = ""
    return result
