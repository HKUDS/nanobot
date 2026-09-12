"""Lazy local embeddings used by semantic memory."""

from __future__ import annotations

import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol


class Embedder(Protocol):
    @property
    def model_id(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedder:
    """A privacy-preserving ONNX embedder loaded only when first used."""

    def __init__(
        self,
        model_name: str,
        *,
        dimension: int,
        cache_dir: Path,
        threads: int | None = None,
    ) -> None:
        self._model_name = model_name
        self._dimension = dimension
        self._cache_dir = cache_dir
        self._threads = threads
        self._model: Any | None = None
        self._lock = threading.RLock()

    @property
    def model_id(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def _get_model(self) -> Any:
        with self._lock:
            if self._model is None:
                try:
                    from fastembed import TextEmbedding
                except ImportError as exc:  # pragma: no cover - environment-dependent
                    raise RuntimeError(
                        "semantic memory requires the 'semantic-memory' optional dependencies"
                    ) from exc
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                kwargs: dict[str, Any] = {
                    "model_name": self._model_name,
                    "cache_dir": str(self._cache_dir),
                }
                if self._threads is not None:
                    kwargs["threads"] = self._threads
                self._model = TextEmbedding(**kwargs)
                actual = int(self._model.embedding_size)
                if actual != self._dimension:
                    self._model = None
                    raise RuntimeError(
                        f"embedding dimension mismatch: configured {self._dimension}, model {actual}"
                    )
            return self._model

    @staticmethod
    def _vectors(values: Any) -> list[list[float]]:
        return [
            [float(value) for value in vector.tolist()]
            for vector in values
        ]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        with self._lock:
            return self._vectors(self._get_model().passage_embed(list(texts)))

    def embed_query(self, text: str) -> list[float]:
        with self._lock:
            vectors = self._vectors(self._get_model().query_embed([text]))
        if not vectors:
            raise RuntimeError("embedding model returned no query vector")
        return vectors[0]
