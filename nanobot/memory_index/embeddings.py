"""Embedding providers for the memory index."""

from __future__ import annotations

import asyncio
import hashlib
from abc import ABC, abstractmethod

import httpx


class EmbeddingUnavailableError(Exception):
    """Raised when the embedding provider cannot be reached."""


class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Embeds text via the Ollama /api/embeddings endpoint."""

    def __init__(self, base_url: str, model: str, batch_size: int = 16) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.batch_size = batch_size
        self._cache: dict[str, list[float]] = {}

    def _cache_key(self, text: str) -> str:
        return hashlib.sha256(f"{self.model}:{text}".encode()).hexdigest()

    async def _embed_one(self, client: httpx.AsyncClient, text: str) -> list[float]:
        r = await client.post(
            f"{self.base_url}/api/embeddings",
            json={"model": self.model, "prompt": text},
        )
        r.raise_for_status()
        return r.json()["embedding"]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding per text. Uses in-memory cache to avoid re-embedding."""
        results: list[list[float] | None] = [None] * len(texts)
        uncached: list[tuple[int, str]] = []

        for i, text in enumerate(texts):
            key = self._cache_key(text)
            if key in self._cache:
                results[i] = self._cache[key]
            else:
                uncached.append((i, text))

        if uncached:
            try:
                # process uncached in chunks of batch_size, concurrent within each chunk
                for chunk_start in range(0, len(uncached), self.batch_size):
                    chunk = uncached[chunk_start : chunk_start + self.batch_size]
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        vecs = await asyncio.gather(
                            *[self._embed_one(client, text) for _, text in chunk]
                        )
                    for (i, text), vec in zip(chunk, vecs):
                        self._cache[self._cache_key(text)] = vec
                        results[i] = vec
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                raise EmbeddingUnavailableError(f"Ollama unreachable: {e}") from e
            except httpx.HTTPStatusError as e:
                raise EmbeddingUnavailableError(
                    f"Ollama HTTP error {e.response.status_code}: {e}"
                ) from e

        assert all(r is not None for r in results), "BUG: some embeddings were not set"
        return results  # type: ignore[return-value]
