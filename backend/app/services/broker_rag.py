from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import chromadb
from chromadb.utils import embedding_functions
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import BrokerRequest
from app.services.structured_llm import (
    invoke_structured_openrouter_model,
    is_llm_configured,
    llm_configuration_error,
)

logger = logging.getLogger(__name__)

SEMANTIC_PROFILE_VERSION = "broker-request-semantic-profile.v1"
RETRIEVAL_PLAN_VERSION = "broker-request-retrieval-plan.v1"


@dataclass(frozen=True)
class VectorCandidate:
    request_id: str
    distance: float | None


class SemanticRequestProfile(BaseModel):
    perspective: Literal["need", "offer", "exchange", "introduction", "general"]
    semantic_document: str = Field(
        min_length=20,
        max_length=5000,
        description=(
            "Detailed privacy-aware request representation for semantic embedding. "
            "It should preserve supported meaning, matching constraints, and the kind "
            "of counterparty that could satisfy or complement the request."
        ),
    )
    desired_counterparty: str = Field(default="", max_length=1200)
    match_signals: list[str] = Field(default_factory=list, max_length=24)
    hard_constraints: list[str] = Field(default_factory=list, max_length=24)
    soft_preferences: list[str] = Field(default_factory=list, max_length=24)
    uncertainties: list[str] = Field(default_factory=list, max_length=24)
    decision_summary: str = Field(
        default="",
        max_length=500,
        description="Audit-safe summary of the semantic profile generation.",
    )


class SemanticRetrievalPlan(BaseModel):
    semantic_query: str = Field(
        min_length=20,
        max_length=4000,
        description=(
            "Semantic candidate-search query describing compatible counterparties or "
            "compatible requests rather than a keyword query."
        ),
    )
    retrieval_focus: str = Field(default="", max_length=600)
    decision_summary: str = Field(
        default="",
        max_length=500,
        description="Audit-safe summary of retrieval planning.",
    )


class BrokerRequestVectorStore:
    """Persistent Chroma index for matchable broker request documents."""

    def __init__(self, persist_dir: str, collection_name: str) -> None:
        vector_dir = Path(persist_dir)
        vector_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(vector_dir))
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"domain": "broker_requests"},
            embedding_function=embedding_functions.DefaultEmbeddingFunction(),
        )

    def upsert_request(
        self,
        broker_request: BrokerRequest,
        profile: SemanticRequestProfile,
    ) -> None:
        """Embed and store the semantic profile document for one ready request."""
        self.collection.upsert(
            ids=[broker_request.id],
            documents=[profile.semantic_document],
            metadatas=[_request_metadata(broker_request, profile)],
        )

    def query_similar(
        self,
        semantic_query: str,
        candidate_count: int,
    ) -> list[VectorCandidate]:
        """Return nearest request ids for a semantic retrieval plan."""
        result = self.collection.query(
            query_texts=[semantic_query],
            n_results=candidate_count,
            include=["distances"],
        )
        ids = result.get("ids", [[]])[0]
        distances = result.get("distances", [[]])[0]
        return [
            VectorCandidate(
                request_id=request_id,
                distance=distances[index] if index < len(distances) else None,
            )
            for index, request_id in enumerate(ids)
        ]


async def index_request(broker_request: BrokerRequest) -> None:
    """Create a semantic request profile, then index it in Chroma."""
    try:
        profile = await build_semantic_request_profile(broker_request)
        broker_request.structured_data = {
            **broker_request.structured_data,
            "semantic_retrieval": {
                "profile_version": SEMANTIC_PROFILE_VERSION,
                "embedding_model": "chroma-default/all-MiniLM-L6-v2",
                "chunking_strategy": "single_request_semantic_document",
                "profile": profile.model_dump(),
            },
        }
        await asyncio.to_thread(
            _get_vector_store().upsert_request,
            broker_request,
            profile,
        )
        broker_request.embedding_status = "embedded"
        logger.info(
            "BrokerAI semantic request indexed",
            extra={
                "request_id": broker_request.id,
                "profile_version": SEMANTIC_PROFILE_VERSION,
                "decision_summary": profile.decision_summary,
            },
        )
    except Exception as exc:
        logger.warning("Broker request embedding failed", exc_info=exc)
        broker_request.embedding_status = "error"


