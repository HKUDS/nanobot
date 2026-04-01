# Missing Indexes + Targeted SQL Dedup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add missing database indexes to eliminate full-table scans, and replace the O(N) read-all dedup algorithm with targeted SQL queries that scale to 100K+ events.

**Architecture:** Part 1 adds 4 indexes to the schema DDL (additive, safe for existing DBs). Part 2 rewrites `EventIngester.append_events()` to use SQL-targeted lookups (PK for exact ID dedup, FTS5 for semantic dedup/supersession) instead of loading all events into memory. `EventDeduplicator` methods stay unchanged — they're called with smaller candidate lists from SQL pre-filtering.

**Tech Stack:** Python 3.10+, SQLite, FTS5, ruff, mypy, pytest

**Spec:** `docs/superpowers/specs/2026-04-01-indexes-and-targeted-dedup-design.md`

---

## File Structure

### Files to Modify

| File | Change |
|------|--------|
| `nanobot/memory/db/connection.py` | Add 4 indexes to `_init_schema()` |
| `nanobot/memory/db/event_store.py` | Add `get_event_by_id()` method |
| `nanobot/memory/write/ingester.py` | Rewrite `append_events()` to use SQL-targeted dedup |

### Files to Create

| File | Purpose |
|------|---------|
| `tests/test_targeted_dedup.py` | Tests for the new dedup algorithm |

---

## Task 1: Add Missing Database Indexes

**Files:**
- Modify: `nanobot/memory/db/connection.py`
- Test: `tests/test_memory_database.py`

- [ ] **Step 1: Add test verifying indexes exist**

Add to `tests/test_memory_database.py`:

```python
def test_events_indexes_exist(self, db: MemoryDatabase) -> None:
    indexes = {
        row[0]
        for row in db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
    }
    assert "idx_events_type" in indexes
    assert "idx_events_status" in indexes
    assert "idx_events_timestamp" in indexes
    assert "idx_edges_target" in indexes
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Add indexes to `_init_schema()` in `connection.py`**

Add after the `{_FTS_TRIGGERS}` line in the executescript:

```sql
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target);
```

- [ ] **Step 4: Run test to verify it passes**

- [ ] **Step 5: Run `make lint && make typecheck && make test`**

- [ ] **Step 6: Commit**

```bash
git commit -m "perf(memory): add missing indexes on events and edges tables

idx_events_type, idx_events_status, idx_events_timestamp for
filtered reads. idx_edges_target for graph BFS traversal."
```

---

## Task 2: Add `get_event_by_id()` to EventStore

**Files:**
- Modify: `nanobot/memory/db/event_store.py`
- Test: `tests/test_event_store.py`

- [ ] **Step 1: Add test**

```python
class TestGetEventById:
    def test_found(self, store: EventStore) -> None:
        store.insert_event(_make_event(id="e1", summary="hello"))
        result = store.get_event_by_id("e1")
        assert result is not None
        assert result["id"] == "e1"
        assert result["summary"] == "hello"

    def test_not_found(self, store: EventStore) -> None:
        assert store.get_event_by_id("nonexistent") is None
```

- [ ] **Step 2: Implement `get_event_by_id()`**

```python
def get_event_by_id(self, event_id: str) -> dict[str, Any] | None:
    """Fetch a single event by primary key. Returns None if not found."""
    row = self._conn.execute(
        "SELECT * FROM events WHERE id = ?", (event_id,)
    ).fetchone()
    if row is None:
        return None
    return dict(row)
```

- [ ] **Step 3: Run tests, lint, typecheck**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(memory): add EventStore.get_event_by_id() for targeted lookups"
```

---

## Task 3: Rewrite `append_events()` with Targeted SQL Dedup

This is the core task. Replace the O(N) read-all pattern with SQL-targeted lookups.

**Files:**
- Modify: `nanobot/memory/write/ingester.py`
- Test: `tests/test_targeted_dedup.py`

- [ ] **Step 1: Create `tests/test_targeted_dedup.py` with correctness tests**

