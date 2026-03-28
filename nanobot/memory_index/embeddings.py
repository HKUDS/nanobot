"""Embedding providers for the memory index."""

from __future__ import annotations

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
                async with httpx.AsyncClient(timeout=30.0) as client:
                    for i, text in uncached:
                        r = await client.post(
                            f"{self.base_url}/api/embeddings",
                            json={"model": self.model, "prompt": text},
                        )
                        r.raise_for_status()
                        vec = r.json()["embedding"]
                        self._cache[self._cache_key(text)] = vec
                        results[i] = vec
            except httpx.ConnectError as e:
                raise EmbeddingUnavailableError(f"Ollama unreachable: {e}") from e
            except httpx.TimeoutException as e:
                raise EmbeddingUnavailableError(f"Ollama timed out: {e}") from e
            except Exception as e:
                raise EmbeddingUnavailableError(f"Embedding failed: {e}") from e

        return [r for r in results if r is not None]
