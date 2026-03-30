# Memory Phase 1: Repository Layer Extraction

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the god-repository `UnifiedMemoryDB` (502 LOC, 20+ methods across 6 concerns) into focused repository classes sharing one SQLite connection, then delete `UnifiedMemoryDB`.

**Architecture:** Create a `memory/db/` subpackage with three files: `connection.py` (connection management + schema init + simple key-value CRUD for profile/history/snapshot), `event_store.py` (event CRUD + FTS5 + vector search — the most complex and most-consumed concern), and `graph_store.py` (entity/edge CRUD + BFS traversal — consumed only by KnowledgeGraph). All share one SQLite connection. Update all 20+ consumers. Delete `UnifiedMemoryDB` with zero remaining references.

**Tech Stack:** Python 3.10+, SQLite, sqlite-vec, FTS5, ruff, mypy, pytest

**Conventions:**
- `from __future__ import annotations` in every module
- TYPE_CHECKING imports for type annotations to avoid circular imports
- No backward compatibility: no shims, no re-exports, no aliases (prohibited-patterns.md)
- After deletion, grep for old name — zero matches required (change-protocol.md)
- Run `make lint && make typecheck` after every change
- All commands run from worktree: `cd C:/Users/C95071414/Documents/nanobot-refactor-memory-phase1 &&`

---

## File Structure

### Files to Create

| File | Responsibility | Approx LOC |
|------|---------------|------------|
| `nanobot/memory/db/__init__.py` | Package exports: `MemoryDatabase`, `EventStore`, `GraphStore` | ~15 |
| `nanobot/memory/db/connection.py` | SQLite connection mgmt, schema init, profile/history/snapshot CRUD | ~200 |
| `nanobot/memory/db/event_store.py` | Event insert/read + FTS5 search + vector search + metadata search | ~170 |
| `nanobot/memory/db/graph_store.py` | Entity/edge CRUD + BFS neighbor traversal | ~140 |

### Files to Modify

| File | Change |
|------|--------|
| `nanobot/memory/store.py` | Replace `UnifiedMemoryDB` with `MemoryDatabase` + sub-stores |
| `nanobot/memory/__init__.py` | Replace `UnifiedMemoryDB` export with `MemoryDatabase` |
| `nanobot/memory/write/ingester.py` | Accept `EventStore` instead of `UnifiedMemoryDB` |
| `nanobot/memory/read/retriever.py` | Accept `EventStore` instead of `UnifiedMemoryDB` |
| `nanobot/memory/read/context_assembler.py` | Accept `MemoryDatabase` instead of `UnifiedMemoryDB` |
| `nanobot/memory/graph/graph.py` | Accept `GraphStore` instead of `UnifiedMemoryDB` |
| `nanobot/memory/persistence/profile_io.py` | Accept `MemoryDatabase` instead of `UnifiedMemoryDB` |
| `nanobot/memory/persistence/snapshot.py` | Accept `MemoryDatabase` instead of `UnifiedMemoryDB` |
| `nanobot/memory/write/conflicts.py` | Accept `MemoryDatabase` instead of `UnifiedMemoryDB` |
| `nanobot/memory/consolidation_pipeline.py` | Accept `MemoryDatabase` instead of `UnifiedMemoryDB` |
| `nanobot/memory/maintenance.py` | Accept `MemoryDatabase` + `EventStore` |
| `nanobot/memory/strategy.py` | Accept `MemoryDatabase` for connection |
| `nanobot/memory/constants.py` | Move `STRATEGIES_DDL` here from `unified_db.py` |
| `nanobot/eval/memory_eval.py` | Accept `MemoryDatabase` instead of `UnifiedMemoryDB` |
| `nanobot/context/feedback_context.py` | Accept `MemoryDatabase` instead of `UnifiedMemoryDB` |
| `nanobot/tools/builtin/feedback.py` | Accept `MemoryDatabase` instead of `UnifiedMemoryDB` |
| `nanobot/tools/setup.py` | Update type annotation |
| `nanobot/agent/agent_factory.py` | Update construction |
| 13 test files | Update imports and fixtures |

### Files to Delete

