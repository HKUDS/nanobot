# Memory Storage Redesign: Unified SQLite + Direct Embeddings

**Date:** 2026-03-23
**Status:** Draft
**Scope:** Replace mem0 with unified SQLite storage (sqlite-vec + FTS5),
direct embeddings, single-tool consolidation. Phase 1 only — knowledge
graph deferred to Phase 2.

## Problem

The memory subsystem has a fundamental reliability and complexity problem:

1. **mem0 fails more than it succeeds.** Production metrics show 272 write
   failures vs 171 successes. The 874-line adapter is defensive workarounds
   for an unstable SDK.

2. **Dual-write creates consistency problems.** Events are written to both
   `events.jsonl` (reliable) and mem0/Qdrant (unreliable). When mem0 writes
   fail, the vector store diverges from ground truth. 17 reindex runs are
   the symptom.

3. **~1,246 lines are dead code.** `mem0_adapter.py` (874), `retrieval.py`
   (285 — BM25 replaced by FTS5), and `persistence.py` (87 — file I/O
   replaced by SQLite).

4. **Consolidation wastes an LLM call.** Two LLM calls per consolidation,
   but the first call's `memory_update` output is a simple summary that can
   be combined with the second call's structured extraction.

5. **The production vector path has zero test coverage.** All tests use
   `embedding_provider="hash"` which forces BM25-only. A regression in
   vector search would be invisible.

## Solution

### 1. Unified SQLite Database (`unified_db.py`, ~250 lines)

Replace `events.jsonl` + `profile.json` + mem0/Qdrant + `HISTORY.md` +
`MEMORY.md` with a single SQLite database (`memory.db`) using FTS5 for
keyword search and sqlite-vec for vector search.

**Schema:**

```sql
-- Events (replaces events.jsonl)
-- NOTE: Do NOT add WITHOUT ROWID — events_vec depends on implicit rowid.
CREATE TABLE events (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,
    summary     TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    source      TEXT,
    status      TEXT DEFAULT 'active',
    metadata    TEXT,  -- JSON blob
    created_at  TEXT NOT NULL
);

-- Full-text search over event summaries (replaces BM25 over events.jsonl)
CREATE VIRTUAL TABLE events_fts USING fts5(
    summary,
    content=events,
    content_rowid=rowid
);

-- FTS5 content-sync triggers (required for content= tables).
-- These keep events_fts in sync with the events table automatically.
CREATE TRIGGER events_ai AFTER INSERT ON events BEGIN
    INSERT INTO events_fts(rowid, summary) VALUES (new.rowid, new.summary);
END;
CREATE TRIGGER events_ad AFTER DELETE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, summary)
        VALUES('delete', old.rowid, old.summary);
END;
CREATE TRIGGER events_au AFTER UPDATE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, summary)
        VALUES('delete', old.rowid, old.summary);
    INSERT INTO events_fts(rowid, summary) VALUES (new.rowid, new.summary);
END;

-- Vector embeddings (replaces mem0/Qdrant)
-- id maps to events.rowid (the implicit SQLite integer rowid),
-- NOT to events.id (which is TEXT). Use last_insert_rowid() after
-- inserting into events to get the correct id for events_vec.
CREATE VIRTUAL TABLE events_vec USING vec0(
    id        INTEGER PRIMARY KEY,
    embedding float[{dims}] distance_metric=cosine
);

-- Profile (replaces profile.json)
CREATE TABLE profile (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL  -- JSON blob
);

-- History (replaces HISTORY.md)
CREATE TABLE history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    entry      TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Snapshots (replaces MEMORY.md file)
CREATE TABLE snapshots (
    key        TEXT PRIMARY KEY,  -- 'current', 'user_pinned'
    content    TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

The `{dims}` in `events_vec` is set at database creation time based on the
embedding model (1536 for `text-embedding-3-small`, 384 for local ONNX test
model).

**MEMORY.md is now in SQLite.** The `snapshots` table stores the generated
memory snapshot (`key='current'`) and user-pinned content
(`key='user_pinned'`). `MemorySnapshot` rebuilds `snapshots['current']`
from profile + events during consolidation, merging in any user-pinned
content. `ContextAssembler` reads from `snapshots['current']` instead of
a file. This eliminates desync between manual edits and rebuilds.

**Key methods on `UnifiedMemoryDB`:**
- `insert_event(event, embedding)` — single transaction: events + FTS5 + vec
- `search_vector(query_embedding, k)` — KNN via sqlite-vec
- `search_fts(query_text, k)` — keyword search via FTS5
- `search_by_metadata(topic, memory_type, k)` — fallback when vector/FTS
  return few results
- `read_profile(key)` / `write_profile(key, value)` — profile CRUD
- `append_history(entry)` — history writes
- `read_events(limit, status)` — replaces `persistence.read_jsonl()`
- `read_snapshot(key)` / `write_snapshot(key, content)` — snapshot CRUD

**Async strategy:** SQLite operations are synchronous but fast (<10ms for
all operations at nanobot's scale). All `UnifiedMemoryDB` public methods
are synchronous. Callers that need async compatibility (e.g., `retriever.py`,
`ingester.py`) wrap calls with `asyncio.to_thread()` where needed. This
avoids the complexity of `aiosqlite` while keeping the event loop unblocked
for any operation that might exceed 1-2ms.

**Key properties:**
- ACID transactions — no dual-write consistency problem
- WAL mode for concurrent reads
- One file (`memory.db`) instead of 5+ files
- sqlite-vec KNN at ~5-7ms for <1000 vectors (brute-force, sufficient at
  nanobot's scale)

### 2. Direct Embedding Pipeline (`embedder.py`, ~120 lines)

Nanobot owns the embedding pipeline directly — no mem0 middleman.

```python
class Embedder(Protocol):
    """Protocol for embedding providers. Two implementations shipped."""
    async def embed(self, text: str) -> list[float]: ...
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...
    @property
    def dims(self) -> int: ...
    @property
    def available(self) -> bool: ...

