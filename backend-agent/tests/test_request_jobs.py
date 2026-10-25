from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.context import ToolContext
from app.agents.tools.match_tools import build_match_tools
from app.agents.tools.request_tools import build_request_tools
from app.agents.tools.search_tools import build_search_tools
from app.db.models import AgentRequest
from app.services.request_jobs import (
    JOB_EVALUATE,
    JOB_INDEX,
    JOB_SCREEN,
    _is_parse_failure,
    _run_kind_with_parse_retry,
    enqueue_followup_screen,
    enqueue_request_job,
    job_packet,
    latest_screen_candidate_ids,
    resolve_evaluate_ids,
    schedule_request_jobs,
)
from app.services.workflow import MATCH_OPEN


def _request(request_id: str, user_id: str, *, indexed: bool = False) -> AgentRequest:
    return AgentRequest(
        id=request_id,
        session_id=f"sess-{request_id}",
        user_id=user_id,
        title="Need a match",
        summary="Looking",
        details={},
        status="open",
        indexed_at=datetime.now(UTC) if indexed else None,
    )


def _ctx(source: AgentRequest) -> ToolContext:
    return ToolContext(
        db=AsyncMock(),
        profile=MagicMock(id="user-a"),
        session=MagicMock(id=source.session_id),
        request=source,
        user_message=None,
        trigger="user_message",
    )


@pytest.mark.asyncio
async def test_index_request_queues_and_does_not_index_inline() -> None:
    source = _request("req-aaaaaa", "user-a")
    ctx = _ctx(source)
    job = SimpleNamespace(id="job-index", status="queued")
    with (
        patch(
            "app.agents.tools.request_tools.enqueue_request_job",
            AsyncMock(return_value=job),
        ) as enqueue,
        patch("app.agents.tools.request_tools.open_match_count", AsyncMock(return_value=0)),
        patch("app.rag.indexer.index_request", AsyncMock()) as indexer,
    ):
        tool = next(item for item in build_request_tools(ctx) if item.name == "index_request")
        result = json.loads(await tool.ainvoke({}))
    assert result["ok"] is True
    assert result["accepted"] is True
    assert result["job_id"] == "job-index"
    assert "Indexing started" in result["outcome"]
    assert ctx.queued_jobs == ["job-index"]
    enqueue.assert_awaited()
    indexer.assert_not_called()
    assert "trigger_agent" not in enqueue.await_args.kwargs or enqueue.await_args.kwargs.get("trigger_agent") is False


@pytest.mark.asyncio
async def test_search_queues_and_omits_candidate_briefs() -> None:
    source = _request("req-aaaaaa", "user-a", indexed=True)
    ctx = _ctx(source)
    job = SimpleNamespace(id="job-screen", status="queued")
    with patch(
        "app.agents.tools.search_tools.enqueue_request_job",
        AsyncMock(return_value=job),
    ) as enqueue:
        tool = next(item for item in build_search_tools(ctx) if item.name == "search_counterparties")
        result = json.loads(await tool.ainvoke({}))
    assert result["ok"] is True
    assert result["accepted"] is True
    assert result["count"] is None
    assert "candidates" not in result
    assert "objective" not in result
    assert ctx.queued_jobs == ["job-screen"]
    enqueue.assert_awaited()
    assert enqueue.await_args.kwargs["kind"] == JOB_SCREEN


def test_evaluate_pair_is_a_broker_tool() -> None:
    source = _request("req-aaaaaa", "user-a", indexed=True)
    names = [item.name for item in build_search_tools(_ctx(source))]
    assert "evaluate_pair" in names
    assert "search_counterparties" in names
    assert "present_candidates" in names


@pytest.mark.asyncio
async def test_evaluate_pair_queues_without_briefs() -> None:
    source = _request("req-aaaaaa", "user-a", indexed=True)
    ctx = _ctx(source)
    job = SimpleNamespace(id="job-eval", status="queued")
    with (
        patch(
            "app.agents.tools.search_tools.resolve_evaluate_ids",
            AsyncMock(return_value=["cand-1"]),
        ),
        patch(
            "app.agents.tools.search_tools.enqueue_request_job",
            AsyncMock(return_value=job),
        ) as enqueue,
    ):
        tool = next(item for item in build_search_tools(ctx) if item.name == "evaluate_pair")
        result = json.loads(await tool.ainvoke({"candidate_ids": ["cand-1"]}))
    assert result["ok"] is True
    assert result["count"] == 1
    assert "candidates" not in result
    assert "Counterpart briefs are not listed here" in result["outcome"]
    assert ctx.queued_jobs == ["job-eval"]
    enqueue.assert_awaited()
    assert enqueue.await_args.kwargs["kind"] == JOB_EVALUATE
    assert enqueue.await_args.kwargs["candidate_ids"] == ["cand-1"]