| File | Reason |
|------|--------|
| `nanobot/memory/unified_db.py` | Replaced by `db/` package |

---

## Method-to-Repository Mapping

| Method | Current Location | Target | Consumers |
|--------|-----------------|--------|-----------|
| `__init__` (connection, schema, WAL) | UnifiedMemoryDB | `MemoryDatabase` | store.py |
| `connection` property | UnifiedMemoryDB | `MemoryDatabase` | strategy.py, agent_factory.py |
| `close`, `__enter__`, `__exit__` | UnifiedMemoryDB | `MemoryDatabase` | store.py, tests |
| `read_profile`, `write_profile` | UnifiedMemoryDB | `MemoryDatabase` | profile_io.py, profile_correction.py |
| `append_history`, `read_history` | UnifiedMemoryDB | `MemoryDatabase` | consolidation_pipeline.py |
| `read_snapshot`, `write_snapshot` | UnifiedMemoryDB | `MemoryDatabase` | snapshot.py, context_assembler.py, consolidation_pipeline.py |
| `insert_event`, `read_events` | UnifiedMemoryDB | `EventStore` | ingester.py, maintenance.py, snapshot.py |
| `search_vector` | UnifiedMemoryDB | `EventStore` | retriever.py |
| `search_fts` | UnifiedMemoryDB | `EventStore` | retriever.py, profile_io.py |
| `search_by_metadata` | UnifiedMemoryDB | `EventStore` | retriever.py |
| `upsert_entity`, `get_entity`, `search_entities` | UnifiedMemoryDB | `GraphStore` | graph.py |
| `add_edge`, `get_edges_from`, `get_edges_to` | UnifiedMemoryDB | `GraphStore` | graph.py |
| `get_neighbors` | UnifiedMemoryDB | `GraphStore` | graph.py |
| `STRATEGIES_DDL` constant | UnifiedMemoryDB | `constants.py` | test fixtures |

---

## Task 1: Create db/ package with MemoryDatabase

**Files:**
- Create: `nanobot/memory/db/__init__.py`
- Create: `nanobot/memory/db/connection.py`
- Test: `tests/test_memory_database.py`

- [ ] **Step 1: Create test file for MemoryDatabase**

Create `tests/test_memory_database.py` testing that `MemoryDatabase` can be instantiated, creates all tables, and provides profile/history/snapshot CRUD. Model tests after existing `tests/test_unified_db.py` but targeting the new class.

Key tests:
- `test_creates_tables` — events, profile, history, snapshots, entities, edges, strategies tables all exist
- `test_wal_mode_enabled` — PRAGMA journal_mode returns WAL
- `test_profile_roundtrip` — write then read profile section
- `test_history_append_and_read` — append entries then read them
- `test_snapshot_roundtrip` — write then read snapshot
- `test_connection_property` — connection is a sqlite3.Connection
- `test_close` — close doesn't error, subsequent access raises
- `test_context_manager` — `with MemoryDatabase(...) as db: ...` works

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:/Users/C95071414/Documents/nanobot-refactor-memory-phase1 && PYTHONPATH=. python -m pytest tests/test_memory_database.py -v`
Expected: FAIL — `MemoryDatabase` not yet defined

- [ ] **Step 3: Create `nanobot/memory/db/__init__.py`**

```python
"""Database layer — focused repository classes sharing one SQLite connection."""

from __future__ import annotations

from .connection import MemoryDatabase

