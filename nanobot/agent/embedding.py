"""Async embedding client for OpenAI-compatible APIs (e.g. NVIDIA NIM)."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import httpx
from loguru import logger

if TYPE_CHECKING:
    from nanobot.config.schema import EmbeddingConfig


class AsyncRateLimiter:
    """Token bucket style rate limiter for requests per minute."""

    def __init__(self, rpm: int):
        self.rpm = max(1, rpm)
        self.interval = 60.0 / self.rpm
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            if elapsed < self.interval:
                await asyncio.sleep(self.interval - elapsed)
            self._last = time.monotonic()


class EmbeddingClient:
    """
    Async client for OpenAI-compatible /v1/embeddings endpoint.
    Rate-limited and retried on transient errors.
    """

    def __init__(self, config: EmbeddingConfig):
        base = (config.api_base or "").rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        self.api_base = base
        self.model = config.model or ""
        self.dimensions = getattr(config, "dimensions", 1024)
        self.api_key = getattr(config, "api_key", "") or ""
        rpm = getattr(config, "rpm_limit", 40)
        self._limiter = AsyncRateLimiter(rpm)
        self._client: httpx.AsyncClient | None = None
        logger.info(
            "EmbeddingClient: {} model={} dims={} rpm={}",
            self.api_base or "(no base)",
            self.model or "(no model)",
            self.dimensions,
            rpm,
        )

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(
                base_url=self.api_base,
                headers=headers,
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def embed(self, text: str, input_type: str = "query") -> list[float]:
        """Embed a single text. Uses input_type='query' for search, 'passage' for storage."""
        results = await self.embed_batch([text], batch_size=1, input_type=input_type)
        return results[0] if results else []

    async def embed_batch(
        self,
        texts: list[str],
        batch_size: int = 10,
        input_type: str = "query",
    ) -> list[list[float]]:
        """
        Embed multiple texts with batching and rate limiting.
        input_type: 'query' for retrieval queries, 'passage' for documents being stored.
        """
        if not texts or not self.api_base or not self.model:
            logger.debug("EmbeddingClient: embed_batch skipped (empty texts or missing api_base/model)")
            return []

        logger.debug("EmbeddingClient: embed_batch size={} batch_size={} input_type={}", len(texts), batch_size, input_type)
        all_vectors = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            await self._limiter.acquire()
            vecs = await self._embed_batch_with_retry(batch, input_type=input_type)
            all_vectors.extend(vecs)
        return all_vectors

    async def _embed_batch_with_retry(self, texts: list[str], input_type: str = "query") -> list[list[float]]:
        """Call embeddings API with exponential backoff retry on transient errors."""
        last_err = None
        for attempt in range(4):
            try:
                return await self._call_embeddings(texts, input_type=input_type)
            except httpx.HTTPStatusError as e:
                last_err = e
                if e.response.status_code in (401, 403, 404):
                    logger.error("EmbeddingClient: non-retryable HTTP {} — check api_base/model/key", e.response.status_code)
                    raise
                if e.response.status_code in (400, 422):
                    body = e.response.text[:200] if e.response else ""
                    logger.error("EmbeddingClient: HTTP {} — {}", e.response.status_code, body)
                    raise
                logger.warning("EmbeddingClient: attempt {} failed (HTTP {}), retrying in {}s", attempt + 1, e.response.status_code, 2 ** attempt)
                if attempt < 3:
                    await asyncio.sleep(2 ** attempt)
            except httpx.RequestError as e:
                last_err = e
                logger.warning("EmbeddingClient: attempt {} failed ({}), retrying in {}s", attempt + 1, e, 2 ** attempt)
                if attempt < 3:
                    await asyncio.sleep(2 ** attempt)
        if last_err is not None:
            logger.error("EmbeddingClient: all retries exhausted: {}", last_err)
            raise last_err
        return []

    async def _call_embeddings(self, texts: list[str], input_type: str = "query") -> list[list[float]]:
        """Single call to /v1/embeddings."""
        payload: dict = {
            "model": self.model,
            "input": texts,
            "input_type": input_type,
        }

        client = self._get_client()
        resp = await client.post("/v1/embeddings", json=payload)
        resp.raise_for_status()
        logger.debug("EmbeddingClient: /v1/embeddings ok, {} vectors (input_type={})", len(texts), input_type)
        data = resp.json()
        out = []
        for item in data.get("data", []):
            emb = item.get("embedding")
            if isinstance(emb, list):
                out.append([float(x) for x in emb])
            else:
                out.append([])
        return out