@pytest.mark.asyncio
async def test_evaluate_pair_stores_view_filters_without_clearing_index() -> None:
    source = _request("req-aaaaaa", "user-a", indexed=True)
    indexed_at = source.indexed_at
    source.view_filters = []
    ctx = _ctx(source)
    job = SimpleNamespace(id="job-eval", status="queued")
    with (
        patch(
            "app.agents.tools.search_tools.resolve_evaluate_ids",
            AsyncMock(return_value=["cand-1"]),
        ),
        patch(
            "app.agents.tools.search_tools.enqueue_request_job",
            AsyncMock(return_value=job),
        ),
    ):
        tool = next(item for item in build_search_tools(ctx) if item.name == "evaluate_pair")
        result = json.loads(
            await tool.ainvoke({"candidate_ids": ["cand-1"], "filters": ["Kharadi"]})
        )
    assert result["ok"] is True
    assert result["view_filters"] == ["Kharadi"]
    assert source.view_filters == ["Kharadi"]
    assert source.indexed_at == indexed_at
    assert source.details == {}


@pytest.mark.asyncio
async def test_update_request_clears_view_filters() -> None:
    source = _request("req-aaaaaa", "user-a", indexed=True)
    source.view_filters = ["Kharadi"]
    ctx = _ctx(source)
    with patch(
        "app.agents.tools.request_tools.generate_request_copy",
        AsyncMock(return_value=("Title", "Summary")),
    ):
        tool = next(item for item in build_request_tools(ctx) if item.name == "update_request")
        result = json.loads(await tool.ainvoke({"location": "Pune"}))
    assert result["ok"] is True
    assert source.view_filters == []
    assert source.indexed_at is None


def test_search_tools_do_not_include_search_again() -> None:
    source = _request("req-aaaaaa", "user-a", indexed=True)
    names = [item.name for item in build_search_tools(_ctx(source))]
    assert "search_again" not in names
    assert "search_counterparties" in names


@pytest.mark.asyncio
async def test_get_match_events_omits_other_brief() -> None:
    source = _request("req-aaaaaa", "user-a")
    other = _request("req-bbbbbb", "user-b")
    match = SimpleNamespace(id="match-1", status=MATCH_OPEN, notebook={})
    ctx = _ctx(source)
    with (
        patch(
            "app.agents.tools.match_tools.owned_match",
            AsyncMock(return_value=(match, source, other, source)),
        ),
        patch("app.agents.tools.match_tools.load_events", AsyncMock(return_value=[])),
        patch("app.agents.tools.match_tools.match_notebook", return_value={}),
    ):
        tool = next(item for item in build_match_tools(ctx) if item.name == "get_match_events")
        result = json.loads(await tool.ainvoke({}))
    assert result["ok"] is True
    assert "other_brief" not in result
    assert result["match_id"] == "match-1"


def test_job_packet_has_ids_not_briefs() -> None:
    job = SimpleNamespace(
        id="job-1",
        kind=JOB_INDEX,
        status="done",
        payload={
            "indexed": True,
            "searchable": True,
            "candidate_ids": ["cand-1"],
            "count": 1,
            "objective": "should not leak",
        },
    )
    packet = job_packet(job)
    assert packet["job_id"] == "job-1"
    assert packet["candidate_ids"] == ["cand-1"]
    assert packet["count"] == 1
    assert "objective" not in packet


def test_schedule_request_jobs_does_not_run_inline() -> None:
    created: list[object] = []

    def fake_create_task(coro, name=None):
        created.append(name)
        coro.close()

    with patch("app.services.request_jobs.asyncio.create_task", side_effect=fake_create_task):
        schedule_request_jobs(["job-1", "job-1"])
    assert created == ["request-job-job-1"]