class OpenAIEmbedder:
    """Production: OpenAI text-embedding-3-small (1536 dims)."""
    def __init__(self, model: str = "text-embedding-3-small") -> None

class LocalEmbedder:
    """Tests: ONNX all-MiniLM-L6-v2 (384 dims). No API key needed."""
    def __init__(self, model: str = "all-MiniLM-L6-v2") -> None
```

Both implement the `Embedder` protocol. `OpenAIEmbedder` is the default
in production; `LocalEmbedder` is used in all tests.

**Vector search is mandatory.** If no embedding capability is available,
memory retrieval returns empty. The agent works without memory context
but the user is informed — `ContextAssembler.build()` returns a notice:

```
[Memory unavailable: no embedding provider configured. Memory retrieval
is disabled for this session.]
```

This notice appears in the conversation prompt, not just in logs, so the
user always knows when memory is offline.

**Embedding happens at three points:**
- At write time: `ingester.append_events()` embeds each event summary
- At query time: `retriever.retrieve()` embeds the query string
- At reindex time: `maintenance.reindex()` batch-embeds all events

**Testing:** All tests use `LocalEmbedder` (ONNX, 384 dims). ONNX Runtime
is a required test dependency (already present for the cross-encoder
reranker). There is no hash-based fallback — tests exercise the real
vector path.

### 3. Unified Retrieval Pipeline

Replace the dual-path (mem0 vs BM25) with a single fused pipeline.

**Current architecture (retriever.py, 1,107 lines):**
```
if mem0.enabled:
    _retrieve_mem0_path()  → vector via mem0 → merge BM25 supplement → rerank
else:
    _retrieve_bm25_path()  → BM25 only → score → no rerank