async def retrieve_similar_requests(
    db: AsyncSession,
    broker_request: BrokerRequest,
    limit: int,
) -> list[tuple[BrokerRequest, float | None]]:
    """Plan a semantic search and hydrate vector candidates for downstream ranking."""
    retrieval_plan = await build_semantic_retrieval_plan(broker_request)
    candidates = await asyncio.to_thread(
        _get_vector_store().query_similar,
        retrieval_plan.semantic_query,
        max(limit * 4, limit + 8),
    )
    logger.info(
        "BrokerAI semantic retrieval plan executed",
        extra={
            "request_id": broker_request.id,
            "plan_version": RETRIEVAL_PLAN_VERSION,
            "decision_summary": retrieval_plan.decision_summary,
        },
    )
    candidate_distances = {
        candidate.request_id: candidate.distance
        for candidate in candidates
        if candidate.request_id != broker_request.id
    }
    if not candidate_distances:
        await asyncio.to_thread(
            _write_match_export,
            broker_request,
            retrieval_plan,
            candidates,
            [],
        )
        return []

    result = await db.execute(
        select(BrokerRequest).where(BrokerRequest.id.in_(candidate_distances.keys()))
    )
    requests_by_id = {candidate.id: candidate for candidate in result.scalars().all()}

    matches = []
    for candidate in candidates:
        hydrated = requests_by_id.get(candidate.request_id)
        if hydrated is None:
            continue
        if hydrated.id == broker_request.id or hydrated.user_id == broker_request.user_id:
            continue
        if hydrated.embedding_status != "embedded":
            continue
        matches.append((hydrated, candidate.distance))
        if len(matches) >= limit:
            break
    await asyncio.to_thread(
        _write_match_export,
        broker_request,
        retrieval_plan,
        candidates,
        matches,
    )
    return matches


def _get_vector_store() -> BrokerRequestVectorStore:
    return _cached_vector_store(
        settings.CHROMA_PERSIST_DIR,
        settings.CHROMA_REQUEST_COLLECTION,
    )


@lru_cache(maxsize=1)
def _cached_vector_store(
    persist_dir: str,
    collection_name: str,
) -> BrokerRequestVectorStore:
    return BrokerRequestVectorStore(persist_dir, collection_name)


async def build_semantic_request_profile(
    broker_request: BrokerRequest,
) -> SemanticRequestProfile:
    """Use the LLM to make one match-oriented request document for embedding."""
    _require_llm_configuration()
    return await invoke_structured_openrouter_model(
        parser_model=SemanticRequestProfile,
        system_prompt=_semantic_profile_prompt(),
        human_payload={
            "profile_version": SEMANTIC_PROFILE_VERSION,
            "request": _request_context(broker_request),
            "task": (
                "Create the semantic retrieval profile that will represent this "
                "ready request in the vector index."
            ),
        },
        temperature=0.1,
    )


async def build_semantic_retrieval_plan(
    broker_request: BrokerRequest,
) -> SemanticRetrievalPlan:
    """Use the LLM to build the semantic candidate query before vector search."""
    _require_llm_configuration()
    return await invoke_structured_openrouter_model(
        parser_model=SemanticRetrievalPlan,
        system_prompt=_semantic_retrieval_prompt(),
        human_payload={
            "plan_version": RETRIEVAL_PLAN_VERSION,
            "request": _request_context(broker_request),
            "semantic_profile": _stored_semantic_profile(broker_request),
            "task": (
                "Plan the semantic vector query for finding compatible match "
                "candidates for this request."
            ),
        },
        temperature=0.1,
    )


def _request_metadata(
    broker_request: BrokerRequest,
    profile: SemanticRequestProfile,
) -> dict[str, str]:
    metadata = {
        "request_id": broker_request.id,
        "session_id": broker_request.session_id,
        "user_id": broker_request.user_id,
        "status": broker_request.status,
        "request_type": broker_request.request_type,
        "perspective": profile.perspective,
        "embedding_status": "embedded",
        "profile_version": SEMANTIC_PROFILE_VERSION,
    }
    if broker_request.category:
        metadata["category"] = broker_request.category
    return metadata


def _request_context(broker_request: BrokerRequest) -> dict[str, Any]:
    return {
        "title": broker_request.title,
        "summary": broker_request.summary,
        "request_type": broker_request.request_type,
        "category": broker_request.category,
        "structured_data": broker_request.structured_data,
    }


