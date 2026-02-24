"""Embedding backends for hybrid memory retrieval."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Iterable

from loguru import logger


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity for two vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=False))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return dot / (norm_a * norm_b)


class MemoryEmbedder:
    """Embedding abstraction with pluggable providers.

    Provider values:
    - "" or "hash": local deterministic hash embedding (default)
    - "sentence-transformers/<model>": optional backend if package is installed
    """

    def __init__(self, provider: str = "", dim: int = 192):
        self.requested_provider = (provider or "hash").strip()
        self.dim = max(dim, 64)
        self._st_model = None
        self._active_provider = "hash"

        if self.requested_provider.startswith("sentence-transformers/"):
            model_name = self.requested_provider.split("/", 1)[1].strip()
            if model_name:
                try:
                    from sentence_transformers import SentenceTransformer  # type: ignore

                    self._st_model = SentenceTransformer(model_name)
                    self._active_provider = self.requested_provider
                except Exception as exc:
                    logger.warning(
                        "Embedding provider '{}' unavailable ({}), falling back to hash",
                        self.requested_provider,
                        exc,
                    )

    @property
    def provider_name(self) -> str:
        return self._active_provider

    @staticmethod
    def _normalize(vec: list[float]) -> list[float]:
        norm = math.sqrt(sum(v * v for v in vec))
        if norm <= 0:
            return vec
        return [v / norm for v in vec]

    @staticmethod
    def _tokens(text: str) -> Iterable[str]:
        for tok in re.findall(r"[a-zA-Z0-9_\-]+", text.lower()):
            if len(tok) > 1:
                yield tok

    @staticmethod
    def _char_trigrams(text: str) -> Iterable[str]:
        cleaned = re.sub(r"\s+", " ", text.lower()).strip()
        if len(cleaned) < 3:
            if cleaned:
                yield cleaned
            return
        for idx in range(len(cleaned) - 2):
            yield cleaned[idx: idx + 3]

    def _hash_embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = list(self._tokens(text))
        trigrams = list(self._char_trigrams(text))

        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[bucket] += sign * 1.2

        for tri in trigrams:
            digest = hashlib.blake2b(tri.encode("utf-8"), digest_size=16).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[bucket] += sign * 0.5

        return self._normalize(vec)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        if self._st_model is not None:
            vectors = self._st_model.encode(texts, normalize_embeddings=True)
            return [list(map(float, row)) for row in vectors]

        return [self._hash_embed_one(text) for text in texts]
