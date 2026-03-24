# Memory Storage Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace mem0/Qdrant with unified SQLite (sqlite-vec + FTS5), direct embeddings, and single-tool consolidation.

**Architecture:** Three phases — (1) build new foundation modules without touching existing code, (2) migrate consumers one-by-one to the new modules, (3) delete old modules and clean up. Each task produces a passing test suite. The knowledge graph is untouched (Phase 2 future work).

**Tech Stack:** Python 3.10+, SQLite (WAL mode), sqlite-vec, FTS5, ONNX Runtime, pytest, asyncio.

---

## File Map

| Action | File | Task |
|--------|------|------|
| Create | `nanobot/agent/memory/unified_db.py` | 1 |
| Create | `nanobot/agent/memory/embedder.py` | 2 |
| Create | `nanobot/agent/memory/migration.py` | 3 |
| Create | `tests/test_unified_db.py` | 1 |
| Create | `tests/test_embedder.py` | 2 |
| Create | `tests/test_migration.py` | 3 |
| Modify | `nanobot/agent/memory/ingester.py` | 4 |
| Modify | `nanobot/agent/memory/retriever.py` | 5 |
| Modify | `nanobot/agent/memory/consolidation_pipeline.py` | 6 |
| Modify | `nanobot/agent/memory/constants.py` | 6 |
| Modify | `nanobot/agent/memory/snapshot.py` | 7 |
| Modify | `nanobot/agent/memory/maintenance.py` | 7 |
| Modify | `nanobot/agent/memory/conflicts.py` | 7 |
| Modify | `nanobot/agent/memory/profile_io.py` | 7 |
| Modify | `nanobot/agent/memory/context_assembler.py` | 8 |
| Modify | `nanobot/agent/memory/store.py` | 9 |
| Delete | `nanobot/agent/memory/mem0_adapter.py` | 10 |
| Delete | `nanobot/agent/memory/retrieval.py` | 10 |
| Delete | `nanobot/agent/memory/persistence.py` | 10 |
| Modify | `nanobot/agent/memory/rollout.py` | 10 |
| Modify | `nanobot/agent/memory/__init__.py` | 10 |
| Modify | `pyproject.toml` | 10 |
| Modify | `tests/test_ingester.py` | 10 |
| Modify | `tests/test_maintenance.py` | 10 |
| Modify | `tests/test_snapshot.py` | 10 |
| Modify | `tests/test_retriever.py` | 10 |
| Modify | `tests/test_memory_hybrid.py` | 10 |
| Modify | `tests/test_mem0_adapter_branches.py` → delete | 10 |
| Modify | `tests/test_mem0_adapter_init_paths.py` → delete | 10 |
| Modify | `tests/test_mem0_adapter_fallback.py` → delete | 10 |
| Modify | `tests/test_memory_helper_wave5.py` | 10 |
| Modify | `tests/test_coverage_push_wave6.py` | 10 |
| Modify | `nanobot/agent/memory/eval.py` | 7 |
| No change | `nanobot/agent/memory/profile_correction.py` | — |
| No change | `nanobot/agent/memory/retrieval_planner.py` | — |

---

## Task 1: UnifiedMemoryDB

**Goal:** Create `unified_db.py` — SQLite database with events, FTS5, sqlite-vec, profile, history, and snapshots tables. Pure storage layer, no embedding logic.

**Context:** This replaces both `persistence.py` (file I/O) and `mem0_adapter.py` (vector store). The schema uses FTS5 content-sync triggers and sqlite-vec for KNN search. All methods are synchronous — callers use `asyncio.to_thread()` when needed. `{dims}` is set at creation time.

**Files:**
- Create: `nanobot/agent/memory/unified_db.py`
- Create: `tests/test_unified_db.py`

- [ ] **Step 1: Write failing tests for UnifiedMemoryDB**