__all__ = ["MemoryDatabase"]
```

- [ ] **Step 4: Create `nanobot/memory/db/connection.py`**

Move connection management, schema init, and profile/history/snapshot CRUD from `unified_db.py`. The schema init creates ALL tables (events, FTS5, vec, profile, history, snapshots, entities, edges, strategies) because they share one SQLite file. Sub-stores (`EventStore`, `GraphStore`) receive the connection from `MemoryDatabase` — they don't create tables themselves.

Key design decisions:
- `MemoryDatabase` owns the connection and schema lifecycle
- Profile/history/snapshot CRUD stays here (too small for separate files: ~12 LOC each)
- `EventStore` and `GraphStore` receive `self._conn` from MemoryDatabase
- The `event_store` and `graph_store` properties create sub-stores lazily

- [ ] **Step 5: Run tests to verify they pass**

- [ ] **Step 6: Run lint and typecheck**

Run: `make lint && make typecheck`

- [ ] **Step 7: Commit**

```bash
git add nanobot/memory/db/ tests/test_memory_database.py
git commit -m "refactor(memory): create MemoryDatabase with connection mgmt and simple CRUD"
```

---

## Task 2: Create EventStore

**Files:**
- Create: `nanobot/memory/db/event_store.py`
- Modify: `nanobot/memory/db/__init__.py` (add export)
- Test: `tests/test_event_store.py`

- [ ] **Step 1: Create test file for EventStore**

Create `tests/test_event_store.py` testing event CRUD, FTS5 search, vector search, and metadata search. Base on existing `tests/test_unified_db.py` event tests.

Key tests:
- `test_insert_and_read_event` — basic roundtrip
- `test_insert_with_embedding` — event + vector stored together
- `test_read_events_with_filters` — status and type filters
- `test_search_fts` — keyword search matches summaries
- `test_search_fts_malformed_query` — returns empty, no error
- `test_search_vector` — KNN returns nearest events
- `test_search_by_metadata` — topic and type filtering

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Create `nanobot/memory/db/event_store.py`**

Move `insert_event`, `read_events`, `search_vector`, `search_fts`, `search_by_metadata` from `unified_db.py`. The class receives a `sqlite3.Connection` (not `MemoryDatabase`) to avoid circular imports.

- [ ] **Step 4: Update `nanobot/memory/db/__init__.py`** to export `EventStore`

- [ ] **Step 5: Add `event_store` property to `MemoryDatabase`**

```python
@property
def event_store(self) -> EventStore:
    if self._event_store is None:
        self._event_store = EventStore(self._conn)
    return self._event_store
