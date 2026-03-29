"""Vector memory store using Qdrant + embedding/rerank APIs."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import httpx
from loguru import logger
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, Filter, FieldCondition, MatchValue


class VectorMemoryStore:
    """RAG memory: embed text chunks, store in Qdrant, retrieve via search + rerank."""

    _BATCH_SIZE = 32
    _OVER_FETCH_MULTIPLIER = 3

    def __init__(
        self,
        qdrant_url: str,
        collection: str,
        embedding_model: str,
        rerank_model: str | None = None,
        rerank_top_k: int = 5,
        score_threshold: float = 0.7,
        api_key: str = "",
        api_base: str = "http://localhost:11434/v1",
    ):
        self.collection = collection
        self.embedding_model = embedding_model
        self.rerank_model = rerank_model
        self.rerank_top_k = rerank_top_k
        self.score_threshold = score_threshold
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = QdrantClient(url=qdrant_url, timeout=10)
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        """Create collection if it does not exist."""
        try:
            exists = self._client.collection_exists(self.collection)
        except Exception:
            logger.warning("RAG: cannot reach Qdrant")
            return
        if not exists:
            self._client.create_collection(
                collection_name=self.collection,
                vectors_config={"size": 1536, "distance": Distance.COSINE},
            )
            logger.info("RAG: created collection '{}'", self.collection)

    def health_check(self) -> bool:
        """Return True if Qdrant is reachable and collection exists."""
        try:
            return self._client.collection_exists(self.collection)
        except Exception:
            return False

    def _point_id(self, session_key: str, text: str) -> str:
        """Deterministic point ID from session_key + text hash."""
        raw = f"{session_key}:{text}"
        return hashlib.md5(raw.encode()).hexdigest()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Batch embed texts via OpenAI-compatible API."""
        all_vectors: list[list[float]] = []
        for i in range(0, len(texts), self._BATCH_SIZE):
            batch = texts[i : i + self._BATCH_SIZE]
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(
                        f"{self.api_base}/embeddings",
                        json={"model": self.embedding_model, "input": batch},
                        headers={**self._headers, "Content-Type": "application/json"},
                    )
                    resp.raise_for_status()
                    data = resp.json()["data"]
                    data.sort(key=lambda x: x["index"])
                    all_vectors.extend(d["embedding"] for d in data)
            except Exception:
                logger.warning("RAG: embedding failed for batch {}/{}", i, len(texts))
                all_vectors.extend([[0.0] * 1536 for _ in batch])
        return all_vectors

    async def store(self, session_key: str, chunks: list[str]) -> None:
        """Embed chunks and upsert into Qdrant."""
        if not chunks:
            return
        try:
            vectors = await self.embed(chunks)
            ts = datetime.now(timezone.utc).isoformat()
            points = [
                PointStruct(
                    id=self._point_id(session_key, chunk),
                    vector=vector,
                    payload={
                        "session_key": session_key,
                        "text": chunk,
                        "timestamp": ts,
                    },
                )
                for chunk, vector in zip(chunks, vectors)
            ]
            self._client.upsert(collection_name=self.collection, points=points)
            # Only log if significant chunks stored
            if len(chunks) > 5:
                logger.debug("RAG: stored {} chunks for {}", len(chunks), session_key)
        except Exception:
            logger.warning("RAG: store failed for {}", session_key)

    async def retrieve(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Embed query, search Qdrant, rerank, return top-K results."""
        try:
            query_vector = await self.embed([query])
            if not query_vector or not query_vector[0]:
                logger.warning("RAG: embed returned empty vector")
                return []
        except Exception:
            logger.warning("RAG: failed to embed query")
            return []

        fetch_k = top_k * self._OVER_FETCH_MULTIPLIER
        try:
            hits = self._client.query_points(
                collection_name=self.collection,
                query=query_vector[0],
                limit=fetch_k,
                with_payload=True,
            ).points
            # Only log if no hits or many hits
            if len(hits) == 0:
                logger.debug("RAG: no hits found")
            elif len(hits) > 10:
                logger.debug("RAG: retrieved {} hits", len(hits))
        except Exception:
            logger.warning("RAG: Qdrant search failed")
            return []

        if not hits:
            logger.debug("RAG: no hits found")
            return []

        texts = [hit.payload["text"] for hit in hits if hit.payload.get("text")]
        logger.debug("RAG: extracted {} texts, rerank_model={}", len(texts), self.rerank_model)

        if self.rerank_model and texts:
            reranked = await self._rerank(query, texts)
            if reranked:
                return reranked[:top_k]

        results = []
        for hit in hits[:top_k]:
            if hit.score >= self.score_threshold:
                results.append({
                    "text": hit.payload.get("text", ""),
                    "score": hit.score,
                })
        return results

    async def _rerank(self, query: str, documents: list[str]) -> list[dict[str, Any]] | None:
        """Rerank documents via API. Returns sorted list or None on failure."""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self.api_base}/rerank",
                    json={
                        "model": self.rerank_model,
                        "query": query,
                        "documents": documents,
                    },
                    headers={**self._headers, "Content-Type": "application/json"},
                )
                resp.raise_for_status()
                results = resp.json().get("results", [])
                out = []
                for r in sorted(results, key=lambda x: x["relevance_score"], reverse=True):
                    idx = r["index"]
                    if 0 <= idx < len(documents):
                        out.append({
                            "text": documents[idx],
                            "score": r["relevance_score"],
                        })
                return out
        except Exception:
            logger.warning("RAG: rerank failed, falling back to Qdrant scores")
            return None

    def delete(self, session_key: str) -> None:
        """Delete all points for a given session_key."""
        try:
            self._client.delete(
                collection_name=self.collection,
                points_selector=Filter(
                    must=[FieldCondition(key="session_key", match=MatchValue(value=session_key))]
                ),
            )
            logger.debug("RAG: deleted memories for {}", session_key)
        except Exception:
            logger.warning("RAG: delete failed for {}", session_key)
