# Store Refinement: Consolidation Extraction, Retriever Unification, Module Independence

**Date:** 2026-03-22
**Status:** Draft
**Scope:** Four structural refinements to the memory subsystem, completing
the work deferred in the store decomposition spec (2026-03-21).

## Problem

The store decomposition reduced `store.py` from 3028 to 597 lines, but left
four items unfinished:

1. **Consolidation pipeline** (221 lines, 37% of remaining store.py) still
   lives in the facade — it's business logic, not coordination
2. **`_retrieve_core`** (419 lines) is the single largest method in the
   codebase with entangled filtering/scoring/reranking, and the BM25 and
   mem0 paths duplicate scoring logic
3. **`_store` back-references** in `profile.py` and `conflicts.py` create
   circular dependencies and block independent testing
4. **`eval.py`** duplicates helpers instead of importing from `helpers.py`

## Scope

### 1. Extract `ConsolidationPipeline` from `store.py`

Move `consolidate()` + 5 helper methods into a new
`nanobot/agent/memory/consolidation_pipeline.py` module.

**New class:** `ConsolidationPipeline`

Constructor dependencies:
- `persistence: MemoryPersistence`
- `extractor: MemoryExtractor`
- `ingester: EventIngester`
- `profile_mgr: ProfileManager`
- `conflict_mgr: ConflictManager`
- `snapshot: MemorySnapshot`
- `mem0: _Mem0Adapter`
- `mem0_raw_turn_ingestion: bool`

Methods to move from `store.py`:
- `consolidate` (158 lines) — the main async pipeline
- `_select_messages_for_consolidation` (27 lines)
- `_format_conversation_lines` (11 lines, static)
- `_build_consolidation_prompt` (9 lines, static)
- `_apply_save_memory_tool_result` (7 lines)
- `_finalize_consolidation` (9 lines)

**Shared helpers:** `_extract_pinned_section` and `_restore_pinned_section`
(~28 lines) are used by both consolidation and `MemorySnapshot`. Move them
to `snapshot.py` as public classmethods. `ConsolidationPipeline` imports from
there. Currently `MemorySnapshot` receives these via callable injection in
its `__init__` — after moving the methods onto the class, remove the
injection parameters and update `MemoryStore.__init__` wiring accordingly.

**Store.py after:** `consolidate()` becomes a one-line delegation to
`self._consolidation.consolidate(...)`. The `agent/consolidation.py`
orchestrator is unchanged.

**Expected result:** `store.py` drops from 597 to ~376 lines — pure facade
with no business logic.

### 2. Unify Retriever Pipeline (Pipes and Filters)

Restructure `retriever.py` internals. Delete `_retrieve_core` (419 lines),
replace with a shared pipeline that both BM25 and mem0 paths feed into.

**Pipeline stages:**

```
Source (BM25 or mem0) → Graph Augment → Filter → Score → Rerank → Truncate
```

**New methods on `MemoryRetriever`:**

| Method | Lines (est.) | Responsibility |
|--------|-------------|---------------|
| `_source_from_bm25(query, plan, top_k)` | ~60 | Local BM25 candidate sourcing |
| `_source_from_mem0(query, plan, candidate_k)` | ~50 | mem0 vector search + unpack |
| `_augment_query_with_graph(query)` | ~30 | Graph entity expansion |
| `_filter_items(items, plan, reflection_enabled)` | ~80 | Intent-based filtering |
| `_score_items(items, plan, profile_data, graph_entities)` | ~80 | Unified scoring formula |
| `_rerank_items(query, items)` | ~30 | Cross-encoder reranking |
| `_build_result_stats(items, source_stats)` | ~20 | Count tabulation |
| `_load_profile_scoring_data()` | ~30 | Profile + conflict adjustments |
| `_inject_rollout_status(items, plan)` | ~30 | Synthetic rollout record |

**`retrieve()` becomes a dispatcher:**
1. Determine source (BM25 vs mem0) based on rollout mode
2. Call source method to get candidates
3. Feed through shared pipeline: filter → score → rerank → truncate
4. Shadow mode comparison (if enabled) wraps the pipeline call

**Key unification:** The BM25 path (currently ~109 lines inline in
`retrieve()`) and the mem0 path (currently `_retrieve_core`) share no
scoring code despite near-identical formulas. After unification, both use
`_score_items` — one scoring formula, one set of tests.

**Expected result:** `retriever.py` stays ~790 lines total but no single
method exceeds ~100 lines. `_retrieve_core` is deleted.

### 3. Eliminate `_store` Back-References

#### `conflicts.py` — 3 callables

`ConflictManager._store` is used in `resolve_conflict()` for three ingester
methods. Fix: inject as callables in `__init__`:

```python
def __init__(
    self,
    profile_mgr: ProfileManager,
    mem0: _Mem0Adapter,
    *,
    sanitize_mem0_text_fn: Callable[[str], str] | None = None,
    normalize_metadata_fn: Callable[[dict], dict] | None = None,
    sanitize_metadata_fn: Callable[[dict], dict] | None = None,
) -> None:
```

`MemoryStore.__init__` wires `self.ingester._sanitize_mem0_text` etc.
Remove `self.conflict_mgr._store = self`.

#### `profile.py` — 10 accesses across 4 subsystems

`ProfileManager._store` is used in `apply_live_user_correction()` for
10 distinct `store.` accesses:

- `store.extractor.extract_explicit_preference_corrections(...)`
- `store.extractor.extract_explicit_fact_corrections(...)`
- `store.ingester._coerce_event(...)`
- `store.ingester.append_events(...)`
- `store.ingester._normalize_memory_metadata(...)`
- `store.ingester._sanitize_mem0_text(...)`
- `store.ingester._sanitize_mem0_metadata(...)`
- `store.conflict_mgr.auto_resolve_conflicts(...)`
- `store.conflict_mgr.ask_user_for_conflict(...)`
- `store.snapshot.rebuild_memory_snapshot(...)`

Fix: inject the 4 subsystem objects directly rather than 10 individual
callables — this is cleaner than wrapping each method:

```python
def __init__(
    self,
    persistence: MemoryPersistence,
    profile_file: Path,
    mem0: _Mem0Adapter,
    *,
    extractor: MemoryExtractor | None = None,
    ingester: EventIngester | None = None,
    conflict_mgr: ConflictManager | None = None,
    snapshot: MemorySnapshot | None = None,
) -> None:
```

`MemoryStore.__init__` wires these after all subsystems are constructed.
Remove `self.profile_mgr._store = self`. The `apply_live_user_correction`
method calls `self._extractor.extract_explicit_preference_corrections(...)`
etc. instead of `store.extractor...`.

**Result:** Zero modules in `nanobot/agent/memory/` have a `_store`
back-reference. Every module is independently constructible and testable.

### 4. Fix `eval.py` Helper Duplication

Replace duplicated `_utc_now_iso` and `_safe_float` in `eval.py` with
imports from `helpers.py`.

## Execution Order

1. **Move pinned-section helpers to `snapshot.py`** — prerequisite for
   consolidation extraction
2. **Extract `ConsolidationPipeline`** — largest change, clears store.py
3. **Restructure `retriever.py`** — break up `_retrieve_core`, unify
   scoring pipeline
4. **Eliminate `_store` from `conflicts.py`** — simple, 3 callables
5. **Eliminate `_store` from `profile.py`** — harder, 5 callables
6. **Fix `eval.py` helpers** — trivial cleanup
7. **Migrate tests + final validation**

### Why this order

- Pinned helpers move first because consolidation needs them in snapshot.py
- Consolidation extraction before retriever because it clears store.py of
  business logic, making the facade final
- `_store` removal after extractions because the callable wiring in
  `MemoryStore.__init__` depends on all subsystems being constructed
- `eval.py` last because it's trivial and independent

## Testing Strategy

### New tests

| File | Tests for |
|------|-----------|
| `test_consolidation_pipeline.py` | Pipeline stages, LLM tool-call parsing, pinned section handling |
| Extended `test_retriever.py` | Each pipeline stage independently: `_filter_items`, `_score_items`, `_rerank_items`, scoring unification |

### Existing test updates

- Tests that call `store.consolidate(...)` continue to work (facade delegates)
- Tests that patch `store._retrieve_core` must be updated (method deleted)
- Tests that use `conflict_mgr._store` or `profile_mgr._store` must be updated

## Expected Results

| File | Before | After |
|------|--------|-------|
| `store.py` | 597 lines | ~376 lines |
| `consolidation_pipeline.py` | new | ~250 lines |
| `retriever.py` | 791 lines | ~790 lines (same size, better structure) |
| `snapshot.py` | 168 lines | ~196 lines (+pinned helpers) |
| `conflicts.py` | 462 lines | ~460 lines (-`_store`, +callable params) |
| `profile.py` | 978 lines | ~970 lines (-`_store`, +callable params) |
| `eval.py` | 415 lines | ~410 lines (-duplicated helpers) |

## Out of Scope

- Splitting `profile.py` (978 lines) into sub-modules — it's large but
  cohesive; splitting needs a clear seam that doesn't exist yet
- Performance optimization (profile.json caching, graph dedup) — separate
  concern, lower urgency
- Changes to `agent/consolidation.py` orchestrator — it stays as the
  locking wrapper
- Refactoring `context_assembler.py` internals
