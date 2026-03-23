# Memory Storage Redesign: Unified SQLite + Direct Embeddings

**Date:** 2026-03-22
**Status:** Draft
**Scope:** Replace mem0 with unified SQLite storage (sqlite-vec + FTS5),
direct OpenAI embeddings, single-tool consolidation, delete ~2,348 lines
of dead code.

## Problem

The memory subsystem has a fundamental reliability and complexity problem:

1. **mem0 fails more than it succeeds.** Production metrics show 272 write
   failures vs 171 successes. The 874-line adapter is defensive workarounds
   for an unstable SDK.

2. **Dual-write creates consistency problems.** Events are written to both
   `events.jsonl` (reliable) and mem0/Qdrant (unreliable). When mem0 writes
   fail, the vector store diverges from ground truth. 17 reindex runs are
   the symptom.

3. **~2,348 lines are dead code.** The knowledge graph (graph.py + ontology
   system) is disabled in production. BM25 retrieval functions in retrieval.py
   are replaced by FTS5.

4. **Consolidation wastes an LLM call.** Two LLM calls per consolidation,
   but the first call's `memory_update` output is discarded (since LAN-206).

5. **The production vector path has zero test coverage.** All tests use
   `embedding_provider="hash"` which forces BM25-only. A regression in
   vector search would be invisible.

## Solution

### 1. Unified SQLite Database (`unified_db.py`, ~250 lines)

Replace `events.jsonl` + `profile.json` + mem0/Qdrant + `history.db` with
a single SQLite database (`memory.db`) using FTS5 for keyword search and
sqlite-vec for vector search.

**Schema:**

```sql
-- Events (replaces events.jsonl)
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
-- NOTE: content-sync table requires INSERT/UPDATE/DELETE triggers to stay
-- in sync with the events table. UnifiedMemoryDB must create these triggers
-- or call `INSERT INTO events_fts(events_fts) VALUES('rebuild')` after
-- bulk operations.
CREATE VIRTUAL TABLE events_fts USING fts5(
    summary,
    content=events,
    content_rowid=rowid
);

-- Vector embeddings (replaces mem0/Qdrant)
-- NOTE: id maps to events.rowid (the implicit SQLite integer rowid),
-- NOT to events.id (which is TEXT). Use last_insert_rowid() after inserting
-- into events to get the correct id for events_vec.
CREATE VIRTUAL TABLE events_vec USING vec0(
    id        INTEGER PRIMARY KEY,
    embedding float[{dims}] distance_metric=cosine
);

-- Profile (replaces profile.json)
CREATE TABLE profile (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL  -- JSON blob
);

-- History (replaces HISTORY.md append-only text)
CREATE TABLE history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    entry      TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

The `{dims}` in `events_vec` is set at database creation time based on the
embedding model (1536 for `text-embedding-3-small`, 384 for local ONNX test
model).

**MEMORY.md:** Remains as a file (not migrated to SQLite). It is a
deterministic projection rebuilt by `MemorySnapshot` from profile + events
data in SQLite. It is injected directly into LLM prompts.

**Key properties:**
- ACID transactions — no dual-write consistency problem
- WAL mode for concurrent reads
- One file (`memory.db`) instead of 5+ files
- sqlite-vec KNN at ~5-7ms for <1000 vectors (brute-force, sufficient at
  nanobot's scale)

### 2. Direct Embedding Pipeline (`embedder.py`, ~120 lines)

Nanobot owns the embedding pipeline directly — no mem0 middleman.

```python
class Embedder:
    """Production embedder using OpenAI API."""
    def __init__(self, model: str = "text-embedding-3-small") -> None
    async def embed(self, text: str) -> list[float]
    async def embed_batch(self, texts: list[str]) -> list[list[float]]
    @property
    def dims(self) -> int
    @property
    def available(self) -> bool

class LocalEmbedder(Embedder):
    """Test embedder using local ONNX model (no API key needed)."""
    def __init__(self, model: str = "all-MiniLM-L6-v2") -> None
    # Same interface, 384 dims, runs via ONNX Runtime