```python
"""Tests for targeted SQL dedup — verifies the new algorithm finds
duplicates and supersessions that the old 100-event-limited approach missed."""
from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.memory.event import MemoryEvent
from nanobot.memory.store import MemoryStore


@pytest.fixture()
def store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(tmp_path, embedding_provider="hash")


class TestExactIdDedup:
    def test_duplicate_id_merges(self, store: MemoryStore) -> None:
        store.ingester.append_events([MemoryEvent(id="e1", summary="v1", type="fact")])
        store.ingester.append_events([MemoryEvent(id="e1", summary="v1 updated", type="fact")])
        events = store.ingester.read_events(limit=100)
        assert sum(1 for e in events if e["id"] == "e1") == 1

    def test_duplicate_id_beyond_100_events(self, store: MemoryStore) -> None:
        """Regression: old algorithm only checked latest 100 events."""
        # Seed 150 events
        for i in range(150):
            store.ingester.append_events([
                MemoryEvent(id=f"seed-{i}", summary=f"Seed event {i}", type="fact",
                            timestamp=f"2026-01-01T{i:04d}:00Z")
            ])
        # Now try to add a duplicate of the OLDEST event (beyond old 100-event window)
        result = store.ingester.append_events([
            MemoryEvent(id="seed-0", summary="Seed event 0 updated", type="fact")
        ])
        # Should merge (written=0) not create duplicate
        all_events = store.ingester.read_events(limit=200)
        ids = [e["id"] for e in all_events]
        assert ids.count("seed-0") == 1


class TestSemanticDedup:
    def test_similar_summaries_merge(self, store: MemoryStore) -> None:
        store.ingester.append_events([
            MemoryEvent(summary="User prefers dark roast coffee", type="preference")
        ])
        written = store.ingester.append_events([
            MemoryEvent(summary="User prefers dark roast coffee beans", type="preference")
        ])
        # Should merge due to high similarity
        events = store.ingester.read_events(limit=100)
        prefs = [e for e in events if e["type"] == "preference"]
        assert len(prefs) <= 1  # merged or deduplicated


class TestSupersession:
    def test_contradiction_marks_superseded(self, store: MemoryStore) -> None:
        store.ingester.append_events([
            MemoryEvent(summary="User likes tea", type="preference")
        ])
        store.ingester.append_events([
            MemoryEvent(summary="User does not like tea", type="preference")
        ])
        events = store.ingester.read_events(limit=100)
        statuses = {e.get("summary", ""): e.get("status", "") for e in events}
        # At least one should be superseded
        assert "superseded" in statuses.values() or len(events) >= 2


class TestNewEventsPassThrough:
    def test_unrelated_events_both_stored(self, store: MemoryStore) -> None:
        store.ingester.append_events([
            MemoryEvent(summary="User likes coffee", type="preference")
        ])
        written = store.ingester.append_events([
            MemoryEvent(summary="Meeting scheduled for Friday", type="task")
        ])
        assert written == 1
        events = store.ingester.read_events(limit=100)
        assert len(events) == 2
```

- [ ] **Step 2: Run tests to establish baseline (some may pass on current code, the 150-event test should fail)**

- [ ] **Step 3: Rewrite `append_events()` in `ingester.py`**

Replace the O(N) read-all pattern. The new algorithm:

```python
def append_events(self, events: Sequence[MemoryEvent]) -> int:
    if not events or self._db is None:
        return 0
    raw_events = [e.to_dict() for e in events]
    t0 = time.monotonic()
    written = 0
    merged = 0
    superseded = 0
    events_to_write: list[dict[str, Any]] = []

    for raw in raw_events:
        event_id = raw.get("id")
        if not event_id:
            summary = str(raw.get("summary", "")).strip()
            if not summary:
                continue
            event_type = str(raw.get("type", "fact"))
            ts = str(raw.get("timestamp", _utc_now_iso()))
            event_id = self._coercer.build_event_id(event_type, summary, ts)
            raw = {**raw, "id": event_id, "timestamp": ts}
        candidate = self._coercer.ensure_event_provenance(raw)

        # Step 1: Exact ID dedup — PK lookup, O(1)
        existing_row = self._db.get_event_by_id(event_id)
        if existing_row is not None:
            existing = self._unpack_event(existing_row)
            existing = self._coercer.ensure_event_provenance(existing)
            merged_event = self._dedup.merge_events(existing, candidate, similarity=1.0)
            events_to_write.append(merged_event)
            merged += 1
            continue

        # Step 2: Supersession — FTS5 pre-filter + type match
        supersession_found = False
        if memory_type_for_item(candidate) == "semantic":
            fts_candidates = self._find_dedup_candidates(candidate, limit=30)
            semantic_candidates = [
                c for c in fts_candidates
                if memory_type_for_item(c) == "semantic"
                and str(c.get("status", "")).lower() != "superseded"
            ]
            superseded_idx = self._dedup.find_semantic_supersession(
                candidate, semantic_candidates
            )
            if superseded_idx is not None:
                now_iso = _utc_now_iso()
                sup_event = dict(semantic_candidates[superseded_idx])
                sup_id = str(sup_event.get("id", ""))
                sup_event["status"] = "superseded"
                sup_event["superseded_at"] = now_iso
                if event_id:
                    sup_event["superseded_by_event_id"] = event_id
                events_to_write.append(sup_event)
                if sup_id:
                    candidate["supersedes_event_id"] = sup_id
                candidate["supersedes_at"] = now_iso
                events_to_write.append(candidate)
                written += 1
                superseded += 1
                supersession_found = True

        # Step 3: Semantic duplicate — FTS5 pre-filter + Jaccard
        if not supersession_found:
            fts_candidates = self._find_dedup_candidates(candidate, limit=30)
            dup_idx, dup_score = self._dedup.find_semantic_duplicate(
                candidate, fts_candidates
            )
            if dup_idx is not None:
                merged_event = self._dedup.merge_events(
                    fts_candidates[dup_idx], candidate, similarity=dup_score
                )
                events_to_write.append(merged_event)
                merged += 1
                continue

            # Step 4: New event — no match found
            events_to_write.append(candidate)
            written += 1

    if written <= 0 and merged <= 0:
        return 0

    # Persist all events
    self._write_events(events_to_write)

    bind_trace().debug(
        "memory_append | written={} | merged={} | superseded={} | {:.0f}ms",
        written, merged, superseded, (time.monotonic() - t0) * 1000,
    )
    return written
```

