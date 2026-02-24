"""Embedding backends for hybrid memory retrieval."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from pathlib import Path
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


class VectorIndexBackend:
    """Storage adapter for vector indexes."""

    name = "json"

    def load_items(self, provider: str) -> dict[str, list[float]]:
        raise NotImplementedError

    def save_items(self, provider: str, items: dict[str, list[float]], dim: int) -> None:
        raise NotImplementedError


class JsonVectorIndexBackend(VectorIndexBackend):
    """JSON-file vector index backend."""

    name = "json"

    def __init__(self, index_dir: Path):
        self.index_dir = index_dir

    @staticmethod
    def provider_slug(provider: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9_\-]+", "_", provider.strip().lower())
        return slug or "hash"

    def index_file(self, provider: str) -> Path:
        return self.index_dir / f"vectors_{self.provider_slug(provider)}.json"

    def load_items(self, provider: str) -> dict[str, list[float]]:
        path = self.index_file(provider)
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            raw_items = payload.get("items") if isinstance(payload, dict) else None
            if not isinstance(raw_items, dict):
                return {}
            out: dict[str, list[float]] = {}
            for key, value in raw_items.items():
                if not isinstance(key, str) or not isinstance(value, list):
                    continue
                out[key] = [float(v) for v in value]
            return out
        except Exception:
            logger.warning("Failed to parse JSON vector index '{}', treating as empty", path)
            return {}

    def save_items(self, provider: str, items: dict[str, list[float]], dim: int) -> None:
        path = self.index_file(provider)
        payload = {
            "provider": provider,
            "backend": self.name,
            "updated_at": "",
            "dim": dim,
            "items": items,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class SqliteVectorIndexBackend(VectorIndexBackend):
    """SQLite vector index backend (portable fallback for sqlite-vss mode)."""

    name = "sqlite"

    def __init__(self, index_dir: Path):
        self.db_path = index_dir / "vectors.sqlite3"
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vectors (
                    provider TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    vector_json TEXT NOT NULL,
                    dim INTEGER NOT NULL,
                    PRIMARY KEY (provider, event_id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_vectors_provider ON vectors(provider)"
            )

    def load_items(self, provider: str) -> dict[str, list[float]]:
        out: dict[str, list[float]] = {}
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT event_id, vector_json FROM vectors WHERE provider = ?",
                (provider,),
            )
            for event_id, vector_json in cursor.fetchall():
                try:
                    row = json.loads(vector_json)
                except Exception:
                    continue
                if isinstance(event_id, str) and isinstance(row, list):
                    out[event_id] = [float(v) for v in row]
        return out

    def save_items(self, provider: str, items: dict[str, list[float]], dim: int) -> None:
        rows = [(provider, event_id, json.dumps(vector, ensure_ascii=False), dim) for event_id, vector in items.items()]
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM vectors WHERE provider = ?", (provider,))
            conn.executemany(
                "INSERT INTO vectors(provider, event_id, vector_json, dim) VALUES (?, ?, ?, ?)",
                rows,
            )
            conn.commit()


class FaissVectorIndexBackend(VectorIndexBackend):
    """FAISS vector index backend (optional dependency)."""

    name = "faiss"

    def __init__(self, index_dir: Path):
        self.index_dir = index_dir

    @staticmethod
    def provider_slug(provider: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9_\-]+", "_", provider.strip().lower())
        return slug or "hash"

    def _index_path(self, provider: str) -> Path:
        return self.index_dir / f"vectors_{self.provider_slug(provider)}.faiss"

    def _meta_path(self, provider: str) -> Path:
        return self.index_dir / f"vectors_{self.provider_slug(provider)}_meta.json"

    def load_items(self, provider: str) -> dict[str, list[float]]:
        try:
            faiss = __import__("faiss")  # type: ignore
            np = __import__("numpy")
        except Exception:
            return {}

        index_path = self._index_path(provider)
        meta_path = self._meta_path(provider)
        if not index_path.exists() or not meta_path.exists():
            return {}

        try:
            ids_payload = json.loads(meta_path.read_text(encoding="utf-8"))
            ids = ids_payload.get("ids") if isinstance(ids_payload, dict) else None
            if not isinstance(ids, list):
                return {}
            ids = [str(x) for x in ids]

            index = faiss.read_index(str(index_path))
            count = index.ntotal
            if count <= 0:
                return {}
            vectors = np.vstack([index.reconstruct(i) for i in range(count)])
            out: dict[str, list[float]] = {}
            for event_id, row in zip(ids, vectors.tolist(), strict=False):
                out[event_id] = [float(v) for v in row]
            return out
        except Exception:
            logger.warning("Failed to read FAISS index for provider '{}', treating as empty", provider)
            return {}

    def save_items(self, provider: str, items: dict[str, list[float]], dim: int) -> None:
        try:
            faiss = __import__("faiss")  # type: ignore
            np = __import__("numpy")
        except Exception:
            return

        ids = list(items.keys())
        index_path = self._index_path(provider)
        meta_path = self._meta_path(provider)

        if not ids or dim <= 0:
            if index_path.exists():
                index_path.unlink()
            if meta_path.exists():
                meta_path.unlink()
            return

        matrix = np.array([items[event_id] for event_id in ids], dtype="float32")
        index = faiss.IndexFlatIP(dim)
        index.add(matrix)
        faiss.write_index(index, str(index_path))
        meta_path.write_text(json.dumps({"provider": provider, "ids": ids}, ensure_ascii=False), encoding="utf-8")


def create_vector_backend(requested: str, *, index_dir: Path) -> VectorIndexBackend:
    """Create requested vector backend with graceful fallback behavior."""
    normalized = (requested or "json").strip().lower()

    if normalized in {"", "json"}:
        return JsonVectorIndexBackend(index_dir)

    if normalized in {"sqlite", "sqlite-vss"}:
        return SqliteVectorIndexBackend(index_dir)

    if normalized == "faiss":
        try:
            __import__("faiss")  # type: ignore
            __import__("numpy")
            return FaissVectorIndexBackend(index_dir)
        except Exception as exc:
            logger.warning("Vector backend '{}' unavailable ({}), falling back to json", normalized, exc)
            return JsonVectorIndexBackend(index_dir)

    if normalized == "auto":
        try:
            __import__("faiss")  # type: ignore
            __import__("numpy")
            return FaissVectorIndexBackend(index_dir)
        except Exception:
            return SqliteVectorIndexBackend(index_dir)

    logger.warning("Unknown vector backend '{}', falling back to json", normalized)
    return JsonVectorIndexBackend(index_dir)
