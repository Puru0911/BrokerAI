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
    AgentAttachment,
    AgentMessage,
    AgentRequest,
    AgentSuggestedMatch,
)
from app.services.attachments import SHARE_PERSONAL, SHARE_PUBLIC, is_image_type, model_facing_label
from app.services.evaluate import PairEvaluation, clarifying_questions_from
from app.services.privacy import redact_identity
from app.services.workflow import (
    MATCH_ACCEPTED,
    MATCH_CONNECTED,
    MATCH_OPEN,
    OpenMatchError,
    get_pair_match,
    open_working_match,
)

logger = logging.getLogger(__name__)

SUGGESTION_STRONG_MATCH = "strong_match"
SUGGESTION_READY = "ready"  # legacy alias; treated as strong_match
SUGGESTION_PENDING_CLARIFY = "pending_clarify"
SUGGESTION_PRESENTED = "presented"
SUGGESTION_INTERESTED = "interested"
SUGGESTION_SKIPPED = "skipped"

CANDIDATE_CARD_KIND = "broker_candidate_card"
CANDIDATE_CARDS_KIND = "broker_candidate_cards"
CARD_VERSION = 1

SuggestionAction = Literal["interested", "skip"]

LIVE_MATCH_STATUSES = {MATCH_OPEN, MATCH_ACCEPTED, MATCH_CONNECTED}
ACTIVE_SUGGESTION_STATUSES = {
    SUGGESTION_STRONG_MATCH,
    SUGGESTION_READY,
    SUGGESTION_PENDING_CLARIFY,
    SUGGESTION_PRESENTED,
}


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
    """Unique pending questions across the whole screening set, pair order."""
    items: list[str] = []
    for row in rows:
        for question in pending_questions_for(row):
            if question not in items:
                items.append(question)
    return items