def _stored_semantic_profile(broker_request: BrokerRequest) -> dict[str, Any] | None:
    semantic_retrieval = broker_request.structured_data.get("semantic_retrieval")
    if not isinstance(semantic_retrieval, dict):
        return None
    profile = semantic_retrieval.get("profile")
    return profile if isinstance(profile, dict) else None


def _write_match_export(
    broker_request: BrokerRequest,
    retrieval_plan: SemanticRetrievalPlan,
    vector_candidates: list[VectorCandidate],
    matches: list[tuple[BrokerRequest, float | None]],
) -> None:
    """Write a local JSON match-debug artifact for MVP retrieval testing."""
    export_dir = Path(settings.MATCH_EXPORT_DIR)
    export_dir.mkdir(parents=True, exist_ok=True)
    export_path = export_dir / f"{_safe_request_filename(broker_request.title)}.json"
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "purpose": "local_match_retrieval_debug",
        "source_request": _request_export_payload(broker_request),
        "retrieval_plan": {
            "plan_version": RETRIEVAL_PLAN_VERSION,
            **retrieval_plan.model_dump(),
        },
        "vector_candidates": [candidate.__dict__ for candidate in vector_candidates],
        "matches": [
            {
                "distance": distance,
                "request": _request_export_payload(match_request),
            }
            for match_request, distance in matches
        ],
    }
    export_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    logger.info(
        "BrokerAI match retrieval export written",
        extra={
            "request_id": broker_request.id,
            "match_count": len(matches),
            "export_path": str(export_path),
        },
    )


def _request_export_payload(broker_request: BrokerRequest) -> dict[str, Any]:
    return {
        "id": broker_request.id,
        "session_id": broker_request.session_id,
        "user_id": broker_request.user_id,
        "status": broker_request.status,
        "request_type": broker_request.request_type,
        "category": broker_request.category,
        "title": broker_request.title,
        "summary": broker_request.summary,
        "embedding_status": broker_request.embedding_status,
        "structured_data": broker_request.structured_data,
    }


def _safe_request_filename(title: str) -> str:
    normalized = re.sub(r"\s+", " ", title.strip())
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", normalized)
    safe = safe.strip(" .")
    return (safe or "broker-request")[:120]


def _require_llm_configuration() -> None:
    if not is_llm_configured():
        raise RuntimeError(
            f"{llm_configuration_error()} for semantic request indexing and retrieval."
        )


def _semantic_profile_prompt() -> str:
    return (
        "You are BrokerAI's semantic request indexer. You prepare the meaning-rich "
        "representation of a ready broker request before it enters the vector index.\n\n"
        "BrokerAI is matching human needs, offers, opportunities, introductions, and "
        "other requests where the best match may be phrased very differently from the "
        "original user message. Convert the supplied structured request into a "
        "professional semantic profile that improves future retrieval. The "
        "semantic_document should be a detailed, natural-language representation of "
        "what the request means, what the user is seeking or offering, the compatible "
        "counterparty or counterpart request, supported constraints, and supported "
        "preferences. Write for embedding quality, not for display and not as a "
        "keyword list.\n\n"
        "Stay grounded in the supplied request. Preserve uncertainty rather than "
        "inventing facts. Do not add personal contact details, credentials, secrets, "
        "private identifiers, or unsupported claims. Keep sensitive information out of "
        "the embedding document unless it is genuinely necessary for matching and was "
        "already supplied.\n\n"
        "Return JSON only. decision_summary must be audit-safe and must not include "
        "hidden reasoning."
    )


def _semantic_retrieval_prompt() -> str:
    return (
        "You are BrokerAI's semantic retrieval planner. Before vector similarity "
        "search, translate one ready request into the semantic search representation "
        "most likely to retrieve compatible match candidates.\n\n"
        "The query is not a database filter and not a paraphrase exercise. Describe "
        "the kinds of counterparties, complementary offers, complementary needs, or "
        "compatible requests that could form a credible match. Carry forward supported "
        "constraints and preferences from the request profile so embeddings can "
        "separate near-miss candidates from genuinely relevant ones. If compatible "
        "matches may be expressed in more than one way, include that semantic breadth "
        "in one coherent query document.\n\n"
        "Do not invent user facts or assume match quality. Do not expose secrets or "
        "contact details in the query plan. Return JSON only. decision_summary must be "
        "audit-safe and must not include hidden reasoning."
    )