```python
# tests/test_unified_db.py
"""Tests for UnifiedMemoryDB — SQLite + FTS5 + sqlite-vec storage."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.memory.unified_db import UnifiedMemoryDB


class TestSchemaCreation:
    def test_creates_database_file(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=384)
        assert (tmp_path / "memory.db").exists()
        db.close()

    def test_wal_mode_enabled(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=384)
        result = db._conn.execute("PRAGMA journal_mode").fetchone()
        assert result[0] == "wal"
        db.close()

    def test_tables_created(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=384)
        tables = {
            row[0]
            for row in db._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "events" in tables
        assert "profile" in tables
        assert "history" in tables
        assert "snapshots" in tables
        db.close()


class TestEventCRUD:
    def test_insert_event_and_read_back(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        event = {
            "id": "evt-1",
            "type": "fact",
            "summary": "User likes coffee",
            "timestamp": "2026-03-23T12:00:00Z",
            "source": "test",
            "status": "active",
            "metadata": json.dumps({"topic": "preference"}),
            "created_at": "2026-03-23T12:00:00Z",
        }
        embedding = [0.1, 0.2, 0.3, 0.4]
        db.insert_event(event, embedding)
        events = db.read_events(limit=10)
        assert len(events) == 1
        assert events[0]["id"] == "evt-1"
        assert events[0]["summary"] == "User likes coffee"
        db.close()

    def test_insert_event_without_embedding(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        event = {
            "id": "evt-2",
            "type": "fact",
            "summary": "No embedding event",
            "timestamp": "2026-03-23T12:00:00Z",
            "source": "test",
            "status": "active",
            "metadata": None,
            "created_at": "2026-03-23T12:00:00Z",
        }
        db.insert_event(event, embedding=None)
        events = db.read_events(limit=10)
        assert len(events) == 1
        db.close()

    def test_read_events_respects_limit(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        for i in range(5):
            db.insert_event(
                {
                    "id": f"evt-{i}",
                    "type": "fact",
                    "summary": f"Event {i}",
                    "timestamp": f"2026-03-23T12:0{i}:00Z",
                    "source": "test",
                    "status": "active",
                    "metadata": None,
                    "created_at": f"2026-03-23T12:0{i}:00Z",
                },
                embedding=None,
            )
        events = db.read_events(limit=3)
        assert len(events) == 3
        db.close()


class TestFTS5Search:
    def test_search_fts_finds_matching_event(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.insert_event(
            {
                "id": "evt-coffee",
                "type": "fact",
                "summary": "User prefers dark roast coffee",
                "timestamp": "2026-03-23T12:00:00Z",
                "source": "test",
                "status": "active",
                "metadata": None,
                "created_at": "2026-03-23T12:00:00Z",
            },
            embedding=None,
        )
        results = db.search_fts("coffee", k=5)
        assert len(results) >= 1
        assert any("coffee" in r["summary"].lower() for r in results)
        db.close()

    def test_search_fts_returns_empty_for_no_match(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.insert_event(
            {
                "id": "evt-1",
                "type": "fact",
                "summary": "User likes tea",
                "timestamp": "2026-03-23T12:00:00Z",
                "source": "test",
                "status": "active",
                "metadata": None,
                "created_at": "2026-03-23T12:00:00Z",
            },
            embedding=None,
        )
        results = db.search_fts("nonexistent_xyz", k=5)
        assert len(results) == 0
        db.close()


class TestVectorSearch:
    def test_search_vector_returns_nearest(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.insert_event(
            {
                "id": "evt-a",
                "type": "fact",
                "summary": "Alpha event",
                "timestamp": "2026-03-23T12:00:00Z",
                "source": "test",
                "status": "active",
                "metadata": None,
                "created_at": "2026-03-23T12:00:00Z",
            },
            embedding=[1.0, 0.0, 0.0, 0.0],
        )
        db.insert_event(
            {
                "id": "evt-b",
                "type": "fact",
                "summary": "Beta event",
                "timestamp": "2026-03-23T12:01:00Z",
                "source": "test",
                "status": "active",
                "metadata": None,
                "created_at": "2026-03-23T12:01:00Z",
            },
            embedding=[0.0, 1.0, 0.0, 0.0],
        )
        # Query near Alpha
        results = db.search_vector([0.9, 0.1, 0.0, 0.0], k=1)
        assert len(results) == 1
        assert results[0]["id"] == "evt-a"
        db.close()

    def test_search_vector_skips_events_without_embedding(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.insert_event(
            {
                "id": "evt-no-vec",
                "type": "fact",
                "summary": "No vector",
                "timestamp": "2026-03-23T12:00:00Z",
                "source": "test",
                "status": "active",
                "metadata": None,
                "created_at": "2026-03-23T12:00:00Z",
            },
            embedding=None,
        )
        results = db.search_vector([1.0, 0.0, 0.0, 0.0], k=5)
        assert len(results) == 0
        db.close()


class TestProfileCRUD:
    def test_write_and_read_profile(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.write_profile("preferences", {"likes": ["coffee", "hiking"]})
        result = db.read_profile("preferences")
        assert result == {"likes": ["coffee", "hiking"]}
        db.close()

    def test_read_missing_profile_returns_none(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        result = db.read_profile("nonexistent")
        assert result is None
        db.close()

    def test_write_profile_overwrites(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.write_profile("key", {"v": 1})
        db.write_profile("key", {"v": 2})
        assert db.read_profile("key") == {"v": 2}
        db.close()


class TestHistoryAndSnapshots:
    def test_append_and_read_history(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.append_history("First entry")
        db.append_history("Second entry")
        entries = db.read_history(limit=10)
        assert len(entries) == 2
        assert entries[0]["entry"] == "First entry"
        db.close()

    def test_write_and_read_snapshot(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.write_snapshot("current", "# Memory\n\nSome content")
        result = db.read_snapshot("current")
        assert result == "# Memory\n\nSome content"
        db.close()

    def test_read_missing_snapshot_returns_empty(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        result = db.read_snapshot("nonexistent")
        assert result == ""
        db.close()


class TestMetadataSearch:
    def test_search_by_metadata_filters_by_type(self, tmp_path: Path):
        db = UnifiedMemoryDB(tmp_path / "memory.db", dims=4)
        db.insert_event(
            {
                "id": "evt-pref",
                "type": "preference",
                "summary": "Likes coffee",
                "timestamp": "2026-03-23T12:00:00Z",
                "source": "test",
                "status": "active",
                "metadata": json.dumps({"topic": "food"}),
                "created_at": "2026-03-23T12:00:00Z",
            },
            embedding=None,
        )
        db.insert_event(
            {
                "id": "evt-task",
                "type": "task",
                "summary": "Fix bug",
                "timestamp": "2026-03-23T12:01:00Z",
                "source": "test",
                "status": "active",
                "metadata": json.dumps({"topic": "work"}),
                "created_at": "2026-03-23T12:01:00Z",
            },
            embedding=None,
        )
        results = db.search_by_metadata(memory_type="preference", k=5)
        assert len(results) == 1
        assert results[0]["type"] == "preference"
        db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_unified_db.py -v
```
Expected: `ImportError: cannot import name 'UnifiedMemoryDB'`

- [ ] **Step 3: Verify sqlite-vec is installable**

```bash
pip install sqlite-vec
python -c "import sqlite_vec; print('sqlite-vec OK')"
```
Expected: `sqlite-vec OK`. If this fails on Windows, document the issue and investigate alternatives before proceeding.

- [ ] **Step 4: Implement UnifiedMemoryDB**