def packet_snapshot(row: AgentSuggestedMatch) -> dict[str, Any]:
    evaluation = row.evaluation if isinstance(row.evaluation, dict) else {}
    status = normalize_status(row.status)
    questions = pending_questions_for(row)
    question = questions[0] if questions else None
    missing = [
        str(item).strip()
        for item in (evaluation.get("missing_info") or [])
        if str(item).strip()
    ]
    return {
        "suggestion_id": row.id,
        "candidate_id": row.candidate_request_id,
        "status": status,
        "verdict": str(evaluation.get("verdict") or "").strip(),
        "recommended_action": str(evaluation.get("recommended_action") or "").strip(),
        "pending_clarify": question,
        "clarifying_question": question or "",
        "pending_questions": questions,
        "missing_info": missing,
        "score": evaluation.get("score"),
        "presented": status == SUGGESTION_PRESENTED,
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


async def skipped_candidate_ids(db: AsyncSession, request_id: str) -> set[str]:
    rows = await list_suggestions(db, request_id, statuses={SUGGESTION_SKIPPED})
    return {row.candidate_request_id for row in rows}


async def known_candidate_ids(db: AsyncSession, request_id: str) -> set[str]:
    rows = await list_suggestions(db, request_id)
    return {row.candidate_request_id for row in rows}


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
        return SUGGESTION_SKIPPED
    if action == "ask_clarifying_question":
        return SUGGESTION_PENDING_CLARIFY
    return SUGGESTION_STRONG_MATCH


def batch_waiting_on_clarify(rows: list[AgentSuggestedMatch]) -> bool:
    return any(normalize_status(row.status) == SUGGESTION_PENDING_CLARIFY for row in rows)


async def upsert_from_evaluations(
    db: AsyncSession,
    *,
    request_id: str,
    evaluations: list[PairEvaluation],
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
            if row.status == SUGGESTION_INTERESTED:
                row.evaluation = payload
                row.updated_at = now
                rows.append(row)
                continue
            if row.status == SUGGESTION_SKIPPED and next_status == SUGGESTION_SKIPPED:
                row.evaluation = payload
                row.updated_at = now
                rows.append(row)
                continue
            if row.status == SUGGESTION_PRESENTED:
                if next_status == SUGGESTION_SKIPPED:
                    row.status = SUGGESTION_SKIPPED
                    await _stamp_card(db, row, SUGGESTION_SKIPPED)
                else:
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


def _preview_for_row(row: AgentSuggestedMatch, provided: str) -> str:
    text = redact_identity(provided.strip())
    if text:
        return text
    evaluation = row.evaluation if isinstance(row.evaluation, dict) else {}
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


async def present_candidates(
    db: AsyncSession,
    *,
    session_id: str,
    request: AgentRequest,
    items: list[dict[str, str]],
) -> list[AgentSuggestedMatch]:
    cap = max_pairs()
    existing_rows = await list_suggestions(db, request.id)
    if batch_waiting_on_clarify(existing_rows):
        raise SuggestionError(
            "Ask the pending clarifying questions first. Present every strong_match "
            "candidate together after they answer."
        )
    previews = {
        str(item.get("candidate_id") or "").strip(): str(item.get("preview") or "")
        for item in items
        if str(item.get("candidate_id") or "").strip()
    }
    by_candidate = {row.candidate_request_id: row for row in existing_rows}
    for candidate_id in previews:
        row = by_candidate.get(candidate_id)
        if row is None:
            raise SuggestionError("Evaluate that candidate before presenting it.")
        if normalize_status(row.status) not in {
            SUGGESTION_STRONG_MATCH,
            SUGGESTION_PRESENTED,
        }:
            raise SuggestionError("That candidate is not ready to present.")
    to_show: list[AgentSuggestedMatch] = []
    seen: set[str] = set()
    for row in existing_rows:
        status = normalize_status(row.status)
        if status != SUGGESTION_STRONG_MATCH:
            continue
        if row.candidate_request_id in seen:
            continue
        seen.add(row.candidate_request_id)
        to_show.append(row)
        if len(to_show) >= cap:
            break
    if not to_show:
        raise SuggestionError("No strong_match candidates are ready to present.")

    cards: list[dict[str, Any]] = []
    for row in to_show:
        candidate = await db.get(AgentRequest, row.candidate_request_id)
        if candidate is None:
            raise SuggestionError("Candidate request not found.")
        cards.append(
            {
                "suggestion_id": row.id,
                "candidate_id": row.candidate_request_id,
                "preview": _preview_for_row(row, previews.get(row.candidate_request_id, "")),
                "status": SUGGESTION_PRESENTED,
                "images": await _card_images(db, session_id, row, candidate),
            }
        )
    payload = {
        "kind": CANDIDATE_CARDS_KIND,
        "version": CARD_VERSION,
        "candidates": cards,
    }
    message = None
    shared_ids = {row.card_message_id for row in to_show if row.card_message_id}
    if len(shared_ids) == 1:
        existing_id = next(iter(shared_ids))
        message = await db.get(AgentMessage, existing_id)
        if message is not None and message.session_id != session_id:
            message = None
    if message is None:
        message = AgentMessage(
            session_id=session_id,
            role="assistant",
            content=json.dumps(payload, ensure_ascii=False),
            match_id=None,
        )
        db.add(message)
        await db.flush()
    else:
        message.content = json.dumps(payload, ensure_ascii=False)
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


async def _card_images(
    db: AsyncSession,
    session_id: str,
    row: AgentSuggestedMatch,
    candidate: AgentRequest,
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(AgentAttachment).where(
            AgentAttachment.session_id == candidate.session_id,
            AgentAttachment.status == "ready",
        )
    )
    images: list[dict[str, Any]] = []
    for attachment in result.scalars().all():
        if not is_image_type(attachment.content_type):
            continue
        if attachment.share_class == SHARE_PUBLIC:
            images.append(
                {
                    "attachment_id": attachment.id,
                    "share_class": SHARE_PUBLIC,
                    "label": model_facing_label(attachment),
                    "content_url": (
                        f"/broker/sessions/{session_id}/suggestions/{row.id}"
                        f"/attachments/{attachment.id}/content"
                    ),
                    "requestable": False,
                }
            )
        elif attachment.share_class == SHARE_PERSONAL:
            images.append(
                {
                    "attachment_id": attachment.id,
                    "share_class": SHARE_PERSONAL,
                    "label": model_facing_label(attachment),
                    "blur_url": (
                        f"/broker/sessions/{session_id}/suggestions/{row.id}"
                        f"/attachments/{attachment.id}/content?variant=blur"
                    ),
                    "requestable": True,
                }
            )
    return images[:6]


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


def suggestion_content_path(
    session_id: str,
    suggestion_id: str,
    attachment_id: str,
    *,
    variant: str | None = None,
) -> str:
    path = (
        f"/broker/sessions/{session_id}/suggestions/{suggestion_id}"
        f"/attachments/{attachment_id}/content"
    )
    if variant:
        return f"{path}?variant={variant}"
    return path
