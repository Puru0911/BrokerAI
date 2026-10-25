"""Source-only screened candidates shown on Your request as Interested/Skip cards."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    AgentMessage,
    AgentRequest,
    AgentSuggestedMatch,
)
from app.services.evaluate import PairEvaluation, clarifying_questions_from
from app.services.privacy import redact_identity
from app.services.workflow import (
    MATCH_ACCEPTED,
    MATCH_CONNECTED,
    MATCH_OPEN,
    OpenMatchError,
    get_pair_match,
    list_matches_for_request,
    open_working_match,
)

logger = logging.getLogger(__name__)

SUGGESTION_STRONG_MATCH = "strong_match"
SUGGESTION_READY = "ready"  # legacy alias; treated as strong_match
SUGGESTION_POSSIBLE_MATCH = "possible_match"
SUGGESTION_PENDING_CLARIFY = "pending_clarify"
SUGGESTION_PRESENTED = "presented"
SUGGESTION_INTERESTED = "interested"
SUGGESTION_SKIPPED = "skipped"
SUGGESTION_NO_MATCH = "no_match"

CANDIDATE_CARD_KIND = "broker_candidate_card"
CANDIDATE_CARDS_KIND = "broker_candidate_cards"
CARD_VERSION = 1

SuggestionAction = Literal["interested", "skip"]

LIVE_MATCH_STATUSES = {MATCH_OPEN, MATCH_ACCEPTED, MATCH_CONNECTED}
STORED_SUGGESTION_STATUSES = {
    SUGGESTION_STRONG_MATCH,
    SUGGESTION_READY,
    SUGGESTION_POSSIBLE_MATCH,
    SUGGESTION_PENDING_CLARIFY,
    SUGGESTION_PRESENTED,
    SUGGESTION_INTERESTED,
    SUGGESTION_SKIPPED,
    SUGGESTION_NO_MATCH,
}
ACTIVE_SUGGESTION_STATUSES = {
    SUGGESTION_STRONG_MATCH,
    SUGGESTION_READY,
    SUGGESTION_POSSIBLE_MATCH,
    SUGGESTION_PENDING_CLARIFY,
    SUGGESTION_PRESENTED,
}
PRESENTABLE_STATUSES = {
    SUGGESTION_STRONG_MATCH,
    SUGGESTION_POSSIBLE_MATCH,
}
CARD_LABEL_STRONG = "strong_fit"
CARD_LABEL_CLOSE = "close_fit"


class SuggestionError(ValueError):
    """Raised when a suggestion cannot be presented or acted on."""


def max_pairs() -> int:
    return max(1, int(settings.MAX_PAIR_PER_REQUEST or 3))


def normalize_status(status: str | None) -> str:
    value = str(status or "").strip()
    if value == SUGGESTION_READY:
        return SUGGESTION_STRONG_MATCH
    return value


def pending_questions_for(row: AgentSuggestedMatch) -> list[str]:
    """Every screening question this person still owes for this pair."""
    if normalize_status(row.status) != SUGGESTION_PENDING_CLARIFY:
        return []
    evaluation = row.evaluation if isinstance(row.evaluation, dict) else {}
    return clarifying_questions_from(evaluation)


def pending_clarify_value(row: AgentSuggestedMatch) -> str | None:
    """First pending question, or None when not required."""
    questions = pending_questions_for(row)
    return questions[0] if questions else None


def all_pending_questions(rows: list[AgentSuggestedMatch]) -> list[str]:
    """Unique this-user questions across pending_clarify rows, pair order."""
    items: list[str] = []
    for row in rows:
        for question in pending_questions_for(row):
            if question not in items:
                items.append(question)
    return items


def pending_question_items(rows: list[AgentSuggestedMatch]) -> list[dict[str, str]]:
    """This-user questions tagged with the stored candidate they belong to."""
    items: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        candidate_id = str(row.candidate_request_id or "").strip()
        if not candidate_id:
            continue
        for question in pending_questions_for(row):
            key = (candidate_id, question)
            if key in seen:
                continue
            seen.add(key)
            items.append({"candidate_id": candidate_id, "question": question})
    return items


def request_pending_questions(request: AgentRequest | None) -> list[str]:
    """Questions this person still owes, with no candidate or request ids."""
    if request is None:
        return []
    items: list[str] = []
    for raw in request.pending_questions or []:
        text = str(raw or "").strip()
        if text and text not in items:
            items.append(text)
    return items


def set_request_pending_questions(request: AgentRequest, questions: list[str]) -> None:
    items: list[str] = []
    for raw in questions:
        text = str(raw or "").strip()
        if text and text not in items:
            items.append(text)
    request.pending_questions = items


def merge_request_pending_questions(request: AgentRequest, questions: list[str]) -> list[str]:
    """Add new questions onto this brief. Returns the ones that were not already stored."""
    current = request_pending_questions(request)
    added: list[str] = []
    for raw in questions:
        text = str(raw or "").strip()
        if text and text not in current:
            current.append(text)
            added.append(text)
    request.pending_questions = current
    return added


def this_user_questions_from(evaluations: list[PairEvaluation]) -> list[str]:
    items: list[str] = []
    for evaluation in evaluations:
        if evaluation.recommended_action != "ask_clarifying_question":
            continue
        if evaluation.verdict == "no_match":
            continue
        for question in clarifying_questions_from(evaluation):
            if question not in items:
                items.append(question)
    return items


def packet_snapshot(row: AgentSuggestedMatch) -> dict[str, Any]:
    evaluation = row.evaluation if isinstance(row.evaluation, dict) else {}
    status = normalize_status(row.status)
    questions = pending_questions_for(row)
    question = questions[0] if questions else None
    return {
        "suggestion_id": row.id,
        "candidate_id": row.candidate_request_id,
        "status": status,
        "verdict": str(evaluation.get("verdict") or "").strip(),
        "recommended_action": str(evaluation.get("recommended_action") or "").strip(),
        "pending_clarify": question,
        "clarifying_question": question or "",
        "pending_questions": questions,
        "score": evaluation.get("score"),
        "presented": status == SUGGESTION_PRESENTED,
        "card_label": card_label_for(row),
    }


async def list_suggestions(
    db: AsyncSession,
    request_id: str,
    *,
    statuses: set[str] | None = None,
) -> list[AgentSuggestedMatch]:
    stmt = select(AgentSuggestedMatch).where(AgentSuggestedMatch.request_id == request_id)
    if statuses:
        stmt = stmt.where(AgentSuggestedMatch.status.in_(statuses))
    stmt = stmt.order_by(AgentSuggestedMatch.updated_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def unpresented_reeval_ids(db: AsyncSession, request_id: str) -> list[str]:
    """Stored Close fit / this-user-question pairs that search would skip."""
    rows = await list_suggestions(
        db,
        request_id,
        statuses={SUGGESTION_PENDING_CLARIFY, SUGGESTION_POSSIBLE_MATCH},
    )
    ids: list[str] = []
    for row in rows:
        if _already_shown(row):
            continue
        if row.candidate_request_id not in ids:
            ids.append(row.candidate_request_id)
    return ids


async def skipped_candidate_ids(db: AsyncSession, request_id: str) -> set[str]:
    rows = await list_suggestions(db, request_id, statuses={SUGGESTION_SKIPPED})
    return {row.candidate_request_id for row in rows}


async def known_candidate_ids(db: AsyncSession, request_id: str) -> set[str]:
    rows = await list_suggestions(db, request_id, statuses=STORED_SUGGESTION_STATUSES)
    return {row.candidate_request_id for row in rows}


async def user_ids_for_request_ids(
    db: AsyncSession,
    request_ids: set[str],
) -> dict[str, str]:
    """Map request id to owning user id."""
    if not request_ids:
        return {}
    result = await db.execute(select(AgentRequest).where(AgentRequest.id.in_(request_ids)))
    return {item.id: item.user_id for item in result.scalars().all() if item.user_id}


async def suggestion_user_map(db: AsyncSession, request_id: str) -> dict[str, str]:
    """Counterpart user_id -> first candidate_request_id already stored on this request."""
    rows = await list_suggestions(
        db,
        request_id,
        statuses=STORED_SUGGESTION_STATUSES - {SUGGESTION_NO_MATCH},
    )
    owners = await user_ids_for_request_ids(db, {row.candidate_request_id for row in rows})
    mapping: dict[str, str] = {}
    for row in rows:
        user_id = owners.get(row.candidate_request_id)
        if user_id and user_id not in mapping:
            mapping[user_id] = row.candidate_request_id
    return mapping


async def live_counterpart_user_ids(db: AsyncSession, request: AgentRequest) -> set[str]:
    matches = await list_matches_for_request(db, request.id, statuses=LIVE_MATCH_STATUSES)
    other_ids: set[str] = set()
    for match in matches:
        other_id = (
            match.candidate_request_id
            if match.source_request_id == request.id
            else match.source_request_id
        )
        if other_id:
            other_ids.add(other_id)
    return set((await user_ids_for_request_ids(db, other_ids)).values())


async def suggestion_for_pair(
    db: AsyncSession,
    request_id: str,
    candidate_request_id: str,
) -> AgentSuggestedMatch | None:
    result = await db.execute(
        select(AgentSuggestedMatch).where(
            AgentSuggestedMatch.request_id == request_id,
            AgentSuggestedMatch.candidate_request_id == candidate_request_id,
        )
    )
    return result.scalar_one_or_none()


async def get_owned_suggestion(
    db: AsyncSession,
    suggestion_id: str,
    request_id: str,
) -> AgentSuggestedMatch:
    row = await db.get(AgentSuggestedMatch, suggestion_id)
    if row is None or row.request_id != request_id:
        raise SuggestionError("Suggestion not found.")
    return row


def status_for_evaluation(evaluation: PairEvaluation) -> str:
    action = evaluation.recommended_action
    verdict = evaluation.verdict
    if action == "skip" or verdict == "no_match":
        return SUGGESTION_NO_MATCH
    if action == "ask_clarifying_question":
        return SUGGESTION_PENDING_CLARIFY
    if action == "ask_other_person":
        return SUGGESTION_POSSIBLE_MATCH
    if verdict == "strong_match":
        return SUGGESTION_STRONG_MATCH
    return SUGGESTION_POSSIBLE_MATCH


def batch_waiting_on_clarify(rows: list[AgentSuggestedMatch]) -> bool:
    return any(normalize_status(row.status) == SUGGESTION_PENDING_CLARIFY for row in rows)


async def upsert_from_evaluations(
    db: AsyncSession,
    *,
    request_id: str,
    evaluations: list[PairEvaluation],
    promote_pending: bool = False,
) -> list[AgentSuggestedMatch]:
    existing = {
        row.candidate_request_id: row
        for row in await list_suggestions(db, request_id)
    }
    now = datetime.now(UTC)
    rows: list[AgentSuggestedMatch] = []
    for evaluation in evaluations:
        candidate_id = evaluation.candidate_id
        if not candidate_id:
            continue
        payload = evaluation.model_dump()
        next_status = status_for_evaluation(evaluation)
        row = existing.get(candidate_id)
        if (
            promote_pending
            and row is not None
            and normalize_status(row.status) == SUGGESTION_PENDING_CLARIFY
            and next_status
            not in {SUGGESTION_SKIPPED, SUGGESTION_NO_MATCH, SUGGESTION_STRONG_MATCH}
        ):
            next_status = SUGGESTION_POSSIBLE_MATCH
            payload["recommended_action"] = "ask_other_person"
        if row is None:
            row = AgentSuggestedMatch(
                request_id=request_id,
                candidate_request_id=candidate_id,
                status=next_status,
                evaluation=payload,
            )
            db.add(row)
            await db.flush()
            existing[candidate_id] = row
        else:
            if row.status in {SUGGESTION_INTERESTED, SUGGESTION_SKIPPED, SUGGESTION_PRESENTED}:
                row.evaluation = payload
                row.updated_at = now
                rows.append(row)
                continue
            else:
                row.status = next_status
            row.evaluation = payload
            row.updated_at = now
        rows.append(row)
    await db.flush()
    return rows


def card_label_for(row: AgentSuggestedMatch) -> str:
    evaluation = row.evaluation if isinstance(row.evaluation, dict) else {}
    verdict = str(evaluation.get("verdict") or "").strip()
    action = str(evaluation.get("recommended_action") or "").strip()
    status = normalize_status(row.status)
    if verdict == "strong_match" and action != "ask_other_person":
        return CARD_LABEL_STRONG
    if (
        status == SUGGESTION_POSSIBLE_MATCH
        or action == "ask_other_person"
        or verdict == "possible_match"
    ):
        return CARD_LABEL_CLOSE
    return CARD_LABEL_STRONG


def _redacted_phrases(values: Any) -> list[str]:
    items: list[str] = []
    for raw in values or []:
        text = redact_identity(str(raw or "").strip())
        if text and text not in items:
            items.append(text)
    return items


def card_fits_for(row: AgentSuggestedMatch) -> list[str]:
    evaluation = row.evaluation if isinstance(row.evaluation, dict) else {}
    return _redacted_phrases(evaluation.get("matched"))[:4]


def card_still_open_for(row: AgentSuggestedMatch) -> list[str]:
    evaluation = row.evaluation if isinstance(row.evaluation, dict) else {}
    items = _redacted_phrases(evaluation.get("missing_info"))
    for phrase in _redacted_phrases(evaluation.get("mismatched")):
        if phrase not in items:
            items.append(phrase)
    return items[:4]


def _preview_for_row(row: AgentSuggestedMatch, provided: str) -> str:
    text = redact_identity(provided.strip())
    if text:
        return text
    evaluation = row.evaluation if isinstance(row.evaluation, dict) else {}
    relative = redact_identity(str(evaluation.get("source_relative_brief") or "").strip())
    if relative:
        return relative
    rationale = redact_identity(str(evaluation.get("rationale") or "").strip())
    if rationale:
        return rationale
    matched = [
        redact_identity(str(item).strip())
        for item in (evaluation.get("matched") or [])
        if str(item).strip()
    ]
    if matched:
        return " · ".join(matched[:4])
    return "A possible match for this request."


def _already_shown(row: AgentSuggestedMatch) -> bool:
    status = normalize_status(row.status)
    return bool(row.card_message_id) or status in {
        SUGGESTION_PRESENTED,
        SUGGESTION_INTERESTED,
        SUGGESTION_SKIPPED,
    }


async def present_candidates(
    db: AsyncSession,
    *,
    session_id: str,
    request: AgentRequest,
    items: list[dict[str, str]] | None = None,
) -> list[AgentSuggestedMatch]:
    cap = max_pairs()
    existing_rows = await list_suggestions(db, request.id)
    previews = {
        str(item.get("candidate_id") or "").strip(): str(item.get("preview") or "")
        for item in (items or [])
        if str(item.get("candidate_id") or "").strip()
    }
    by_candidate = {row.candidate_request_id: row for row in existing_rows}
    for candidate_id in previews:
        row = by_candidate.get(candidate_id)
        if row is None:
            raise SuggestionError("Evaluate that candidate before presenting it.")
        if _already_shown(row):
            continue
        if normalize_status(row.status) not in PRESENTABLE_STATUSES:
            raise SuggestionError("That candidate is not ready to present.")
    shown_users = await live_counterpart_user_ids(db, request)
    settled_ids = {
        row.candidate_request_id
        for row in existing_rows
        if _already_shown(row)
    }
    shown_users.update((await user_ids_for_request_ids(db, settled_ids)).values())
    wanted = set(previews) if previews else None
    to_show: list[AgentSuggestedMatch] = []
    seen: set[str] = set()
    for row in existing_rows:
        if wanted is not None and row.candidate_request_id not in wanted:
            continue
        if _already_shown(row):
            continue
        if normalize_status(row.status) not in PRESENTABLE_STATUSES:
            continue
        if row.candidate_request_id in seen:
            continue
        candidate = await db.get(AgentRequest, row.candidate_request_id)
        if candidate is None:
            raise SuggestionError("Candidate request not found.")
        if candidate.user_id in shown_users:
            continue
        seen.add(row.candidate_request_id)
        shown_users.add(candidate.user_id)
        to_show.append(row)
        if len(to_show) >= cap:
            break
    if not to_show:
        raise SuggestionError("No new Strong fit or Close fit candidates are ready to present.")

    cards: list[dict[str, Any]] = []
    for row in to_show:
        cards.append(
            {
                "suggestion_id": row.id,
                "candidate_id": row.candidate_request_id,
                "preview": _preview_for_row(row, previews.get(row.candidate_request_id, "")),
                "status": SUGGESTION_PRESENTED,
                "label": card_label_for(row),
                "fits": card_fits_for(row),
                "still_open": card_still_open_for(row),
            }
        )
    payload = {
        "kind": CANDIDATE_CARDS_KIND,
        "version": CARD_VERSION,
        "candidates": cards,
    }
    message = AgentMessage(
        session_id=session_id,
        role="assistant",
        content=json.dumps(payload, ensure_ascii=False),
        match_id=None,
    )
    db.add(message)
    await db.flush()
    now = datetime.now(UTC)
    for row in to_show:
        row.card_message_id = message.id
        row.status = SUGGESTION_PRESENTED
        row.updated_at = now
    await db.flush()
    return to_show


async def _stamp_card(db: AsyncSession, row: AgentSuggestedMatch, status: str) -> None:
    if not row.card_message_id:
        return
    message = await db.get(AgentMessage, row.card_message_id)
    if message is None:
        return
    try:
        payload = json.loads(message.content)
    except json.JSONDecodeError:
        return
    if not isinstance(payload, dict):
        return
    kind = payload.get("kind")
    if kind == CANDIDATE_CARDS_KIND:
        changed = False
        for item in payload.get("candidates") or []:
            if isinstance(item, dict) and item.get("suggestion_id") == row.id:
                item["status"] = status
                changed = True
        if not changed:
            return
    elif kind == CANDIDATE_CARD_KIND:
        payload["status"] = status
    else:
        return
    message.content = json.dumps(payload, ensure_ascii=False)


async def skip_suggestion(db: AsyncSession, row: AgentSuggestedMatch) -> AgentSuggestedMatch:
    if row.status == SUGGESTION_INTERESTED:
        raise SuggestionError("That match is already open.")
    row.status = SUGGESTION_SKIPPED
    row.updated_at = datetime.now(UTC)
    await _stamp_card(db, row, SUGGESTION_SKIPPED)
    return row


async def mark_interested(
    db: AsyncSession,
    *,
    row: AgentSuggestedMatch,
    source: AgentRequest,
    session_id: str,
    user_id: str,
    requested_attachment_id: str | None = None,
) -> tuple[Any, bool, str | None]:
    if row.status == SUGGESTION_SKIPPED:
        raise SuggestionError("That candidate was skipped.")
    candidate = await db.get(AgentRequest, row.candidate_request_id)
    if candidate is None:
        raise SuggestionError("Candidate request not found.")
    existing = await get_pair_match(db, source.id, candidate.id)
    if existing is not None and existing.status in LIVE_MATCH_STATUSES:
        row.status = SUGGESTION_INTERESTED
        row.updated_at = datetime.now(UTC)
        await _stamp_card(db, row, SUGGESTION_INTERESTED)
        return existing, True, requested_attachment_id
    try:
        match, reused = await open_working_match(
            db,
            source=source,
            candidate=candidate,
            session_id=session_id,
            user_id=user_id,
        )
    except OpenMatchError as exc:
        raise SuggestionError(str(exc)) from exc
    row.status = SUGGESTION_INTERESTED
    row.updated_at = datetime.now(UTC)
    await _stamp_card(db, row, SUGGESTION_INTERESTED)
    logger.info(
        "suggestion interested suggestion_id=%s match_id=%s reused=%s photo=%s",
        row.id,
        match.id,
        reused,
        requested_attachment_id,
    )
    return match, reused, requested_attachment_id