```python
# nanobot/agent/memory/unified_db.py
"""Unified SQLite storage for the memory subsystem.

Replaces events.jsonl + profile.json + mem0/Qdrant + HISTORY.md + MEMORY.md
with a single SQLite database (memory.db). Uses FTS5 for keyword search
and sqlite-vec for vector search.

All public methods are synchronous. Callers that need async compatibility
wrap calls with asyncio.to_thread().
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import re

import sqlite_vec

from .helpers import _utc_now_iso

__all__ = ["UnifiedMemoryDB"]

# FTS5 content-sync triggers — keep events_fts in sync with events table.
_FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS events_ai AFTER INSERT ON events BEGIN
    INSERT INTO events_fts(rowid, summary) VALUES (new.rowid, new.summary);
END;
CREATE TRIGGER IF NOT EXISTS events_ad AFTER DELETE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, summary)
        VALUES('delete', old.rowid, old.summary);
END;
CREATE TRIGGER IF NOT EXISTS events_au AFTER UPDATE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, summary)
        VALUES('delete', old.rowid, old.summary);
    INSERT INTO events_fts(rowid, summary) VALUES (new.rowid, new.summary);
END;
"""


class UnifiedMemoryDB:
    """Single-file SQLite database for all memory storage.

    Parameters
    ----------
    db_path : Path
        Path to the SQLite database file. Created if it does not exist.
    dims : int
        Embedding vector dimensions (1536 for OpenAI, 384 for ONNX test).
    """

    def __init__(self, db_path: Path, *, dims: int) -> None:
        self._db_path = Path(db_path)
        self._dims = dims
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.enable_load_extension(True)
        sqlite_vec.load(self._conn)
        self._conn.enable_load_extension(False)
        self._init_schema()

    def _init_schema(self) -> None:
        """Create tables, virtual tables, and triggers if they don't exist."""
        self._conn.executescript(f"""
            CREATE TABLE IF NOT EXISTS events (
                id          TEXT PRIMARY KEY,
                type        TEXT NOT NULL,
                summary     TEXT NOT NULL,
                timestamp   TEXT NOT NULL,
                source      TEXT,
                status      TEXT DEFAULT 'active',
                metadata    TEXT,
                created_at  TEXT NOT NULL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
                summary,
                content=events,
                content_rowid=rowid
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS events_vec USING vec0(
                id        INTEGER PRIMARY KEY,
                embedding float[{self._dims}] distance_metric=cosine
            );

            CREATE TABLE IF NOT EXISTS profile (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS history (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                entry      TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS snapshots (
                key        TEXT PRIMARY KEY,
                content    TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            {_FTS_TRIGGERS}
        """)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def insert_event(
        self,
        event: dict[str, Any],
        embedding: list[float] | None = None,
    ) -> None:
        """Insert an event with optional vector embedding (single transaction)."""
        with self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO events
                   (id, type, summary, timestamp, source, status, metadata, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event["id"],
                    event["type"],
                    event["summary"],
                    event["timestamp"],
                    event.get("source"),
                    event.get("status", "active"),
                    event.get("metadata"),
                    event["created_at"],
                ),
            )
            if embedding is not None:
                rowid = self._conn.execute(
                    "SELECT rowid FROM events WHERE id = ?", (event["id"],)
                ).fetchone()[0]
                self._conn.execute(
                    "INSERT OR REPLACE INTO events_vec (id, embedding) VALUES (?, ?)",
                    (rowid, sqlite_vec.serialize_float32(embedding)),
                )

    def read_events(
        self,
        *,
        limit: int = 100,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Read events ordered by timestamp descending."""
        if status:
            rows = self._conn.execute(
                "SELECT * FROM events WHERE status = ? ORDER BY timestamp DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM events ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_vector(
        self,
        query_embedding: list[float],
        k: int = 10,
    ) -> list[dict[str, Any]]:
        """KNN vector search via sqlite-vec. Returns events with distance."""
        rows = self._conn.execute(
            """SELECT e.*, v.distance
               FROM events_vec v
               JOIN events e ON e.rowid = v.id
               WHERE v.embedding MATCH ?
               AND k = ?
               ORDER BY v.distance""",
            (sqlite_vec.serialize_float32(query_embedding), k),
        ).fetchall()
        return [dict(row) for row in rows]

    def search_fts(self, query_text: str, k: int = 10) -> list[dict[str, Any]]:
        """FTS5 keyword search over event summaries.

        Uses term-level matching (implicit AND) rather than phrase matching
        so that "coffee preference" matches documents containing both terms
        anywhere, not just the exact phrase.
        """
        # Quote each term individually to escape FTS5 operators
        terms = re.findall(r"\w+", query_text)
        if not terms:
            return []
        safe_query = " ".join(f'"{t}"' for t in terms)
        try:
            rows = self._conn.execute(
                """SELECT e.*, rank
                   FROM events_fts fts
                   JOIN events e ON e.rowid = fts.rowid
                   WHERE events_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (safe_query, k),
            ).fetchall()
        except sqlite3.OperationalError:
            # Malformed FTS query — return empty
            return []
        return [dict(row) for row in rows]

    def search_by_metadata(
        self,
        *,
        topic: str | None = None,
        memory_type: str | None = None,
        k: int = 10,
    ) -> list[dict[str, Any]]:
        """Fallback search by event type and/or metadata topic."""
        conditions: list[str] = []
        params: list[Any] = []
        if memory_type:
            conditions.append("type = ?")
            params.append(memory_type)
        if topic:
            conditions.append("json_extract(metadata, '$.topic') = ?")
            params.append(topic)
        if not conditions:
            return []
        where = " AND ".join(conditions)
        params.append(k)
        rows = self._conn.execute(
            f"SELECT * FROM events WHERE {where} ORDER BY timestamp DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------

    def read_profile(self, key: str) -> dict[str, Any] | None:
        """Read a profile section by key. Returns None if not found."""
        row = self._conn.execute(
            "SELECT value FROM profile WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def write_profile(self, key: str, value: dict[str, Any]) -> None:
        """Write a profile section (upsert)."""
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO profile (key, value) VALUES (?, ?)",
                (key, json.dumps(value, default=str)),
            )

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def append_history(self, entry: str) -> None:
        """Append a history entry with current timestamp."""
        with self._conn:
            self._conn.execute(
                "INSERT INTO history (entry, created_at) VALUES (?, ?)",
                (entry, _utc_now_iso()),
            )

    def read_history(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Read history entries ordered by creation time ascending."""
        rows = self._conn.execute(
            "SELECT * FROM history ORDER BY created_at ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def read_snapshot(self, key: str) -> str:
        """Read a snapshot by key. Returns empty string if not found."""
        row = self._conn.execute(
            "SELECT content FROM snapshots WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return ""
        return row[0]

    def write_snapshot(self, key: str, content: str) -> None:
        """Write a snapshot (upsert)."""
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO snapshots (key, content, updated_at) VALUES (?, ?, ?)",
                (key, content, _utc_now_iso()),
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
```

- [ ] **Step 5: Run tests**

```bash
make lint && make typecheck
pytest tests/test_unified_db.py -v
```
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add nanobot/agent/memory/unified_db.py tests/test_unified_db.py
git commit -m "feat: add UnifiedMemoryDB — SQLite + FTS5 + sqlite-vec storage

Single-file database replacing events.jsonl, profile.json, mem0/Qdrant,
HISTORY.md, and MEMORY.md. Includes FTS5 content-sync triggers and
sqlite-vec KNN search. All methods synchronous.
"
```

---

## Task 2: Embedder Protocol and Implementations

**Goal:** Create `embedder.py` with `Embedder` protocol, `OpenAIEmbedder`, and `LocalEmbedder` (ONNX). Pure embedding logic, no storage dependency.

**Context:** `OpenAIEmbedder` uses the OpenAI API (`text-embedding-3-small`, 1536 dims). `LocalEmbedder` uses ONNX Runtime (`all-MiniLM-L6-v2`, 384 dims) for tests. Both implement the `Embedder` protocol. The ONNX model is already available via the `onnxruntime` dependency used by the cross-encoder reranker.

**Files:**
- Create: `nanobot/agent/memory/embedder.py`
- Create: `tests/test_embedder.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_embedder.py
"""Tests for Embedder protocol and LocalEmbedder implementation."""
from __future__ import annotations

import pytest

from nanobot.memory.embedder import LocalEmbedder


class TestLocalEmbedder:
    def test_available_is_true(self):
        e = LocalEmbedder()
        assert e.available is True

    def test_dims_is_384(self):
        e = LocalEmbedder()
        assert e.dims == 384

    async def test_embed_returns_list_of_floats(self):
        e = LocalEmbedder()
        result = await e.embed("hello world")
        assert isinstance(result, list)
        assert len(result) == 384
        assert all(isinstance(x, float) for x in result)

    async def test_embed_batch_returns_list_of_lists(self):
        e = LocalEmbedder()
        results = await e.embed_batch(["hello", "world"])
        assert len(results) == 2
        assert all(len(v) == 384 for v in results)

    async def test_embed_empty_string(self):
        e = LocalEmbedder()
        result = await e.embed("")
        assert len(result) == 384

    async def test_similar_texts_have_higher_cosine(self):
        e = LocalEmbedder()
        v1 = await e.embed("I love coffee")
        v2 = await e.embed("I enjoy drinking coffee")
        v3 = await e.embed("quantum mechanics research paper")
        # Cosine similarity: dot product of normalized vectors
        import math
        def cosine(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(x * x for x in b))
            return dot / (na * nb) if na and nb else 0.0
        sim_similar = cosine(v1, v2)
        sim_different = cosine(v1, v3)
        assert sim_similar > sim_different
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_embedder.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Implement embedder.py**