```

**Vector search is mandatory.** If no embedding capability is available,
memory retrieval does not function (the agent works without memory context,
same as an empty memory store). There is no "hash" fallback mode.

**Embedding happens:**
- At write time: `ingester.append_events()` embeds each event summary
- At reindex time: `maintenance.reindex()` batch-embeds all events
- At query time: `retriever.retrieve()` embeds the query string

**Embedding cache:** Content-hash lookup in `events_vec` — skip re-embedding
unchanged events during reindex.

### 3. Unified Retrieval Pipeline

Vector search is the primary retrieval path. FTS5 keyword search supplements
it. Both are fused via Reciprocal Rank Fusion (RRF).

```python
def retrieve(self, query, top_k=10, ...):
    plan = self._planner.plan(query, ...)

    # Primary: vector search (cosine similarity)
    query_vec = await self._embedder.embed(query)
    vec_results = self._db.search_vector(query_vec, k=candidate_k)

    # Supplement: FTS5 keyword search (catches exact term matches)
    fts_results = self._db.search_fts(query, k=candidate_k)

    # Fuse: RRF with vector weight 0.7
    candidates = self._fuse_results(vec_results, fts_results, vector_weight=0.7)

    # Same pipeline as today
    filtered = self._filter_items(candidates, plan, ...)
    scored = self._score_items(filtered, plan, ...)
    reranked = self._rerank_items(query, scored)
    return reranked[:top_k]
```

**What's removed from retriever.py:**
- `_source_from_mem0()` / `_source_from_bm25()` / `_retrieve_mem0_path()` /
  `_retrieve_bm25_path()` — dual-path dispatch
- Shadow mode comparison
- `_inject_rollout_status()` — synthetic rollout records
- `_merge_graph_bm25_supplement()` — graph BM25 supplement

**Topic/metadata fallback:** The current `_topic_fallback_retrieve` from
`retrieval.py` fills remaining slots by matching event metadata (type, topic)
when BM25 returns too few candidates. This is replaced by a SQL query
against `events.type` and `events.metadata` in `UnifiedMemoryDB`:
```python
def search_by_metadata(self, topic: str, memory_type: str, k: int) -> list[dict]:
    """Fallback retrieval by event metadata when vector/FTS return few results."""
