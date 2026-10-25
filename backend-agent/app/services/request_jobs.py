"""Fire-and-forget index / screen / evaluate jobs, then a request-lane agent turn."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context import ToolContext
from app.db.models import (
    AgentRequest,
    AgentRequestJob,
    AgentSession,
    UserProfile,
)
from app.db.models.broker import utc_now
from app.db.session import AsyncSessionLocal
from app.rag.indexer import index_request
from app.services.screening import evaluate_candidate_ids, screen_request
from app.services.suggestions import (
    ACTIVE_SUGGESTION_STATUSES,
    list_suggestions,
    max_pairs,
    request_pending_questions,
    skipped_candidate_ids,
)

logger = logging.getLogger(__name__)

JobKind = Literal["index", "screen", "evaluate", "clarify"]

JOB_INDEX = "index"
JOB_SCREEN = "screen"
JOB_EVALUATE = "evaluate"
JOB_CLARIFY = "clarify"

_PARSE_FAILURE_MARKERS = (
    "failed to parse",
    "outputparser",
    "validation error",
    "jsondecodeerror",
    "invalid json",
    "pydantic",
)

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

OPEN_STATUSES = {STATUS_QUEUED, STATUS_RUNNING}

_session_locks: dict[str, asyncio.Lock] = {}


def session_turn_lock(session_id: str) -> asyncio.Lock:
    lock = _session_locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _session_locks[session_id] = lock
    return lock


def schedule_request_jobs(job_ids: list[str]) -> None:
    """Start queued jobs after the current request has committed. Does not wait."""
    for job_id in dict.fromkeys(item for item in job_ids if item):
        asyncio.create_task(_run_request_job(job_id), name=f"request-job-{job_id}")


async def enqueue_request_job(
    db: AsyncSession,
    *,
    kind: JobKind,
    request: AgentRequest,
    session_id: str,
    user_id: str,
    candidate_ids: list[str] | None = None,
    trigger_agent: bool = True,
    replace: bool = False,
) -> AgentRequestJob:
    if kind == JOB_INDEX:
        trigger_agent = False
        await _fail_open_jobs(
            db,
            request.id,
            kinds={JOB_SCREEN, JOB_EVALUATE},
            reason="brief changed",
        )
    if replace:
        await _fail_open_jobs(db, request.id, kinds={kind}, reason="replaced")
    existing = await _open_job(db, request.id, kind)
    if existing is not None:
        return existing
    payload: dict[str, Any] = {}
    if candidate_ids:
        payload["candidate_ids"] = list(dict.fromkeys(candidate_ids))
    job = AgentRequestJob(
        request_id=request.id,
        session_id=session_id,
        user_id=user_id,
        kind=kind,
        status=STATUS_QUEUED,
        payload=payload,
        trigger_agent=trigger_agent,
    )
    db.add(job)
    await db.flush()
    logger.info(
        "request job queued job_id=%s kind=%s request_id=%s",
        job.id,
        kind,
        request.id,
    )
    return job


async def latest_screen_candidate_ids(db: AsyncSession, request_id: str) -> list[str]:
    stmt = (
        select(AgentRequestJob)
        .where(
            AgentRequestJob.request_id == request_id,
            AgentRequestJob.kind == JOB_SCREEN,
            AgentRequestJob.finished_at.is_not(None),
        )
        .order_by(AgentRequestJob.finished_at.desc())
        .limit(8)
    )
    result = await db.execute(stmt)
    for job in result.scalars().all():
        ids = [
            str(item)
            for item in (job.payload or {}).get("candidate_ids") or []
            if str(item).strip()
        ]
        if ids:
            return ids
    return []


async def resolve_evaluate_ids(
    db: AsyncSession,
    request_id: str,
    candidate_ids: list[str] | None,
) -> list[str]:
    ids = [item.strip() for item in (candidate_ids or []) if item and item.strip()]
    if ids:
        return list(dict.fromkeys(ids))[: max_pairs()]
    hits = await latest_screen_candidate_ids(db, request_id)
    skipped = await skipped_candidate_ids(db, request_id)
    fresh = [item for item in hits if item not in skipped]
    if fresh:
        return fresh[: max_pairs()]
    rows = await list_suggestions(db, request_id, statuses=ACTIVE_SUGGESTION_STATUSES)
    return [row.candidate_request_id for row in rows][: max_pairs()]


def job_packet(job: AgentRequestJob | None) -> dict[str, Any] | None:
    if job is None:
        return None
    payload = dict(job.payload or {})
    payload.pop("error", None)
    return {
        "job_id": job.id,
        "kind": job.kind,
        "status": job.status,
        "count": payload.get("count"),
        "candidate_ids": payload.get("candidate_ids") or [],
        "strong_match": payload.get("strong_match") or [],
        "possible_match": payload.get("possible_match") or [],
        "pending_clarify": payload.get("pending_clarify") or [],
        "pending_questions": payload.get("pending_questions") or [],
        "skipped": payload.get("skipped") or [],
        "hold_cards": payload.get("hold_cards"),
        "indexed": payload.get("indexed"),
        "searchable": payload.get("searchable"),
        "view_filters": payload.get("view_filters") or [],
        "error": payload.get("error") if job.status == STATUS_FAILED else None,
    }


async def _open_job(db: AsyncSession, request_id: str, kind: str) -> AgentRequestJob | None:
    stmt = (
        select(AgentRequestJob)
        .where(
            AgentRequestJob.request_id == request_id,
            AgentRequestJob.kind == kind,
            AgentRequestJob.status.in_(OPEN_STATUSES),
        )
        .order_by(AgentRequestJob.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _fail_open_jobs(
    db: AsyncSession,
    request_id: str,
    *,
    kinds: set[str],
    reason: str,
) -> None:
    stmt = select(AgentRequestJob).where(
        AgentRequestJob.request_id == request_id,
        AgentRequestJob.kind.in_(kinds),
        AgentRequestJob.status.in_(OPEN_STATUSES),
    )
    result = await db.execute(stmt)
    now = datetime.now(UTC)
    for job in result.scalars().all():
        payload = dict(job.payload or {})
        payload["error"] = reason
        job.payload = payload
        job.status = STATUS_FAILED
        job.finished_at = now
        logger.info(
            "request job superseded job_id=%s kind=%s reason=%s",
            job.id,
            job.kind,
            reason,
        )


async def _run_request_job(job_id: str) -> None:
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(AgentRequestJob)
                .where(AgentRequestJob.id == job_id)
                .with_for_update()
            )
            job = result.scalar_one_or_none()
            if job is None or job.status != STATUS_QUEUED:
                return
            job.status = STATUS_RUNNING
            job.started_at = utc_now()
            await db.commit()
        await _execute_job(job_id)
    except Exception:
        logger.exception("request job failed job_id=%s", job_id)
        try:
            async with AsyncSessionLocal() as db:
                job = await db.get(AgentRequestJob, job_id)
                if job is not None and job.status == STATUS_RUNNING:
                    payload = dict(job.payload or {})
                    payload["error"] = "job failed"
                    job.payload = payload
                    job.status = STATUS_FAILED
                    job.finished_at = utc_now()
                    await db.commit()
        except Exception:
            logger.exception("request job fail-mark failed job_id=%s", job_id)


async def _execute_job(job_id: str) -> None:
    extra_ids: list[str] = []
    outreach_jobs: list[Any] = []
    trigger = False
    session_id = ""
    kind = ""
    status = ""
    async with AsyncSessionLocal() as db:
        job = await db.get(AgentRequestJob, job_id)
        if job is None or job.status != STATUS_RUNNING:
            return
        request = await db.get(AgentRequest, job.request_id)
        if request is None:
            job.status = STATUS_FAILED
            job.finished_at = utc_now()
            job.payload = {**(job.payload or {}), "error": "request missing"}
            await db.commit()
            return
        try:
            payload = await _run_kind_with_parse_retry(db, job, request)
            outreach_jobs = list(payload.pop("_outreach", []) or [])
            job.payload = payload
            job.status = STATUS_DONE
            job.finished_at = utc_now()
            if job.kind == JOB_INDEX:
                extra_ids = await enqueue_followup_screen(db, request)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "request job work failed job_id=%s kind=%s error=%s",
                job.id,
                job.kind,
                exc,
            )
            job.payload = {**(job.payload or {}), "error": str(exc)}
            job.status = STATUS_FAILED
            job.finished_at = utc_now()
        await db.commit()
        trigger = job.trigger_agent and job.status in {STATUS_DONE, STATUS_FAILED}
        if job.kind == JOB_INDEX and job.status == STATUS_FAILED:
            trigger = True
        session_id = job.session_id
        kind = job.kind
        status = job.status
    logger.info("request job finished job_id=%s kind=%s status=%s", job_id, kind, status)
    if extra_ids:
        schedule_request_jobs(extra_ids)
    if outreach_jobs:
        from app.services.outreach import schedule_outreach

        schedule_outreach(outreach_jobs)
    if trigger:
        async with session_turn_lock(session_id):
            await _run_completion_turn(job_id)


async def _run_kind(
    db: AsyncSession,
    job: AgentRequestJob,
    request: AgentRequest,
) -> dict[str, Any]:
    if job.kind == JOB_INDEX:
        await index_request(request)
        return {
            "indexed": request.indexed_at is not None,
            "searchable": request.indexed_at is not None,
            "request_id": request.id,
        }
    if request.indexed_at is None:
        raise RuntimeError("This brief is not indexed.")
    if job.kind == JOB_SCREEN:
        return await screen_request(db, request, job=job)
    if job.kind == JOB_EVALUATE:
        ids = await resolve_evaluate_ids(
            db,
            request.id,
            (job.payload or {}).get("candidate_ids"),
        )
        if not ids:
            return screening_empty()
        return await evaluate_candidate_ids(db, request, ids)
    if job.kind == JOB_CLARIFY:
        return await clarify_packet(db, request)
    raise RuntimeError(f"Unknown job kind {job.kind}")


def _is_parse_failure(exc: BaseException) -> bool:
    blob = f"{type(exc).__name__} {exc}".lower()
    return any(marker in blob for marker in _PARSE_FAILURE_MARKERS)


async def _run_kind_with_parse_retry(
    db: AsyncSession,
    job: AgentRequestJob,
    request: AgentRequest,
) -> dict[str, Any]:
    try:
        return await _run_kind(db, job, request)
    except Exception as exc:
        if job.kind not in {JOB_SCREEN, JOB_EVALUATE} or not _is_parse_failure(exc):
            raise
        logger.warning(
            "request job silent parse retry job_id=%s kind=%s error=%s",
            job.id,
            job.kind,
            exc,
        )
        return await _run_kind(db, job, request)


async def clarify_packet(db: AsyncSession, request: AgentRequest) -> dict[str, Any]:
    questions = request_pending_questions(request)
    return {
        "count": len(questions),
        "candidate_ids": [],
        "strong_match": [],
        "possible_match": [],
        "pending_clarify": [],
        "pending_questions": questions,
        "skipped": [],
        "errors": [],
        "cap": max_pairs(),
        "hold_cards": False,
    }


async def enqueue_followup_screen(
    db: AsyncSession,
    request: AgentRequest,
) -> list[str]:
    """After a successful index, run search and pair evaluation before waking the broker."""
    if request.indexed_at is None:
        return []
    job = await enqueue_request_job(
        db,
        kind=JOB_SCREEN,
        request=request,
        session_id=request.session_id,
        user_id=request.user_id,
        trigger_agent=True,
    )
    logger.info(
        "index chained to screen request_id=%s job_id=%s",
        request.id,
        job.id,
    )
    return [job.id]


def screening_empty() -> dict[str, Any]:
    return {
        "count": 0,
        "candidate_ids": [],
        "strong_match": [],
        "possible_match": [],
        "pending_clarify": [],
        "pending_questions": [],
        "skipped": [],
        "errors": [],
        "cap": max_pairs(),
        "hold_cards": False,
    }


async def _run_completion_turn(job_id: str) -> None:
    from app.agents.runtime import run_broker_turn
    from app.services.notify import mail_jobs_for_outreach, schedule_mail
    from app.services.outreach import schedule_outreach

    try:
        async with AsyncSessionLocal() as db:
            job = await db.get(AgentRequestJob, job_id)
            if job is None or job.status not in {STATUS_DONE, STATUS_FAILED}:
                return
            session = await db.get(AgentSession, job.session_id)
            profile = await db.get(UserProfile, job.user_id)
            request = await db.get(AgentRequest, job.request_id)
            if session is None or profile is None or request is None:
                logger.info("job trigger skipped job_id=%s reason=missing_session", job_id)
                return
            ctx = ToolContext(
                db=db,
                profile=profile,
                session=session,
                request=request,
                user_message=None,
                trigger="request_ready",
                background_job=job_packet(job),
            )
            logger.info(
                "job trigger start job_id=%s kind=%s session=%s",
                job.id,
                job.kind,
                session.id,
            )
            replies = await run_broker_turn(ctx)
            mail = await mail_jobs_for_outreach(
                db,
                session=session,
                profile=profile,
                replies=replies,
            )
            if ctx.queued_mail:
                mail.extend(ctx.queued_mail)
            await db.commit()
            schedule_outreach(list(ctx.queued_outreach))
            schedule_mail(mail)
            schedule_request_jobs(list(ctx.queued_jobs))
    except Exception:
        logger.exception("job trigger failed job_id=%s", job_id)
