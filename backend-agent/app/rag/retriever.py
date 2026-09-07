from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import clip
from app.db.models import AgentRequest
from app.rag.indexer import build_retrieval_plan
from app.rag.store import get_vector_store
from app.services.workflow import REQUEST_OPEN

logger = logging.getLogger(__name__)


async def retrieve_similar_requests(
    db: AsyncSession,
    request: AgentRequest,
    limit: int,
) -> list[tuple[AgentRequest, float | None]]:
    plan = await build_retrieval_plan(request)
    n_results = max(limit * 4, limit + 8)
    logger.debug(
        "semantic search request_id=%s n_results=%s query=%s",
        request.id,
        n_results,
        clip(plan.query_text, 240),
    )
    candidates = await asyncio.to_thread(
        get_vector_store().query_similar,
        plan.query_text,
        n_results,
    )
    matches: list[tuple[AgentRequest, float | None]] = []
    ids = [candidate.request_id for candidate in candidates if candidate.request_id != request.id]
    logger.info(
        "retrieval ran request_id=%s chroma_hits=%s usable_ids=%s",
        request.id,
        len(candidates),
        len(ids),
    )
    if not ids:
        logger.debug("retrieval empty request_id=%s", request.id)
        return []
    result = await db.execute(select(AgentRequest).where(AgentRequest.id.in_(ids)))
    by_id = {item.id: item for item in result.scalars().all()}
    for candidate in candidates:
        hydrated = by_id.get(candidate.request_id)
        if hydrated is None:
            continue
        if hydrated.id == request.id or hydrated.user_id == request.user_id:
            continue
        if hydrated.status != REQUEST_OPEN or hydrated.indexed_at is None:
            continue
        matches.append((hydrated, candidate.distance))
        if len(matches) >= limit:
            break
    return matches
