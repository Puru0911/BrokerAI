from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import chromadb
from chromadb.utils import embedding_functions

from app.core.config import settings
from app.db.models import AgentRequest


@dataclass(frozen=True)
class VectorCandidate:
    request_id: str
    distance: float | None


class RequestVectorStore:
    def __init__(self, persist_dir: str, collection_name: str) -> None:
        vector_dir = Path(persist_dir)
        vector_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(vector_dir))
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"domain": "agent_requests"},
            embedding_function=embedding_functions.DefaultEmbeddingFunction(),
        )

    def upsert_request(
        self,
        request: AgentRequest,
        semantic_document: str,
        domain: str | None = None,
        location: str | None = None,
    ) -> None:
        metadata: dict[str, Any] = {
            "request_id": request.id,
            "session_id": request.session_id,
            "user_id": request.user_id,
            "status": request.status,
        }
        if domain:
            metadata["domain"] = str(domain)[:120]
        if location:
            metadata["location"] = str(location)[:160]
        self.collection.upsert(
            ids=[request.id],
            documents=[semantic_document],
            metadatas=[metadata],
        )

    def delete_request(self, request_id: str) -> None:
        """Remove one request's embedding. Missing ids are ignored."""
        self.collection.delete(ids=[request_id])

    def query_similar(
        self,
        semantic_query: str,
        candidate_count: int,
    ) -> list[VectorCandidate]:
        result = self.collection.query(
            query_texts=[semantic_query],
            n_results=max(candidate_count, 1),
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


@lru_cache(maxsize=1)
def _cached_vector_store(persist_dir: str, collection_name: str) -> RequestVectorStore:
    return RequestVectorStore(persist_dir, collection_name)


def get_vector_store() -> RequestVectorStore:
    return _cached_vector_store(settings.CHROMA_PERSIST_DIR, settings.CHROMA_REQUEST_COLLECTION)


def request_kind(request: AgentRequest) -> str | None:
    from app.services.living_request import living_request_dict

    domain = living_request_dict(request.details).get("domain")
    return domain if domain else None