def test_job_packet_includes_screen_case_ids() -> None:
    job = SimpleNamespace(
        id="job-2",
        kind=JOB_SCREEN,
        status="done",
        payload={
            "candidate_ids": ["cand-1", "cand-2", "cand-3"],
            "strong_match": ["cand-1"],
            "possible_match": ["cand-2"],
            "pending_clarify": ["cand-3"],
            "pending_questions": ["Can you relocate?"],
        },
    )
    packet = job_packet(job)
    assert packet["strong_match"] == ["cand-1"]
    assert packet["possible_match"] == ["cand-2"]
    assert packet["pending_clarify"] == ["cand-3"]
    assert packet["pending_questions"] == ["Can you relocate?"]


def test_parse_failure_detects_schema_echo() -> None:
    assert _is_parse_failure(ValueError("Failed to parse PairEvaluation from completion"))
    assert not _is_parse_failure(RuntimeError("This brief is not indexed."))


@pytest.mark.asyncio
async def test_silent_parse_retry_reruns_once() -> None:
    calls = {"n": 0}

    async def fake_run(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("Failed to parse PairEvaluation from completion")
        return {"count": 1, "strong_match": ["cand-1"]}

    job = SimpleNamespace(id="job-screen", kind=JOB_SCREEN)
    with patch("app.services.request_jobs._run_kind", fake_run):
        payload = await _run_kind_with_parse_retry(AsyncMock(), job, MagicMock())
    assert calls["n"] == 2
    assert payload["strong_match"] == ["cand-1"]


@pytest.mark.asyncio
async def test_index_job_does_not_trigger_agent() -> None:
    source = _request("req-aaaaaa", "user-a")
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    with (
        patch("app.services.request_jobs._fail_open_jobs", AsyncMock()),
        patch("app.services.request_jobs._open_job", AsyncMock(return_value=None)),
    ):
        job = await enqueue_request_job(
            db,
            kind=JOB_INDEX,
            request=source,
            session_id=source.session_id,
            user_id=source.user_id,
            trigger_agent=True,
        )
    added = db.add.call_args[0][0]
    assert added is job
    assert added.kind == JOB_INDEX
    assert added.trigger_agent is False


@pytest.mark.asyncio
async def test_index_complete_enqueues_screen() -> None:
    source = _request("req-aaaaaa", "user-a", indexed=True)
    job = SimpleNamespace(id="job-screen")
    with patch(
        "app.services.request_jobs.enqueue_request_job",
        AsyncMock(return_value=job),
    ) as enqueue:
        ids = await enqueue_followup_screen(AsyncMock(), source)
    assert ids == ["job-screen"]
    assert enqueue.await_args.kwargs["kind"] == JOB_SCREEN
    assert enqueue.await_args.kwargs["trigger_agent"] is True
    assert enqueue.await_args.kwargs["request"] is source


@pytest.mark.asyncio
async def test_latest_screen_ids_use_failed_job_when_it_stored_them() -> None:
    failed = SimpleNamespace(
        payload={"candidate_ids": ["cand-new-1", "cand-new-2"]},
        finished_at=datetime.now(UTC),
    )
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [failed]
    db.execute = AsyncMock(return_value=result)
    ids = await latest_screen_candidate_ids(db, "req-bbbbbb")
    assert ids == ["cand-new-1", "cand-new-2"]


@pytest.mark.asyncio
async def test_resolve_evaluate_ids_skips_stale_skipped_last_search() -> None:
    db = AsyncMock()
    with (
        patch(
            "app.services.request_jobs.latest_screen_candidate_ids",
            AsyncMock(return_value=["cand-old-skip"]),
        ),
        patch(
            "app.services.request_jobs.skipped_candidate_ids",
            AsyncMock(return_value={"cand-old-skip"}),
        ),
        patch(
            "app.services.request_jobs.list_suggestions",
            AsyncMock(
                return_value=[
                    SimpleNamespace(candidate_request_id="cand-inbound"),
                ]
            ),
        ) as listed,
    ):
        ids = await resolve_evaluate_ids(db, "req-bbbbbb", None)
    assert ids == ["cand-inbound"]
    listed.assert_awaited()