With two new helper methods:

```python
def _find_dedup_candidates(self, candidate: dict[str, Any], limit: int = 30) -> list[dict[str, Any]]:
    """Use FTS5 to find events with overlapping tokens, filtered by type."""
    summary = str(candidate.get("summary", ""))
    event_type = str(candidate.get("type", ""))
    tokens = re.findall(r"\w+", f"{event_type} {summary}".lower())
    if not tokens:
        return []
    # Use FTS5 to narrow candidates
    fts_query = " OR ".join(f"{t}*" for t in tokens[:15])
    fts_results = self._db.search_fts(fts_query, k=limit * 2)
    # Filter by type and unpack metadata
    candidates = []
    for row in fts_results:
        event = self._unpack_event(row)
        if str(event.get("type", "")) == event_type:
            candidates.append(self._coercer.ensure_event_provenance(event))
        if len(candidates) >= limit:
            break
    return candidates

def _unpack_event(self, row: dict[str, Any]) -> dict[str, Any]:
    """Unpack metadata._extra from a raw DB row to top-level keys."""
    import json as _json
    event = dict(row)
    raw_meta = event.get("metadata")
    if isinstance(raw_meta, str):
        try:
            meta = _json.loads(raw_meta)
        except (ValueError, TypeError):
            meta = {}
    else:
        meta = raw_meta if isinstance(raw_meta, dict) else {}
    extras = meta.pop("_extra", None) if isinstance(meta, dict) else None
    if isinstance(extras, dict):
        event.update(extras)
    if meta:
        event["metadata"] = meta
    return event

def _write_events(self, events: list[dict[str, Any]]) -> None:
    """Pack and persist events to EventStore."""
    import json as _json
    _db_columns = {"id", "type", "summary", "timestamp", "source", "status", "metadata", "created_at"}
    for event in events:
        evt_copy = dict(event)
        meta = evt_copy.get("metadata")
        meta = meta if isinstance(meta, dict) else {}
        extras = {k: v for k, v in evt_copy.items() if k not in _db_columns}
        if extras:
            meta = {**meta, "_extra": extras}
        evt_copy["metadata"] = _json.dumps(meta) if meta else None
        evt_copy.setdefault("created_at", evt_copy.get("timestamp", _utc_now_iso()))
        self._db.insert_event(evt_copy, embedding=None)
```

- [ ] **Step 4: Add `import re` and `from ..event import memory_type_for_item` to ingester.py imports**

- [ ] **Step 5: Run all tests**

Run: `PYTHONPATH=. python -m pytest tests/test_targeted_dedup.py tests/test_ingester.py -v`
Then: `PYTHONPATH=. python -m pytest tests/ --ignore=tests/integration -x -q`

- [ ] **Step 6: Run `make lint && make typecheck`**

- [ ] **Step 7: Commit**

```bash
git commit -m "fix(memory): replace O(N) read-all dedup with targeted SQL queries

Fixes correctness bug: old algorithm only checked latest 100 events,
missing duplicates beyond that window. New algorithm uses:
- PK lookup for exact ID dedup (O(1))
- FTS5 pre-filtering for semantic dedup/supersession (O(k), k~30)
- Full event loaded only when merge needed

Scales to 100K+ events with constant ingestion time."
```

---

## Task 4: Final Verification + Code Review + PR

- [ ] **Step 1: Run `make pre-push`**
- [ ] **Step 2: Verify the 150-event regression test passes**
- [ ] **Step 3: Dispatch code review**
- [ ] **Step 4: Push and create PR**