```python
# nanobot/agent/memory/embedder.py
"""Embedding pipeline — Protocol + OpenAI and local ONNX implementations.

Callers depend on the ``Embedder`` protocol, not concrete classes.
``OpenAIEmbedder`` is the production default; ``LocalEmbedder`` is used
in all tests (no API key needed, 384-dim ONNX model).
"""
from __future__ import annotations

import asyncio
from typing import Any, Protocol, runtime_checkable

from loguru import logger

__all__ = ["Embedder", "LocalEmbedder", "OpenAIEmbedder"]


@runtime_checkable
class Embedder(Protocol):
    """Protocol for embedding providers."""

    async def embed(self, text: str) -> list[float]: ...
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def dims(self) -> int: ...

    @property
    def available(self) -> bool: ...


class OpenAIEmbedder:
    """Production embedder using OpenAI text-embedding-3-small (1536 dims).

    Requires OPENAI_API_KEY environment variable.
    """

    def __init__(self, model: str = "text-embedding-3-small") -> None:
        self._model = model
        self._dims_value = 1536
        self._client: Any = None
        try:
            import openai

            self._client = openai.AsyncOpenAI()
        except Exception:  # crash-barrier: any OpenAI init failure disables embedder
            logger.warning("OpenAI client not available — embedder disabled")

    @property
    def dims(self) -> int:
        return self._dims_value

    @property
    def available(self) -> bool:
        return self._client is not None

    async def embed(self, text: str) -> list[float]:
        if self._client is None:
            raise RuntimeError("OpenAI client not available — check OPENAI_API_KEY")
        response = await self._client.embeddings.create(
            model=self._model, input=text
        )
        return response.data[0].embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if self._client is None:
            raise RuntimeError("OpenAI client not available — check OPENAI_API_KEY")
        response = await self._client.embeddings.create(
            model=self._model, input=texts
        )
        return [item.embedding for item in response.data]


class LocalEmbedder:
    """Test embedder using local ONNX model (all-MiniLM-L6-v2, 384 dims).

    Requires onnxruntime and the sentence-transformers model. No API key
    needed. Suitable for contract tests and local development.
    """

    def __init__(self, model: str = "all-MiniLM-L6-v2") -> None:
        self._model_name = model
        self._dims_value = 384
        self._tokenizer: Any = None
        self._session: Any = None
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Lazy-load the ONNX model on first use."""
        if self._initialized:
            return
        try:
            from tokenizers import Tokenizer
            from huggingface_hub import hf_hub_download
            import onnxruntime as ort
            import numpy as np  # noqa: F401 — used in embed

            model_path = hf_hub_download(
                repo_id=f"sentence-transformers/{self._model_name}",
                filename="onnx/model.onnx",
            )
            tokenizer_path = hf_hub_download(
                repo_id=f"sentence-transformers/{self._model_name}",
                filename="tokenizer.json",
            )
            self._session = ort.InferenceSession(model_path)
            self._tokenizer = Tokenizer.from_file(tokenizer_path)
            self._tokenizer.enable_padding(length=128)
            self._tokenizer.enable_truncation(max_length=128)
            self._initialized = True
        except Exception:
            logger.exception("Failed to load local ONNX embedder")
            raise

    @property
    def dims(self) -> int:
        return self._dims_value

    @property
    def available(self) -> bool:
        try:
            self._ensure_initialized()
            return True
        except Exception:
            return False

    async def embed(self, text: str) -> list[float]:
        return (await self.embed_batch([text]))[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self._ensure_initialized()
        import numpy as np

        def _run() -> list[list[float]]:
            encoded = self._tokenizer.encode_batch(texts)
            input_ids = np.array([e.ids for e in encoded], dtype=np.int64)
            attention_mask = np.array(
                [e.attention_mask for e in encoded], dtype=np.int64
            )
            token_type_ids = np.zeros_like(input_ids)
            outputs = self._session.run(
                None,
                {
                    "input_ids": input_ids,
                    "attention_mask": attention_mask,
                    "token_type_ids": token_type_ids,
                },
            )
            # Mean pooling over token embeddings
            token_embeddings = outputs[0]  # (batch, seq_len, hidden_dim)
            mask_expanded = np.expand_dims(attention_mask, -1).astype(np.float32)
            summed = np.sum(token_embeddings * mask_expanded, axis=1)
            counts = np.clip(mask_expanded.sum(axis=1), a_min=1e-9, a_max=None)
            pooled = summed / counts
            # L2 normalize
            norms = np.linalg.norm(pooled, axis=1, keepdims=True)
            norms = np.clip(norms, a_min=1e-9, a_max=None)
            normalized = pooled / norms
            return normalized.tolist()

        return await asyncio.to_thread(_run)
```

> **Implementation note:** The `LocalEmbedder` uses `huggingface_hub` to download the ONNX model on first use. The `tokenizers` package is a dependency of `huggingface_hub`. If these are not already in the project's dependencies, add `huggingface-hub` and `tokenizers` to `[project.optional-dependencies]` in `pyproject.toml` under a `[dev]` or `[test]` extra. Check if `onnx_reranker.py` already has these dependencies available.

- [ ] **Step 4: Run tests**

```bash
make lint && make typecheck
pytest tests/test_embedder.py -v
```
Expected: All pass. The first run may take 30-60 seconds to download the ONNX model.

- [ ] **Step 5: Commit**

```bash
git add nanobot/agent/memory/embedder.py tests/test_embedder.py
git commit -m "feat: add Embedder protocol with OpenAI and local ONNX implementations

Embedder protocol + OpenAIEmbedder (1536 dims) and LocalEmbedder
(ONNX all-MiniLM-L6-v2, 384 dims). LocalEmbedder used in all tests.
"
```

---

## Task 3: Migration Script

**Goal:** Create `migration.py` that converts existing file-based data (events.jsonl, profile.json, HISTORY.md, MEMORY.md) into the new SQLite database.

**Context:** Migration runs automatically on first `MemoryStore` construction when `memory.db` doesn't exist but old files do. If embedder is unavailable, events are inserted without vectors (backfilled by reindex later). Old files renamed to `.bak`.