```

- [ ] **Step 6: Run tests, lint, typecheck**

- [ ] **Step 7: Commit**

```bash
git commit -m "refactor(memory): create EventStore for event CRUD and search"
```

---

## Task 3: Create GraphStore

**Files:**
- Create: `nanobot/memory/db/graph_store.py`
- Modify: `nanobot/memory/db/__init__.py` (add export)
- Test: `tests/test_graph_store.py`

- [ ] **Step 1: Create test file for GraphStore**

Key tests:
- `test_upsert_and_get_entity` — entity roundtrip
- `test_search_entities` — name/alias substring match
- `test_add_and_get_edges` — edge creation and directional queries
- `test_get_neighbors` — BFS traversal up to depth
- `test_neighbors_depth_clamped` — depth clamped to [1, 5]

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Create `nanobot/memory/db/graph_store.py`**

Move `upsert_entity`, `get_entity`, `search_entities`, `add_edge`, `get_edges_from`, `get_edges_to`, `get_neighbors` from `unified_db.py`.

- [ ] **Step 4: Update exports and add `graph_store` property to `MemoryDatabase`**

- [ ] **Step 5: Run tests, lint, typecheck**

- [ ] **Step 6: Commit**

```bash
git commit -m "refactor(memory): create GraphStore for entity/edge CRUD and traversal"
```

---

## Task 4: Migrate internal memory consumers to new repositories

This is the largest task — update all files inside `nanobot/memory/` that use `UnifiedMemoryDB` to use the appropriate new class.

**Files to modify:** store.py, ingester.py, retriever.py, context_assembler.py, graph.py, profile_io.py, snapshot.py, conflicts.py, consolidation_pipeline.py, maintenance.py, strategy.py, `__init__.py`

- [ ] **Step 1: Update `store.py`**

Replace `UnifiedMemoryDB` with `MemoryDatabase`. Replace `self.db` with `self.db` (same attribute name, new type). Pass `self.db.event_store` to consumers that need event operations, `self.db.graph_store` to graph consumers. Pass `self.db` directly to consumers that need profile/history/snapshot.

Key changes:
- `from .db import MemoryDatabase` replaces `from .unified_db import UnifiedMemoryDB`
- `self.db: MemoryDatabase = MemoryDatabase(...)` replaces `UnifiedMemoryDB(...)`
- `EventIngester(db=self.db.event_store, ...)` replaces `db=self.db`
- `MemoryRetriever(db=self.db.event_store, ...)` replaces `db=self.db`
- `KnowledgeGraph(db=self.db.graph_store)` replaces `db=self.db`
- Consumers using profile/history/snapshot keep `db=self.db`

- [ ] **Step 2: Update `write/ingester.py`**

Change `db: UnifiedMemoryDB` parameter to `db: EventStore`. Update TYPE_CHECKING import. Methods used: `insert_event`, `read_events`.

- [ ] **Step 3: Update `read/retriever.py`**

Change `db: UnifiedMemoryDB` parameter to `db: EventStore`. Methods used: `search_vector`, `search_fts`, `search_by_metadata` (via `_retrieve_unified`).

- [ ] **Step 4: Update `graph/graph.py`**

Change `db: UnifiedMemoryDB` parameter to `db: GraphStore`. Remove the backward-compat `workspace=` path that creates an internal `UnifiedMemoryDB`. Methods used: `upsert_entity`, `get_entity`, `search_entities`, `add_edge`, `get_edges_from`, `get_edges_to`, `get_neighbors`.

- [ ] **Step 5: Update `persistence/profile_io.py`**

Change `db: UnifiedMemoryDB` to `db: MemoryDatabase`. Methods used: `read_profile`, `write_profile`, `search_fts` (via `_find_supporting_events`). Note: `search_fts` is on `EventStore`, so ProfileStore needs access to both `MemoryDatabase` (for profile CRUD) and `EventStore` (for FTS search). Pass both, or pass `MemoryDatabase` and access `db.event_store.search_fts()`.

- [ ] **Step 6: Update `persistence/snapshot.py`**

Change `db: UnifiedMemoryDB` to `db: MemoryDatabase`. Methods used: `read_events` (EventStore), `read_snapshot`, `write_snapshot` (MemoryDatabase). Similar pattern: pass `MemoryDatabase` and access `db.event_store` for read_events.

- [ ] **Step 7: Update `write/conflicts.py`**

Change `db: UnifiedMemoryDB` to `db: MemoryDatabase`. Methods used: none directly (delegates to profile_mgr). Check if any method calls `self._db.*` — if not, the type change is annotation-only.

- [ ] **Step 8: Update `consolidation_pipeline.py`**

Change `db: UnifiedMemoryDB` to `db: MemoryDatabase`. Methods used: `append_history`, `read_snapshot`.

- [ ] **Step 9: Update `maintenance.py`**

Change `db: UnifiedMemoryDB` to `db: MemoryDatabase`. Methods used: `read_events`, `insert_event` (EventStore operations). Pass `MemoryDatabase` and access `db.event_store`.

- [ ] **Step 10: Update `read/context_assembler.py`**

Change `db: UnifiedMemoryDB` to `db: MemoryDatabase`. Methods used: `read_snapshot`.

- [ ] **Step 11: Update `strategy.py`**

Update docstrings referencing `UnifiedMemoryDB`. The class uses `connection` (raw sqlite3.Connection), which is still available on `MemoryDatabase.connection`.

- [ ] **Step 12: Update `memory/__init__.py`**

Replace `UnifiedMemoryDB` export with `MemoryDatabase`:
```python
from .db import MemoryDatabase
# Remove: from .unified_db import UnifiedMemoryDB
```
Update `__all__`.

- [ ] **Step 13: Move `STRATEGIES_DDL` to `constants.py`**

Move the `STRATEGIES_DDL` constant from `unified_db.py` to `constants.py`. Update test imports that use it.

- [ ] **Step 14: Run full test suite**

Run: `make lint && make typecheck && PYTHONPATH=. python -m pytest tests/ --ignore=tests/integration -x -q`
Expected: ALL PASS

- [ ] **Step 15: Commit**

```bash
git commit -m "refactor(memory): migrate internal consumers from UnifiedMemoryDB to db/ repositories"
```

---

## Task 5: Migrate external consumers and tests

**Files to modify:** feedback_context.py, feedback.py, setup.py, agent_factory.py, memory_eval.py, 13 test files

- [ ] **Step 1: Update `nanobot/context/feedback_context.py`**

Change `db: UnifiedMemoryDB` to `db: MemoryDatabase`. Methods used: `read_events` — this needs `EventStore`. Since this function is called with `store.db` from `context.py`, and `store.db` is now `MemoryDatabase`, update to use `db.event_store.read_events()`.

- [ ] **Step 2: Update `nanobot/tools/builtin/feedback.py`**

Change `db: UnifiedMemoryDB` to `db: MemoryDatabase`. Methods used: `insert_event` — needs `EventStore`. Update to `self._db.event_store.insert_event()`.

- [ ] **Step 3: Update `nanobot/tools/setup.py`**

Update TYPE_CHECKING import and parameter annotation.

- [ ] **Step 4: Update `nanobot/agent/agent_factory.py`**

Update the comment referencing `UnifiedMemoryDB`. The actual construction is in `store.py` which is already updated.

- [ ] **Step 5: Update `nanobot/eval/memory_eval.py`**

Change TYPE_CHECKING import. Methods used: check what EvalRunner actually calls on `db`.

- [ ] **Step 6: Update all 13 test files**

For each test file that imports `UnifiedMemoryDB`:
- Replace `from nanobot.memory.unified_db import UnifiedMemoryDB` with `from nanobot.memory.db import MemoryDatabase`
- Replace `UnifiedMemoryDB(path, dims=N)` with `MemoryDatabase(path, dims=N)`
- For tests that need `EventStore` or `GraphStore`, access via `db.event_store` / `db.graph_store`
- For tests importing `STRATEGIES_DDL`, update import to `from nanobot.memory.constants import STRATEGIES_DDL`

Test files: test_unified_db.py (rename to test_memory_database.py or merge), test_knowledge_graph.py, test_profile_store.py, test_ingester.py, test_feedback.py, test_consumer_migration.py, test_strategy_store.py, test_strategy_extractor.py, test_embedder.py, test_coverage_gaps.py, test_profile_correction.py, contract/test_memory_wiring.py, integration/test_feedback_roundtrip.py

- [ ] **Step 7: Run full test suite**

- [ ] **Step 8: Commit**

```bash
git commit -m "refactor(memory): migrate external consumers and tests to db/ repositories"
```

---

## Task 6: Delete UnifiedMemoryDB and final cleanup

**Files:**
- Delete: `nanobot/memory/unified_db.py`

- [ ] **Step 1: Delete `nanobot/memory/unified_db.py`**

- [ ] **Step 2: Grep for zero remaining references**

```bash
grep -rn "UnifiedMemoryDB" nanobot/ tests/ --include="*.py"
grep -rn "unified_db" nanobot/ tests/ --include="*.py"
```

Both must return zero matches (excluding docs/ and .md files). Fix any remaining references.

- [ ] **Step 3: Clear mypy cache and re-run**

```bash
rm -rf .mypy_cache && make typecheck
```

- [ ] **Step 4: Run `make pre-push`**

Full CI validation including coverage gate.

- [ ] **Step 5: Commit**

```bash
git commit -m "refactor(memory): delete UnifiedMemoryDB — replaced by db/ package

UnifiedMemoryDB (502 LOC god-repository) replaced by:
- MemoryDatabase: connection mgmt + profile/history/snapshot CRUD
- EventStore: event CRUD + FTS5 + vector search
- GraphStore: entity/edge CRUD + BFS traversal

All share one SQLite connection. Zero remaining references."
```

---

## Deviations from Assessment

The assessment proposed 6 separate repository files (event, profile, graph, snapshot, strategy). This plan consolidates:
- **Profile, history, snapshot CRUD stays on MemoryDatabase** — each is ~12 LOC of trivial key-value operations. Separate files would be ceremony over substance.
- **Strategy table DDL moves to constants.py** — `StrategyAccess` already manages its own table logic via raw connection; it doesn't need a repository class.
- **Result: 3 files in db/ instead of 6** — same decoupling benefit, less boilerplate.