```

**What's added:**
- `_fuse_results()` — RRF fusion (~30 lines)

**What's preserved:**
- `_filter_items()`, `_score_items()`, `_rerank_items()` — the unified pipeline
- `_augment_query_with_graph()` — kept but no-op when graph disabled
- `_build_graph_context_lines()` — kept for ContextAssembler (returns empty)
- Intent routing via `RetrievalPlanner`
- Cross-encoder reranking

### 4. Single-Tool Consolidation

Merge the two separate LLM calls into one call with a combined tool schema.

**Combined tool:**
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
                    "description": "Structured memory events extracted from conversation"
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

**Forced invocation:** `tool_choice={"type": "function", "function": {"name": "consolidate_memory"}}`

This guarantees the LLM calls the tool. The `required` fields ensure both
`history_entry` and `events` are present. One call, one tool, guaranteed.

**What changes in `consolidation_pipeline.py`:**
- Delete the separate `extract_structured_memory()` call
- Merge prompts into one
- Parse the single tool-call response for all three fields
- Update `consolidation.md` prompt template

### 5. Dead Code Deletion

| Module | Lines | Reason |
|--------|-------|--------|
| `mem0_adapter.py` | 874 | Replaced by `UnifiedMemoryDB` + `Embedder` |
| `graph.py` | 608 | Disabled in production, too sparse for value |
| `entity_classifier.py` | 590 | Only used by graph.py |
| `entity_linker.py` | 6 | Only used by graph.py |
| `ontology.py` | 6 | Re-exports for graph |
| `ontology_rules.py` | 29 | Only used by ontology |
| `ontology_types.py` | 116 | Only used by ontology |
| `retrieval.py` | 119 | BM25 functions replaced by FTS5 |

**Total: ~2,348 lines deleted**

### 6. Migration

A one-time migration script (`migration.py`, ~80 lines) converts existing
production data:

1. Read `events.jsonl` → insert into `events` table + `events_fts`
2. Embed all event summaries → insert into `events_vec`
3. Read `profile.json` → insert into `profile` table
4. Read `HISTORY.md` → parse entries → insert into `history` table
5. Keep old files as `.bak` backups

The migration runs automatically on first access if `memory.db` doesn't exist
but old files do.

## Execution Order

### Phase 1: Foundation (new modules, no deletions)
1. Create `unified_db.py` — SQLite + FTS5 + sqlite-vec
2. Create `embedder.py` — OpenAI + local ONNX embedder
3. Create `migration.py` — old format → SQLite

### Phase 2: Wire new storage
4. Update `ingester.py` — write to `UnifiedMemoryDB`
5. Update `retriever.py` — vector-primary + FTS5 supplement + RRF
6. Update `store.py` — wire `UnifiedMemoryDB` + `Embedder`

### Phase 3: Update remaining modules
7. Update `maintenance.py` — reindex via `UnifiedMemoryDB` + `Embedder`
8. Update `snapshot.py` — read from `UnifiedMemoryDB`
9. Update `consolidation_pipeline.py` — single combined tool
10. Simplify `rollout.py` — remove mem0-specific flags
11. Update `conflicts.py` — replace `self.mem0` usage with `UnifiedMemoryDB`
    operations (search/delete for conflict resolution)
12. Update `profile.py` — remove `_Mem0Adapter` dependency, replace
    `_find_mem0_id_for_text` with `UnifiedMemoryDB` lookup

### Phase 4: Delete dead code
11. Delete mem0_adapter.py, graph.py, ontology system, retrieval.py
12. Update `__init__.py` exports
13. Clean up or delete `persistence.py`

### Phase 5: Tests + validation
14. Update existing tests to use local ONNX embedder
15. Add integration tests with real OpenAI embeddings
16. Run migration on production data
17. Final validation — `make check`

## Testing Strategy

### Contract tests (no API key needed)
Use `LocalEmbedder` (ONNX, 384 dims) for all contract tests. These verify
behavioral invariants with real vector search — not the BM25 degradation path.

### LLM round-trip tests (needs API key)
Use `Embedder` (OpenAI, 1536 dims) for production-path testing. Same 5
scenarios as the eval redesign, but now exercising real vector retrieval.

### Integration tests (needs API key)
New tests verifying:
- Vector search returns semantically similar events (not just keyword matches)
- RRF fusion ranks hybrid matches above keyword-only or vector-only
- Reindex preserves all events and embeddings
- Migration produces correct data from old format

## Expected Results

| Metric | Before | After |
|--------|--------|-------|
| Memory module lines | ~11,241 | ~8,000 (-29%) |
| External dependencies | mem0, Qdrant | sqlite-vec (bundled in wheel) |
| Storage files | events.jsonl + profile.json + Qdrant + history.db + MEMORY.md | memory.db + MEMORY.md |
| Write failures | 272 (60% failure rate) | 0 (SQLite ACID) |
| Vector search latency | ~50ms (mem0 overhead) | ~5-7ms (sqlite-vec) |
| Retrieval paths | 2 (mem0 vs BM25) | 1 (vector + FTS5 fused) |
| LLM calls per consolidation | 2 | 1 |
| Production path test coverage | 0% | Full (contract + integration) |

## Dependencies

### New Python packages
- `sqlite-vec` (v0.1.7+) — bundled C extension, no external process
- ONNX Runtime already a dependency (used by cross-encoder reranker)

### SQLite version
System SQLite is 3.37.2. sqlite-vec works on this version (verified). FTS5
is available (verified). No SQLite upgrade required.

### API keys
- `OPENAI_API_KEY` — required for production embeddings and LLM round-trip tests
- No key needed for contract tests (local ONNX embedder)

## Out of Scope

- Multi-user memory isolation (future work if needed)
- Approximate nearest neighbor indexing (brute-force is fast enough at <1000 events)
- LLM-as-judge evaluation
- Knowledge graph reimplementation (deleted, can be reintroduced later if needed)
- Performance benchmarking beyond basic latency verification
