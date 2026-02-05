"""Vector memory store using SQLite with embeddings stored as BLOBs."""

import json
import re
import sqlite3
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

VALID_NAMESPACE_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')
MAX_CONTENT_LENGTH = 8192


@dataclass
class MemoryItem:
    id: str
    content: str
    embedding: list[float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    access_count: int = 0
    priority: float = 0.5
    namespace: str = "default"


class RateLimiter:
    def __init__(self, max_requests_per_minute: int = 3000):
        self.max_requests = max_requests_per_minute
        self.tokens = float(max_requests_per_minute)
        self.last_update = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                elapsed = now - self.last_update
                self.tokens = min(self.max_requests, self.tokens + (elapsed * self.max_requests / 60.0))
                self.last_update = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
            time.sleep(0.1)


class EmbeddingService:
    def __init__(self, model: str = "text-embedding-3-small", max_requests_per_minute: int = 3000, cache_size: int = 1000):
        self.model = model
        self._dimension: int | None = None
        self._rate_limiter = RateLimiter(max_requests_per_minute)
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_size = cache_size
        self._cache_lock = threading.Lock()

    def embed(self, text: str) -> list[float]:
        with self._cache_lock:
            if text in self._cache:
                self._cache.move_to_end(text)
                return self._cache[text]
        self._rate_limiter.acquire()
        import litellm
        try:
            response = litellm.embedding(model=self.model, input=[text])
            embedding = response.data[0]["embedding"]
            with self._cache_lock:
                self._cache[text] = embedding
                if len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
            return embedding
        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            raise

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            self._dimension = len(self.embed("test"))
        return self._dimension


class VectorMemoryStore:
    MAX_MEMORIES = 1000

    def __init__(self, db_path: Path, base_dir: Path | None = None, embedding_service: EmbeddingService | None = None, max_memories: int = 1000, namespace: str = "default"):
        db_path = Path(db_path)
        if base_dir:
            base_dir = Path(base_dir).resolve()
            resolved_path = (base_dir / db_path).resolve()
            if not str(resolved_path).startswith(str(base_dir)):
                raise ValueError(f"db_path must be within {base_dir}")
            self.db_path = resolved_path
        else:
            if db_path.is_absolute():
                raise ValueError("db_path must be relative when base_dir not specified")
            if '..' in db_path.parts:
                raise ValueError("db_path cannot contain parent directory references")
            self.db_path = db_path.resolve()

        self._lock = threading.RLock()
        self.embedding_service = embedding_service or EmbeddingService()
        self.max_memories = max_memories
        self.namespace = self._validate_namespace(namespace)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_db()

    def close(self) -> None:
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def _validate_namespace(self, namespace: str) -> str:
        if not VALID_NAMESPACE_PATTERN.match(namespace):
            raise ValueError("Invalid namespace: must be alphanumeric with _ or -, max 64 chars")
        return namespace

    def _init_db(self) -> None:
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    embedding BLOB,
                    metadata TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    access_count INTEGER DEFAULT 0,
                    priority REAL DEFAULT 0.5,
                    namespace TEXT DEFAULT 'default'
                )
            """)
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_updated ON memories(updated_at DESC)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_namespace ON memories(namespace)")
            self._conn.commit()

    def add(self, content: str, metadata: dict[str, Any] | None = None, namespace: str | None = None) -> MemoryItem:
        if not isinstance(content, str):
            raise TypeError("content must be a string")
        content = content.strip()
        if not content:
            raise ValueError("content cannot be empty")
        if len(content) > MAX_CONTENT_LENGTH:
            raise ValueError(f"content exceeds maximum length of {MAX_CONTENT_LENGTH}")

        namespace = self._validate_namespace(namespace or self.namespace)
        embedding = self.embedding_service.embed(content)

        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                memory_id = str(uuid.uuid4())[:8]
                embedding_blob = sqlite3.Binary(np.array(embedding, dtype=np.float32).tobytes()) if HAS_NUMPY else sqlite3.Binary(json.dumps(embedding).encode("utf-8"))
                now = datetime.now()
                item_metadata = metadata or {}
                importance = item_metadata.get("importance", 0.5)
                priority = max(0.0, min(1.0, importance * 0.4 + 0.3))
                self._conn.execute(
                    "INSERT INTO memories (id, content, embedding, metadata, created_at, updated_at, access_count, priority, namespace) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (memory_id, content, embedding_blob, json.dumps(item_metadata), now.isoformat(), now.isoformat(), 0, priority, namespace),
                )
                self._conn.commit()
                self._prune_if_needed(namespace)
                logger.debug(f"Added memory {memory_id} to namespace '{namespace}': {content[:50]}...")
                return MemoryItem(
                    id=memory_id,
                    content=content,
                    embedding=embedding,
                    metadata=item_metadata,
                    created_at=now,
                    updated_at=now,
                    priority=priority,
                    namespace=namespace,
                )
            except Exception:
                self._conn.rollback()
                raise

    def update(self, memory_id: str, content: str, metadata: dict[str, Any] | None = None, namespace: str | None = None) -> MemoryItem | None:
        if not isinstance(content, str):
            raise TypeError("content must be a string")
        content = content.strip()
        if not content:
            raise ValueError("content cannot be empty")
        if len(content) > MAX_CONTENT_LENGTH:
            raise ValueError(f"content exceeds maximum length of {MAX_CONTENT_LENGTH}")

        namespace = self._validate_namespace(namespace or self.namespace)

        with self._lock:
            existing = self.get(memory_id, namespace)
            if not existing:
                return None

        embedding = self.embedding_service.embed(content) if content != existing.content else existing.embedding

        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                embedding_blob = sqlite3.Binary(np.array(embedding, dtype=np.float32).tobytes()) if HAS_NUMPY else sqlite3.Binary(json.dumps(embedding).encode("utf-8"))
                now = datetime.now()
                final_metadata = metadata if metadata is not None else existing.metadata
                importance = final_metadata.get("importance", 0.5)
                age_days = (now - existing.created_at).total_seconds() / 86400
                recency = max(0.0, 1.0 - (age_days / 30.0))
                access_score = min(1.0, (existing.access_count ** 0.5) / 10.0)
                priority = max(0.0, min(1.0, importance * 0.4 + recency * 0.3 + access_score * 0.3))
                self._conn.execute(
                    "UPDATE memories SET content = ?, embedding = ?, metadata = ?, updated_at = ?, priority = ? WHERE id = ? AND namespace = ?",
                    (content, embedding_blob, json.dumps(final_metadata), now.isoformat(), priority, memory_id, namespace),
                )
                self._conn.commit()
                return MemoryItem(
                    id=memory_id,
                    content=content,
                    embedding=embedding,
                    metadata=final_metadata,
                    created_at=existing.created_at,
                    updated_at=now,
                    access_count=existing.access_count,
                    priority=priority,
                    namespace=namespace,
                )
            except Exception:
                self._conn.rollback()
                raise

    def delete(self, memory_id: str, namespace: str | None = None) -> bool:
        namespace = self._validate_namespace(namespace or self.namespace)
        with self._lock:
            cursor = self._conn.execute("DELETE FROM memories WHERE id = ? AND namespace = ?", (memory_id, namespace))
            self._conn.commit()
            return cursor.rowcount > 0

    def get(self, memory_id: str, namespace: str | None = None) -> MemoryItem | None:
        namespace = self._validate_namespace(namespace or self.namespace)
        with self._lock:
            cursor = self._conn.execute("SELECT * FROM memories WHERE id = ? AND namespace = ?", (memory_id, namespace))
            row = cursor.fetchone()
            if not row:
                return None
            columns = [desc[0] for desc in cursor.description]
            data = dict(zip(columns, row))
            embedding = None
            if data.get("embedding"):
                embedding = np.frombuffer(data["embedding"], dtype=np.float32).tolist() if HAS_NUMPY else json.loads(data["embedding"].decode("utf-8"))
            return MemoryItem(
                id=data["id"],
                content=data["content"],
                embedding=embedding,
                metadata=json.loads(data.get("metadata", "{}")),
                created_at=datetime.fromisoformat(data["created_at"]),
                updated_at=datetime.fromisoformat(data["updated_at"]),
                access_count=data.get("access_count", 0),
                priority=data.get("priority", 0.5),
                namespace=data.get("namespace", "default"),
            )

    def search(self, query: str, top_k: int = 5, threshold: float = 0.5, namespace: str | None = None, priority_weight: float = 0.3) -> list[tuple[MemoryItem, float]]:
        namespace = self._validate_namespace(namespace or self.namespace)
        query_embedding = self.embedding_service.embed(query)

        with self._lock:
            cursor = self._conn.execute(
                "SELECT id, content, embedding, metadata, created_at, updated_at, access_count, priority, namespace FROM memories WHERE namespace = ?",
                (namespace,),
            )
            rows = cursor.fetchall()
            if not rows:
                return []
            results: list[tuple[MemoryItem, float, float]] = []
            for row in rows:
                if not row[2]:
                    continue
                embedding = np.frombuffer(row[2], dtype=np.float32).tolist() if HAS_NUMPY else json.loads(row[2].decode("utf-8"))
                similarity = self._cosine_similarity(query_embedding, embedding)
                if similarity >= threshold:
                    priority = row[7] if row[7] is not None else 0.5
                    combined_score = similarity * (1 - priority_weight) + priority * priority_weight
                    item = MemoryItem(
                        id=row[0],
                        content=row[1],
                        embedding=embedding,
                        metadata=json.loads(row[3] or "{}"),
                        created_at=datetime.fromisoformat(row[4]),
                        updated_at=datetime.fromisoformat(row[5]),
                        access_count=row[6] or 0,
                        priority=priority,
                        namespace=row[8] or "default",
                    )
                    results.append((item, similarity, combined_score))
            results.sort(key=lambda x: x[2], reverse=True)
            return [(item, sim) for item, sim, _ in results[:top_k]]

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        if HAS_NUMPY:
            a_arr, b_arr = np.array(a), np.array(b)
            dot = np.dot(a_arr, b_arr)
            norm_a, norm_b = np.linalg.norm(a_arr), np.linalg.norm(b_arr)
        else:
            dot = sum(x * y for x, y in zip(a, b))
            norm_a = sum(x * x for x in a) ** 0.5
            norm_b = sum(x * x for x in b) ** 0.5
        return 0.0 if norm_a == 0 or norm_b == 0 else float(dot / (norm_a * norm_b))

    def _prune_if_needed(self, namespace: str | None = None) -> None:
        namespace = namespace or self.namespace
        with self._lock:
            cursor = self._conn.execute("SELECT COUNT(*) FROM memories WHERE namespace = ?", (namespace,))
            count = cursor.fetchone()[0]
            if count > self.max_memories:
                excess = count - self.max_memories
                cursor = self._conn.execute(
                    "SELECT id FROM memories WHERE namespace = ? ORDER BY priority ASC, updated_at ASC LIMIT ?",
                    (namespace, excess),
                )
                ids_to_delete = [row[0] for row in cursor.fetchall()]
                for memory_id in ids_to_delete:
                    self._conn.execute("DELETE FROM memories WHERE id = ? AND namespace = ?", (memory_id, namespace))
                self._conn.commit()
                logger.info(f"Pruned {len(ids_to_delete)} old memories from namespace '{namespace}'")

    def count(self, namespace: str | None = None) -> int:
        namespace = self._validate_namespace(namespace or self.namespace)
        with self._lock:
            cursor = self._conn.execute("SELECT COUNT(*) FROM memories WHERE namespace = ?", (namespace,))
            return cursor.fetchone()[0]