```

**New architecture (retriever.py, ~400 lines estimated):**
```
retrieve(query):
    plan = planner.plan(query)

    # 1. Embed query
    query_vec = await embedder.embed(query)

    # 2. Dual source — always both
    vec_results = db.search_vector(query_vec, k=candidate_k)
    fts_results = db.search_fts(query, k=candidate_k)

    # 3. Fuse via Reciprocal Rank Fusion (vector weight 0.7)
    candidates = _fuse_results(vec_results, fts_results)

    # 4. Same pipeline as today (kept unchanged)
    filtered = _filter_items(candidates, plan)
    scored = _score_items(filtered, plan, profile)
    reranked = _rerank_items(query, scored)
    return reranked[:top_k]
```

**What's deleted from retriever.py:**
- `_retrieve_mem0_path()` / `_retrieve_bm25_path()` — dual-path dispatch
- `_source_from_mem0()` / `_source_from_bm25()` — separate sourcing
- `_merge_graph_bm25_supplement()` — no longer needed, FTS5 handles keywords
- `_inject_rollout_status()` — synthetic rollout records
- Shadow mode comparison

**What's kept in retriever.py:**
- `_filter_items()`, `_score_items()`, `_rerank_items()` — scoring/reranking
- `_augment_query_with_graph()` — kept for Phase 2 (no-op when disabled)
- `_graph_cache` — stays, ready for Phase 2
- `RetrievalPlanner` intent classification
- Cross-encoder reranking

**What's added:**
- `_fuse_results(vec_results, fts_results, vector_weight=0.7)` — RRF
  fusion (~30 lines)

### 4. Single-Tool Consolidation

Merge the two separate LLM calls into one call with a combined tool schema.

**Current (2 LLM calls in consolidation_pipeline.py):**
1. LLM → `save_memory` tool → `history_entry`
2. LLM → `save_events` tool → `events` + `profile_updates`

**New (1 LLM call):**
```python
_CONSOLIDATE_TOOL = {
    "type": "function",
    "function": {
        "name": "consolidate_memory",
        "parameters": {
            "type": "object",
            "properties": {
                "history_entry": {
                    "type": "string",
                    "description": "Summary of key events, decisions, and topics"
                },
                "events": {
                    "type": "array",
                    "items": { ... },  # same schema as current save_events
                    "description": "Structured memory events from conversation"
                },
                "profile_updates": {
                    "type": "object",
                    "description": "Updates to user profile sections"
                },
            },
            "required": ["history_entry", "events"],
        },
    },
}
```

**Forced invocation:**
`tool_choice={"type": "function", "function": {"name": "consolidate_memory"}}`

This guarantees the LLM calls the tool. The `required` fields ensure both
`history_entry` and `events` are present. One call, one tool, guaranteed.

**Provider compatibility:** The `tool_choice` format above is OpenAI's.
The project uses litellm which normalizes `tool_choice` across providers
(Anthropic, Google, etc.). No provider-specific handling is needed in
`consolidation_pipeline.py`.

**Fallback chain** if the combined call fails:
1. Parse whatever fields the LLM did return (partial success — if
   `history_entry` is present but `events` is malformed, keep the history)
2. For missing `events` → fall back to `MemoryExtractor` heuristic
   extraction (existing code in `extractor.py`)
3. For missing `history_entry` → generate from first 2-3 conversation
   turns heuristically
4. Log the partial failure for observability

**What changes in `consolidation_pipeline.py`:**
- Delete the separate `extract_structured_memory()` call
- Merge prompts into one
- Parse the single tool-call response for all three fields
- Add fallback chain for partial failures
- Update `consolidation.md` prompt template

### 5. Dead Code Deletion (Phase 1)

| Module | Lines | Reason |
|--------|-------|--------|
| `mem0_adapter.py` | 874 | Replaced by `unified_db.py` + `embedder.py` |
| `retrieval.py` | 285 | BM25 replaced by FTS5 in SQLite |
| `persistence.py` | 87 | File I/O replaced by `unified_db.py` |

**Total: ~1,246 lines deleted**

**Kept for Phase 2 decision:**
- `graph.py` (608) — disabled, untouched
- `entity_classifier.py` (590) — only used by graph
- `entity_linker.py` (54) — only used by graph
- `ontology.py` + `ontology_rules.py` + `ontology_types.py` (~575) — graph support

**Rollout flags cleaned up in `rollout.py`:**
- Remove: all `mem0_*` flags, `memory_history_fallback_enabled`,
  `memory_shadow_mode`, `memory_shadow_sample_rate`,
  `memory_fallback_allowed_sources`
- Keep: `reranker_*`, `memory_router_enabled`, `memory_reflection_enabled`,
  `memory_type_separation_enabled`, `graph_enabled`

### 6. Migration

A one-time migration (`migration.py`, ~80 lines) converts existing
production data when `memory.db` doesn't exist but old files do.

**Steps:**
1. Read `events.jsonl` → insert into `events` table + `events_fts`
2. Embed all event summaries → insert into `events_vec`
3. Read `profile.json` → insert into `profile` table
4. Read `HISTORY.md` → parse entries → insert into `history` table
5. Read `MEMORY.md` → insert into `snapshots` table (extract user-pinned
   section if present into `snapshots['user_pinned']`, rest into
   `snapshots['current']`)
6. Rename old files to `.bak` backups

Runs automatically on first `MemoryStore` construction. If the embedder
is unavailable during migration, events are inserted without vectors and
a warning is logged. A subsequent `maintenance.reindex()` will backfill
embeddings when an embedder becomes available.

**Rollback:** Old files are kept as `.bak` for manual recovery. To revert:
delete `memory.db`, rename `.bak` files back to originals, and revert the
code to the pre-migration commit. This is a manual procedure — no automated
rollback is provided since the migration is a one-way schema change.

**Concurrency:** Migration is guarded by SQLite file locking. Nanobot is
single-process, so concurrent migration is not expected, but the SQLite
lock prevents corruption if it somehow occurs.

### 7. Modules Requiring Updates (Not Deleted)

These modules import from `mem0_adapter`, `persistence`, or `retrieval`
and must be updated to use `UnifiedMemoryDB` + `Embedder`:

| Module | Change |
|--------|--------|
| `store.py` | Wire `UnifiedMemoryDB` + `Embedder`, remove `mem0` and `persistence` |
| `ingester.py` | Write via `db.insert_event(event, embedding)` instead of `persistence` + `mem0` |
| `retriever.py` | Single fused pipeline (Section 3 above) |
| `consolidation_pipeline.py` | Single combined tool (Section 4 above) |
| `snapshot.py` | Read/write via `db.read_snapshot()` / `db.write_snapshot()` |
| `maintenance.py` | Reindex via `db` + `embedder.embed_batch()` |
| `conflicts.py` | Replace `self.mem0` search/delete with `db` operations |
| `profile_io.py` | Replace `ProfileCache` file reads with `db.read_profile()` |
| `context_assembler.py` | Read snapshot from `db`, add embedder-unavailable notice. Replace `MemoryPersistence` constructor param/import with `UnifiedMemoryDB` |
| `rollout.py` | Remove mem0/shadow flags |
| `eval.py` | Update to use `LocalEmbedder` for eval runs. Replace `MemoryPersistence` import with `UnifiedMemoryDB` |
| `__init__.py` | Remove `_Mem0Adapter`, `_Mem0RuntimeInfo`, `MemoryPersistence` from imports and `__all__`. Add `UnifiedMemoryDB`, `Embedder` |

**`MemoryPersistence` migration note:** `persistence.py` is imported by
7+ modules (`context_assembler.py`, `consolidation_pipeline.py`, `eval.py`,
`ingester.py`, `maintenance.py`, `profile_io.py`, `snapshot.py`). Each
must replace its `MemoryPersistence` dependency with `UnifiedMemoryDB`.
The `MemoryPersistence` class is fully removed (no backward-compat shim)
since all callers are internal to the memory subsystem.

**`profile_io.py` mem0 surface:** `ProfileStore.__init__` currently takes
`mem0: _Mem0Adapter` as a constructor argument for mem0-based profile sync.
This parameter and all mem0 usage within `ProfileStore` must be removed.
Profile reads/writes go through `db.read_profile()` / `db.write_profile()`.

### 8. Execution Phases

**Phase 1 (this spec) — Storage layer swap:**
1. Create `unified_db.py` — SQLite + FTS5 + sqlite-vec
2. Create `embedder.py` — OpenAI + local ONNX
3. Create `migration.py` — old format → SQLite
4. Update `ingester.py` — write to `UnifiedMemoryDB`
5. Update `retriever.py` — single fused pipeline (vector + FTS5 + RRF)
6. Update `consolidation_pipeline.py` — single combined tool
7. Update `snapshot.py`, `maintenance.py`, `conflicts.py`, `profile_io.py` — replace `MemoryPersistence` + `mem0` with `UnifiedMemoryDB`
8. Update `store.py` — wire `UnifiedMemoryDB` + `Embedder`, remove mem0 (after all consumers are migrated)
9. Update `context_assembler.py` — read snapshot from DB, add unavailable notice
10. Delete `mem0_adapter.py`, `retrieval.py`, `persistence.py`
11. Clean up `rollout.py` — remove mem0/shadow flags
12. Update tests — ONNX embedder, real vector path
13. Final validation — `make check`

**Phase 2 (future) — Knowledge graph decision:**
- Decide: wire graph into SQLite (entities/edges tables) or delete it
- If kept: migrate `knowledge_graph.json` → SQLite, update `ingester.py`
  and `retriever.py` graph integration
- If deleted: remove `graph.py`, `entity_classifier.py`, `entity_linker.py`,
  `ontology*.py` (~1,877 lines)

## Testing Strategy

### Contract tests (no API key needed)
Use `LocalEmbedder` (ONNX, 384 dims) for all contract tests. These verify
behavioral invariants with real vector search — not the BM25 degradation
path. ONNX Runtime is a required test dependency.

### Integration tests (needs API key)
Use `OpenAIEmbedder` (1536 dims) for production-path testing:
- Vector search returns semantically similar events
- RRF fusion ranks hybrid matches above keyword-only or vector-only
- Reindex preserves all events and embeddings
- Migration produces correct data from old format
- Single-tool consolidation produces valid structured output

## Dependencies

### New Python packages
- `sqlite-vec` (v0.1.7+) — pre-built wheels for Linux x86_64, macOS,
  Windows x64. Verify `pip install sqlite-vec` on dev environment
  (Windows 11 x64, Python 3.10+) before implementation begins.
- ONNX Runtime — already a dependency (used by cross-encoder reranker)

### Removed Python packages
- `mem0ai` — no longer needed
- `qdrant-client` — no longer needed (was a mem0 transitive dependency)

### API keys
- `OPENAI_API_KEY` — required for production embeddings and integration tests
- No key needed for contract tests (local ONNX embedder)

## Expected Results

| Metric | Before | After |
|--------|--------|-------|
| Storage files | events.jsonl + profile.json + Qdrant + MEMORY.md + HISTORY.md | memory.db (single file) |
| External dependencies | mem0, Qdrant | sqlite-vec (pip wheel) |
| Write failures | 272 (60% failure rate) | 0 (SQLite ACID) |
| Vector search latency | ~50ms (mem0 overhead) | ~5-7ms (sqlite-vec) |
| Retrieval paths | 2 (mem0 vs BM25) | 1 (vector + FTS5 fused) |
| LLM calls per consolidation | 2 | 1 |
| Dead code deleted | — | ~1,246 lines |
| Production vector test coverage | 0% | Full (contract + integration) |

## Out of Scope

- Knowledge graph changes (Phase 2)
- Multi-user memory isolation
- Approximate nearest neighbor indexing (brute-force sufficient at <1000 events)
- LLM-as-judge evaluation
- Performance benchmarking beyond basic latency verification