**Files:**
- Create: `nanobot/agent/memory/migration.py`
- Create: `tests/test_migration.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_migration.py
"""Tests for file-to-SQLite migration."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.memory.migration import migrate_to_sqlite
from nanobot.memory.unified_db import UnifiedMemoryDB


def _setup_old_files(memory_dir: Path) -> None:
    """Create mock old-format files in memory_dir."""
    memory_dir.mkdir(parents=True, exist_ok=True)

    # events.jsonl
    events = [
        {"id": "e1", "type": "fact", "summary": "User likes coffee",
         "timestamp": "2026-03-01T10:00:00Z", "source": "chat",
         "status": "active", "created_at": "2026-03-01T10:00:00Z"},
        {"id": "e2", "type": "task", "summary": "Fix the bug",
         "timestamp": "2026-03-02T10:00:00Z", "source": "chat",
         "status": "open", "created_at": "2026-03-02T10:00:00Z"},
    ]
    with open(memory_dir / "events.jsonl", "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")

    # profile.json
    profile = {
        "preferences": ["dark roast coffee"],
        "stable_facts": ["software engineer"],
        "active_projects": [],
        "relationships": [],
        "constraints": [],
        "conflicts": [],
        "last_verified_at": None,
        "meta": {},
    }
    with open(memory_dir / "profile.json", "w") as f:
        json.dump(profile, f)

    # HISTORY.md
    (memory_dir / "HISTORY.md").write_text(
        "[2026-03-01] First session summary\n\n"
        "[2026-03-02] Second session summary\n"
    )

    # MEMORY.md
    (memory_dir / "MEMORY.md").write_text(
        "# Memory\n\n## Preferences\n- dark roast coffee\n\n"
        "<!-- user-pinned -->\nImportant note\n<!-- end-user-pinned -->\n"
    )


class TestMigration:
    def test_migrates_events(self, tmp_path: Path):
        memory_dir = tmp_path / "memory"
        _setup_old_files(memory_dir)
        db = migrate_to_sqlite(memory_dir, dims=4, embedder=None)
        events = db.read_events(limit=10)
        assert len(events) == 2
        db.close()

    def test_migrates_profile(self, tmp_path: Path):
        memory_dir = tmp_path / "memory"
        _setup_old_files(memory_dir)
        db = migrate_to_sqlite(memory_dir, dims=4, embedder=None)
        profile = db.read_profile("profile")
        assert profile is not None
        assert "preferences" in profile
        db.close()

    def test_migrates_history(self, tmp_path: Path):
        memory_dir = tmp_path / "memory"
        _setup_old_files(memory_dir)
        db = migrate_to_sqlite(memory_dir, dims=4, embedder=None)
        entries = db.read_history(limit=10)
        assert len(entries) >= 1
        db.close()

    def test_migrates_memory_md_to_snapshot(self, tmp_path: Path):
        memory_dir = tmp_path / "memory"
        _setup_old_files(memory_dir)
        db = migrate_to_sqlite(memory_dir, dims=4, embedder=None)
        current = db.read_snapshot("current")
        assert "Memory" in current or "coffee" in current
        db.close()

    def test_extracts_user_pinned_section(self, tmp_path: Path):
        memory_dir = tmp_path / "memory"
        _setup_old_files(memory_dir)
        db = migrate_to_sqlite(memory_dir, dims=4, embedder=None)
        pinned = db.read_snapshot("user_pinned")
        assert "Important note" in pinned
        db.close()

    def test_renames_old_files_to_bak(self, tmp_path: Path):
        memory_dir = tmp_path / "memory"
        _setup_old_files(memory_dir)
        migrate_to_sqlite(memory_dir, dims=4, embedder=None)
        assert (memory_dir / "events.jsonl.bak").exists()
        assert (memory_dir / "profile.json.bak").exists()
        assert (memory_dir / "HISTORY.md.bak").exists()
        assert (memory_dir / "MEMORY.md.bak").exists()

    def test_no_migration_when_db_exists(self, tmp_path: Path):
        memory_dir = tmp_path / "memory"
        _setup_old_files(memory_dir)
        # Create the DB first
        db = UnifiedMemoryDB(memory_dir / "memory.db", dims=4)
        db.close()
        # Migration should return existing DB, not re-migrate
        db2 = migrate_to_sqlite(memory_dir, dims=4, embedder=None)
        events = db2.read_events(limit=10)
        assert len(events) == 0  # no migration happened
        db2.close()

    def test_no_old_files_creates_empty_db(self, tmp_path: Path):
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir(parents=True)
        db = migrate_to_sqlite(memory_dir, dims=4, embedder=None)
        events = db.read_events(limit=10)
        assert len(events) == 0
        db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_migration.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Implement migration.py**

```python
# nanobot/agent/memory/migration.py
"""One-time migration from file-based storage to unified SQLite.

Converts events.jsonl, profile.json, HISTORY.md, and MEMORY.md into
memory.db. Renames old files to .bak. Runs automatically on first
MemoryStore construction when memory.db does not exist.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from .unified_db import UnifiedMemoryDB

if TYPE_CHECKING:
    from .embedder import Embedder

__all__ = ["migrate_to_sqlite"]

_PINNED_START = "<!-- user-pinned -->"
_PINNED_END = "<!-- end-user-pinned -->"


def migrate_to_sqlite(
    memory_dir: Path,
    *,
    dims: int,
    embedder: Embedder | None,
) -> UnifiedMemoryDB:
    """Open or create memory.db, migrating old files if needed.

    If memory.db already exists, returns it directly (no migration).
    If old files exist but memory.db does not, migrates data and
    renames old files to .bak.
    """
    db_path = memory_dir / "memory.db"

    if db_path.exists():
        return UnifiedMemoryDB(db_path, dims=dims)

    db = UnifiedMemoryDB(db_path, dims=dims)

    old_files_exist = any(
        (memory_dir / f).exists()
        for f in ("events.jsonl", "profile.json", "HISTORY.md", "MEMORY.md")
    )

    if not old_files_exist:
        return db

    logger.info("Migrating file-based memory to SQLite: {}", memory_dir)

    # 1. Events
    events_file = memory_dir / "events.jsonl"
    if events_file.exists():
        _migrate_events(db, events_file, embedder)

    # 2. Profile
    profile_file = memory_dir / "profile.json"
    if profile_file.exists():
        _migrate_profile(db, profile_file)

    # 3. History
    history_file = memory_dir / "HISTORY.md"
    if history_file.exists():
        _migrate_history(db, history_file)

    # 4. MEMORY.md → snapshots
    memory_file = memory_dir / "MEMORY.md"
    if memory_file.exists():
        _migrate_memory_md(db, memory_file)

    # 5. Rename old files
    for name in ("events.jsonl", "profile.json", "HISTORY.md", "MEMORY.md"):
        src = memory_dir / name
        if src.exists():
            src.rename(src.with_suffix(src.suffix + ".bak"))

    logger.info("Migration complete")
    return db


def _migrate_events(
    db: UnifiedMemoryDB,
    events_file: Path,
    embedder: Embedder | None,
) -> None:
    """Read events.jsonl and insert into the events table."""
    with open(events_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed event line")
                continue
            # Ensure required fields
            if not event.get("id") or not event.get("summary"):
                continue
            event.setdefault("type", "fact")
            event.setdefault("timestamp", event.get("created_at", ""))
            event.setdefault("created_at", event.get("timestamp", ""))
            event.setdefault("status", "active")
            # Serialize metadata if it's a dict
            if isinstance(event.get("metadata"), dict):
                event["metadata"] = json.dumps(event["metadata"])
            db.insert_event(event, embedding=None)

    # Embedding backfill is NOT done during migration. Events are inserted
    # without vectors. The first maintenance.reindex() call (which runs at
    # startup via ensure_health()) will batch-embed all events using the
    # embedder. This avoids async complexity in the synchronous migration path.
    if embedder is None:
        logger.warning(
            "No embedder available during migration — events inserted without "
            "vectors. Run maintenance.reindex() to backfill embeddings."
        )
    else:
        logger.info(
            "Events migrated without embeddings — reindex will backfill "
            "vectors on next startup."
        )


def _migrate_profile(db: UnifiedMemoryDB, profile_file: Path) -> None:
    """Read profile.json and insert as a single profile row."""
    try:
        data = json.loads(profile_file.read_text())
        if isinstance(data, dict):
            db.write_profile("profile", data)
    except (json.JSONDecodeError, OSError):
        logger.warning("Failed to read profile.json — skipping")


def _migrate_history(db: UnifiedMemoryDB, history_file: Path) -> None:
    """Read HISTORY.md and insert each non-empty block as a history entry."""
    text = history_file.read_text()
    # Split on double newlines (each block is one entry)
    blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
    for block in blocks:
        db.append_history(block)


def _migrate_memory_md(db: UnifiedMemoryDB, memory_file: Path) -> None:
    """Read MEMORY.md, extract user-pinned section, store both in snapshots."""
    text = memory_file.read_text()

    # Extract user-pinned section if present
    pinned = ""
    start = text.find(_PINNED_START)
    end = text.find(_PINNED_END)
    if start != -1 and end != -1 and end > start:
        pinned = text[start + len(_PINNED_START) : end].strip()

    db.write_snapshot("current", text)
    if pinned:
        db.write_snapshot("user_pinned", pinned)
```

- [ ] **Step 4: Run tests**

```bash
make lint && make typecheck
pytest tests/test_migration.py -v
```
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add nanobot/agent/memory/migration.py tests/test_migration.py
git commit -m "feat: add file-to-SQLite migration script

Converts events.jsonl, profile.json, HISTORY.md, MEMORY.md into
memory.db on first access. Old files renamed to .bak. Events
inserted without vectors if embedder unavailable (backfilled later).
"
```

---

## Task 4: Update Ingester Write Path

**Goal:** Replace `persistence.write_jsonl()` + `mem0.add_text()` in `EventIngester` with `db.insert_event(event, embedding)`.

**Context:** `EventIngester.append_events()` (ingester.py:753) currently writes to `persistence.write_jsonl()` (line 818) and then syncs to mem0 via `_sync_events_to_mem0()` (line 870). Both are replaced by a single `db.insert_event()` call that writes the event + embedding in one transaction. The ingester receives `UnifiedMemoryDB` and `Embedder` as constructor dependencies (injected by `store.py` in Task 9). During the transition, both old and new paths can coexist — the ingester checks `if self._db is not None:` to use the new path.

**Files:**
- Modify: `nanobot/agent/memory/ingester.py`
- Modify: `tests/test_ingester.py`

> **Implementation note for the subagent:** This task is complex. Read `ingester.py` fully before editing. The key changes are:
> 1. Add `db: UnifiedMemoryDB | None = None` and `embedder: Embedder | None = None` to `__init__`
> 2. In `append_events()`, after the coerce/dedup/merge logic, replace the `persistence.write_jsonl()` + mem0 sync block with `db.insert_event()` when `self._db is not None`
> 3. Keep the old path (`persistence.write_jsonl` + `_sync_events_to_mem0`) as fallback when `self._db is None` (backward compat during transition)
> 4. `_sync_events_to_mem0()` becomes a no-op when `self._db is not None`
> 5. Embed each event summary at write time: `embedding = await embedder.embed(event["summary"])` (run in `asyncio.to_thread` since `append_events` is currently synchronous — or keep it sync and embed inline since ONNX is fast)

The tests should verify that when `db` is provided, events appear in the database and `persistence.write_jsonl` is NOT called.

- [ ] **Step 1 – Step 6:** Follow TDD: write tests → verify fail → implement → verify pass → lint → commit.

```bash
git commit -m "refactor: ingester writes to UnifiedMemoryDB when available

append_events() now routes through db.insert_event() with embedding
when UnifiedMemoryDB is injected. Falls back to persistence + mem0
when db is None (transition period).
"
```

---

## Task 5: Unified Retrieval Pipeline

**Goal:** Replace the dual-path (mem0 vs BM25) retriever with a single fused pipeline using vector search + FTS5 + RRF.

**Context:** `MemoryRetriever.retrieve()` (retriever.py:120) currently dispatches to `_retrieve_mem0_path()` or `_retrieve_bm25_path()`. Replace both with a single path: embed query → vector search → FTS5 search → RRF fusion → filter → score → rerank. The existing `_filter_items()`, `_score_items()`, `_rerank_items()` methods are kept. The new path requires `UnifiedMemoryDB` and `Embedder` as constructor dependencies.

**Files:**
- Modify: `nanobot/agent/memory/retriever.py`
- Modify: `tests/test_retriever.py`

> **Implementation note for the subagent:** Read `retriever.py` fully. Key changes:
> 1. Add `db: UnifiedMemoryDB | None = None` and `embedder: Embedder | None = None` to `__init__`
> 2. When `self._db is not None and self._embedder is not None`: use new single path
> 3. When `self._db is None`: keep old dual-path dispatch (backward compat)
> 4. New path: `embed query → db.search_vector() → db.search_fts() → _fuse_results() → _filter_items() → _score_items() → _rerank_items()`
> 5. Add `_fuse_results(vec_results, fts_results, vector_weight=0.7)` implementing Reciprocal Rank Fusion:
>    - For each result, compute RRF score: `1 / (k + rank)` where `k=60` (standard RRF constant)
>    - Weight: `vector_weight * vec_rrf + (1 - vector_weight) * fts_rrf`
>    - Deduplicate by event ID, keep highest combined score
> 6. Delete: `_source_from_mem0()`, `_source_from_bm25()`, `_merge_supplementary_bm25()`, `_inject_rollout_status()`, shadow mode code
> 7. `retrieval_planner.py` is untouched — `RetrievalPlanner` is kept and used by the new path

Tests should verify:
- RRF fusion produces correct ordering
- Vector-only and FTS-only results are both included
- Deduplication by event ID works
- Old path still works when `db` is None

- [ ] **Step 1 – Step 6:** Follow TDD: write tests → verify fail → implement → verify pass → lint → commit.

```bash
git commit -m "refactor: unified retrieval pipeline — vector + FTS5 + RRF fusion

Replaces dual-path (mem0 vs BM25) with single fused pipeline.
RRF fusion combines vector search and FTS5 keyword search.
Old dual-path preserved as fallback when db is None.
"
```

---

## Task 6: Single-Tool Consolidation

**Goal:** Merge the two LLM calls in `consolidation_pipeline.py` into one combined `consolidate_memory` tool.

**Context:** Currently `consolidation_pipeline.py` makes two LLM calls: (1) `save_memory` → history_entry, (2) `extract_structured_memory()` → events + profile_updates. Replace with a single call using a combined `consolidate_memory` tool with all three fields. Add fallback to `MemoryExtractor` heuristic if the combined call fails.

**Files:**
- Modify: `nanobot/agent/memory/consolidation_pipeline.py`
- Modify: `nanobot/agent/memory/constants.py`
- Create: `tests/test_consolidation_single_tool.py`

> **Implementation note for the subagent:**
> 1. In `constants.py`, add `_CONSOLIDATE_MEMORY_TOOL` combining `history_entry` (string, required), `events` (array, required, same schema as current `save_events`), and `profile_updates` (object, optional)
> 2. In `consolidation_pipeline.py`, find the `consolidate()` method (line 150). Replace the two sequential LLM calls with one call using `_CONSOLIDATE_MEMORY_TOOL` and `tool_choice={"type": "function", "function": {"name": "consolidate_memory"}}`
> 3. Parse the single response for all three fields
> 4. Add fallback: if `events` is missing/malformed, call `self._extractor.extract_structured_memory()` as before; if `history_entry` is missing, generate a summary from the first few messages
> 5. Keep the existing post-processing (append_events, graph triples, profile updates, snapshot rebuild) unchanged
> 6. Add a rollout flag `consolidation_single_tool` (default True) to allow reverting to the old 2-call path if needed

- [ ] **Step 1 – Step 6:** Follow TDD: write tests → verify fail → implement → verify pass → lint → commit.

```bash
git commit -m "feat: single-tool consolidation — one LLM call instead of two

Combined consolidate_memory tool produces history_entry, events, and
profile_updates in a single forced tool call. Falls back to
MemoryExtractor heuristic if events extraction fails.
"
```

---

## Task 7: Migrate Remaining Consumers

**Goal:** Update `snapshot.py`, `maintenance.py`, `conflicts.py`, `profile_io.py`, and `eval.py` to use `UnifiedMemoryDB` instead of `MemoryPersistence` and `_Mem0Adapter`.

**Context:** These modules are passed `persistence` and/or `mem0` as constructor dependencies. Each needs an optional `db: UnifiedMemoryDB | None` parameter. When `db` is provided, use it instead of the old dependencies. This is the transition step — both paths coexist until Task 10 removes the old modules. `profile_correction.py` and `retrieval_planner.py` were assessed and require no changes (no persistence/mem0 imports).

**Files:**
- Modify: `nanobot/agent/memory/snapshot.py`
- Modify: `nanobot/agent/memory/maintenance.py`
- Modify: `nanobot/agent/memory/conflicts.py`
- Modify: `nanobot/agent/memory/profile_io.py`
- Modify: `nanobot/agent/memory/eval.py`

> **Implementation note for the subagent:** Handle each file separately:
>
> **snapshot.py:** Replace `self._read_long_term()` / `self._write_long_term()` (which read/write MEMORY.md file) with `db.read_snapshot("current")` / `db.write_snapshot("current", content)`. Replace `self._read_events()` with `db.read_events()`.
>
> **maintenance.py:** Replace `self.mem0.delete_all_user_memories()`, `self.mem0.add_text()`, `self.mem0.flush_vector_store()` in `reindex_from_structured_memory()` with `db.insert_event()` calls (with embeddings). The reindex flow becomes: clear events_vec → re-embed all events → re-insert.
>
> **conflicts.py:** Replace `self.mem0.delete()`, `self.mem0.update()`, `self.mem0.add_text()` in conflict resolution with equivalent DB operations (delete event, update event summary, insert event). The `_find_mem0_id_for_text()` calls in `profile_io.py` become `db.search_fts()`.
>
> **profile_io.py:** Remove `mem0` constructor parameter. Replace `self.mem0.search()` in `_find_mem0_id_for_text()` with `db.search_fts()` or `db.search_vector()`. Replace `ProfileCache` file-based reads with `db.read_profile("profile")` / `db.write_profile("profile", data)`.
>
> **eval.py:** Replace `from .persistence import MemoryPersistence` with `UnifiedMemoryDB`. Update any `persistence.*` calls to use the `db` parameter. Use `LocalEmbedder` for eval runs.
>
> **consolidation_pipeline.py:** In addition to the tool change (Task 6), ensure `persistence` and `mem0` imports are replaced. The `_sync_events_to_mem0()` call and raw turn ingestion are deleted — events are already written to the DB by the ingester.

- [ ] **Step 1 – Step 10:** TDD per file: write tests → verify fail → implement → verify pass → lint → commit.

```bash
git commit -m "refactor: migrate snapshot, maintenance, conflicts, profile_io, eval to UnifiedMemoryDB

All modules now accept optional db parameter and route through
UnifiedMemoryDB when available. Old persistence/mem0 paths preserved
as fallback during transition.
"
```

---

## Task 8: Update ContextAssembler

**Goal:** Update `ContextAssembler` to read the memory snapshot from `UnifiedMemoryDB` instead of files, and add the embedder-unavailable notice.

**Context:** `ContextAssembler.build()` calls `self._read_long_term_fn()` (wired to `persistence.read_text(memory_file)` by `store.py`). Replace with `db.read_snapshot("current")`. Add check: if embedder is unavailable, return `[Memory unavailable: no embedding provider configured...]` instead of normal memory context.

**Files:**
- Modify: `nanobot/agent/memory/context_assembler.py`

> **Implementation note:** Add `db: UnifiedMemoryDB | None = None` and `embedder_available: bool = True` to `__init__`. In `build()`:
> - If `not self._embedder_available`: return the unavailable notice
> - If `self._db is not None`: read snapshot from `self._db.read_snapshot("current")` instead of `self._read_long_term_fn()`

- [ ] **Step 1 – Step 5:** TDD: write tests → verify fail → implement → verify pass → lint → commit.

```bash
git commit -m "refactor: context_assembler reads snapshot from UnifiedMemoryDB

Adds embedder-unavailable notice when embedding provider is missing.
Reads memory snapshot from db.read_snapshot() instead of file.
"
```

---

## Task 9: Wire Store.py

**Goal:** Update `MemoryStore.__init__` to construct `UnifiedMemoryDB` and `Embedder` and pass them to all subsystems. This is the integration task that connects everything.

**Context:** `store.py` is the facade that wires all subsystems. Currently it constructs `MemoryPersistence` (line 94) and `_Mem0Adapter` (line 113). Replace with `UnifiedMemoryDB` and `Embedder`. Pass `db=` and `embedder=` to all subsystems that accept them (Tasks 4-8). Keep `persistence` and `mem0` construction as dead-code until Task 10 confirms all consumers are migrated.

**Files:**
- Modify: `nanobot/agent/memory/store.py`

> **Implementation note:**
> 1. Add `from .unified_db import UnifiedMemoryDB` and `from .embedder import OpenAIEmbedder, LocalEmbedder`
> 2. Add `from .migration import migrate_to_sqlite`
> 3. In `__init__`, after workspace setup: `self.db = migrate_to_sqlite(self.memory_dir, dims=embedder.dims, embedder=embedder)`
> 4. Construct embedder: Try `OpenAIEmbedder()` first; if `not embedder.available`, fall back to `LocalEmbedder()` or `None`
> 5. Pass `db=self.db` and `embedder=self._embedder` to: `EventIngester`, `MemoryRetriever`, `MemoryMaintenance`, `ConflictManager`, `ProfileStore`, `MemorySnapshot`, `ContextAssembler`
> 6. Keep the old `persistence` and `mem0` construction temporarily — subsystems still fall back to them if `db` is None

- [ ] **Step 1 – Step 5:** TDD: write tests → verify pass → lint → commit.

```bash
git commit -m "feat: wire UnifiedMemoryDB + Embedder in MemoryStore

MemoryStore now constructs unified SQLite database and embedder,
passing them to all subsystems. Migration runs automatically on
first access. Old persistence/mem0 paths still available as fallback.
"
```

---

## Task 10: Delete Dead Code, Clean Up, and Update Tests

**Goal:** Remove `mem0_adapter.py`, `retrieval.py`, `persistence.py`. Clean up `rollout.py`, `__init__.py`, `pyproject.toml`. Delete and update all affected test files. This is a single atomic task — code deletion and test migration happen together so the test suite never breaks.

**Context:** After Tasks 4-9, all subsystems route through `UnifiedMemoryDB`. The old modules are unused. Remove them, clean up references, and migrate all tests in one commit.

**Files:**
- Delete: `nanobot/agent/memory/mem0_adapter.py`
- Delete: `nanobot/agent/memory/retrieval.py`
- Delete: `nanobot/agent/memory/persistence.py`
- Delete: `tests/test_mem0_adapter_branches.py`
- Delete: `tests/test_mem0_adapter_init_paths.py`
- Delete: `tests/test_mem0_adapter_fallback.py`
- Modify: `nanobot/agent/memory/rollout.py`
- Modify: `nanobot/agent/memory/__init__.py`
- Modify: `pyproject.toml`
- Modify: `tests/test_ingester.py`
- Modify: `tests/test_maintenance.py`
- Modify: `tests/test_snapshot.py`
- Modify: `tests/test_retriever.py`
- Modify: `tests/test_memory_hybrid.py`
- Modify: `tests/test_memory_helper_wave5.py`
- Modify: `tests/test_coverage_push_wave6.py`

> **Implementation note:**
>
> **Part A — Delete modules and clean up:**
> 1. `git rm` the three source files and three test files
> 2. In `rollout.py`: remove all `mem0_*` flags, `memory_history_fallback_enabled`, `memory_shadow_mode`, `memory_shadow_sample_rate`, `memory_fallback_allowed_sources`
> 3. In `__init__.py`: remove `_Mem0Adapter`, `_Mem0RuntimeInfo`, `MemoryPersistence` from imports and `__all__`. Add `UnifiedMemoryDB`, `Embedder`, `OpenAIEmbedder`, `LocalEmbedder`
> 4. In `pyproject.toml`: remove `mem0ai` from dependencies. Add `sqlite-vec`. Note: `qdrant-client` was only a transitive dependency of `mem0ai` — no separate removal needed.
> 5. In all subsystem `__init__` methods: remove the `if self._db is None:` fallback paths (the old persistence/mem0 code). Make `db` required instead of optional.
> 6. Remove any remaining `import` of the deleted modules
>
> **Part B — Update tests:**
> 7. For each remaining test file that imported `_Mem0Adapter` or `MemoryPersistence`:
>    - Replace `MagicMock()` for `_Mem0Adapter` with a real `UnifiedMemoryDB(tmp_path / "memory.db", dims=4)` or a mock of the DB interface
>    - Replace `MagicMock()` for `MemoryPersistence` with the DB
>    - Use `LocalEmbedder()` where embedder is needed
>    - Ensure all tests use real vector search, not hash fallback
> 8. For `test_memory_helper_wave5.py`: replace `from nanobot.memory.retrieval import ...` with equivalent DB-based assertions
>
> **Part C — Verify:**
> 9. Run `grep -r "mem0_adapter\|from .persistence\|from .retrieval import" nanobot/ tests/` — expected: no output
> 10. Run `make lint && make typecheck && pytest -x`

- [ ] **Step 1 – Step 10:** Delete files → clean modules → update tests → verify → commit.

```bash
git commit -m "chore: delete mem0_adapter, retrieval, persistence + migrate tests

Remove ~1,246 lines of dead code. Delete 3 mem0-specific test files.
Update 7 test files to use UnifiedMemoryDB + LocalEmbedder. Clean up
rollout flags, __init__ exports, and pyproject dependencies.
"
```

---

## Task 11: Final Validation

**Goal:** Run full validation, verify all dead code is gone, update docs.

**Files:**
- Modify: `docs/architecture.md` (update memory subsystem section)

- [ ] **Step 1: Run full validation**

```bash
make check
```
Expected: lint + typecheck + import-check + prompt-check + tests all pass.

- [ ] **Step 2: Verify deleted modules are gone**

```bash
ls nanobot/agent/memory/mem0_adapter.py 2>&1 || echo "DELETED"
ls nanobot/agent/memory/retrieval.py 2>&1 || echo "DELETED"
ls nanobot/agent/memory/persistence.py 2>&1 || echo "DELETED"
```

- [ ] **Step 3: Verify no remaining mem0 imports**

```bash
grep -r "mem0_adapter\|from .persistence import\|from .retrieval import" nanobot/ tests/
```
Expected: no output.

- [ ] **Step 4: Verify sqlite-vec works**

```bash
python -c "
from nanobot.memory.unified_db import UnifiedMemoryDB
from pathlib import Path
import tempfile
with tempfile.TemporaryDirectory() as d:
    db = UnifiedMemoryDB(Path(d) / 'test.db', dims=4)
    db.insert_event({'id': 'test', 'type': 'fact', 'summary': 'hello',
                     'timestamp': '2026-01-01', 'created_at': '2026-01-01'},
                    embedding=[1,0,0,0])
    r = db.search_vector([1,0,0,0], k=1)
    assert len(r) == 1
    print('OK: SQLite + sqlite-vec working')
    db.close()
"
```

- [ ] **Step 5: Update architecture docs**

Add to `docs/architecture.md` under "Memory Subsystem Module Boundaries":
```markdown
### Storage Layer (Post-Redesign)

- **`unified_db.py`** — Single SQLite database (`memory.db`) with FTS5 + sqlite-vec.
  All memory storage flows through this module. Replaces `persistence.py` + `mem0_adapter.py`.
- **`embedder.py`** — `Embedder` protocol with `OpenAIEmbedder` (production) and
  `LocalEmbedder` (tests, ONNX). No hash-based fallback.
- **`migration.py`** — One-time file-to-SQLite migration. Runs on first access.
```

- [ ] **Step 6: Commit**

```bash
git add docs/architecture.md
git commit -m "docs: update architecture for unified SQLite storage layer"
```

---

## Quick Reference: Key Module Dependencies

| Module | Old deps (remove) | New deps (add) |
|--------|-------------------|----------------|
| `ingester.py` | `persistence`, `mem0` | `db`, `embedder` |
| `retriever.py` | `mem0`, `retrieval.py` | `db`, `embedder` |
| `consolidation_pipeline.py` | `persistence` | `db` |
| `snapshot.py` | `persistence` | `db` |
| `maintenance.py` | `mem0`, `persistence` | `db`, `embedder` |
| `conflicts.py` | `mem0` | `db` |
| `profile_io.py` | `mem0`, `persistence` | `db` |
| `context_assembler.py` | `persistence` | `db` |
| `store.py` | `persistence`, `mem0` | `db`, `embedder`, `migration` |
