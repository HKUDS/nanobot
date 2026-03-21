# MemoryStore Decomposition: Extract-and-Facade

**Date:** 2026-03-21
**Status:** Draft
**Scope:** Decompose `nanobot/agent/memory/store.py` (3028 lines) into 6 focused
modules, remove 48 thin wrappers, leave `MemoryStore` as a thin facade.

## Problem

`MemoryStore` is 3028 lines — the largest file in the codebase. Despite prior
extractions (ProfileManager, ConflictManager, RetrievalPlanner, ContextAssembler,
EvalRunner), it still owns 6 distinct responsibility clusters plus 48 thin
wrapper methods (~348 lines) that purely delegate to already-extracted modules.

This makes the file hard to navigate, review, and test in isolation. Each
cluster has high internal cohesion but low coupling to other clusters — classic
extraction candidates.

## Approach: Extract-and-Facade

Extract each cluster into its own module with a clean interface. `MemoryStore`
becomes a thin **facade** that composes the extracted modules and delegates all
calls. Thin wrappers are removed — callers migrate to subsystem objects accessed
via `store.retriever`, `store.ingester`, etc.

Consolidation (~286 lines) stays in `store.py` because it cross-cuts all
subsystems (ingestion, profile, snapshot, mem0 sync, LLM). Extracting it
cleanly requires the other extractions to land first — future work.

## New Modules

### `helpers.py` — Shared Utility Functions (~150 lines)

Static helpers currently duplicated across `store.py`, `profile.py`,
`conflicts.py`, and `context_assembler.py`:

- `_utc_now_iso()` — UTC timestamp
- `_safe_float(v)` — safe float coercion
- `_norm_text(s)` — text normalization
- `_tokenize(s)` — token extraction
- `_extract_query_keywords(text)` — graph query keyword extraction
- `_to_str_list(v)` — safe list coercion
- `_to_datetime(v)` — datetime parsing
- `_estimate_tokens(text)` — token estimation
- `_contains_any(text, terms)` — substring check
- `_GRAPH_QUERY_STOPWORDS` — stopword set

Extracted once, imported everywhere. Eliminates duplication.

### `rollout.py` — `RolloutConfig` (~170 lines)

Feature flag management for the memory subsystem. Fully self-contained — no
dependencies on other clusters.

```python
class RolloutConfig:
    ROLLOUT_MODES: ClassVar[set[str]]

    def __init__(self, overrides: dict[str, Any], mem0_enabled: bool) -> None
    def load(self) -> dict[str, Any]
    def apply_overrides(self, overrides: dict[str, Any]) -> None
    def get_status(self) -> dict[str, Any]

    @property
    def rollout(self) -> dict[str, Any]
```

### `ingester.py` — `EventIngester` (~750 lines)

The complete write path for memory events.

```python
class EventIngester:
    def __init__(
        self,
        persistence: MemoryPersistence,
        mem0: Mem0Adapter | None,
        graph: KnowledgeGraph | None,
        rollout: RolloutConfig,
    ) -> None

    # Public API
    def append_events(self, events: list[dict]) -> list[dict]
    def read_events(self) -> list[dict]
    def sync_events_to_mem0(self, events: list[dict]) -> None

    # Internal pipeline
    def _coerce_event(self, raw: dict) -> dict
    def _build_event_id(self, event: dict) -> str
    def _infer_episodic_status(self, event: dict) -> str
    def _ensure_event_provenance(self, event: dict, existing: list[dict]) -> dict
    def _classify_memory_type(self, event: dict) -> str
    def _normalize_memory_metadata(self, event: dict) -> dict
    def _event_mem0_write_plan(self, event: dict) -> list[dict]
    def _sanitize_mem0_text(self, text: str) -> str
    def _sanitize_mem0_metadata(self, meta: dict) -> dict
    def _distill_semantic_summary(self, event: dict) -> str
    def _find_semantic_duplicate(self, event: dict, existing: list[dict]) -> dict | None
    def _find_semantic_supersession(self, event: dict, existing: list[dict]) -> dict | None
    def _merge_events(self, old: dict, new: dict) -> dict
    def _event_similarity(self, a: dict, b: dict) -> float
    async def _ingest_graph_triples(self, events: list[dict]) -> None
```

Dependencies: `persistence`, `mem0` (add_text), `graph` (ingest), `rollout`.

### `retriever.py` — `MemoryRetriever` (~660 lines)

The complete read path for memory retrieval.

```python
class MemoryRetriever:
    def __init__(
        self,
        mem0: Mem0Adapter | None,
        graph: KnowledgeGraph | None,
        planner: RetrievalPlanner,
        reranker: MemoryReranker | None,
        profile_mgr: ProfileManager,
        rollout: RolloutConfig,
        read_events_fn: Callable[[], list[dict]],
        extractor: MemoryExtractor | None = None,
    ) -> None

    # Public API
    def retrieve(self, query: str, top_k: int = 10, ...) -> list[dict]

    # Internal pipeline
    def _retrieve_core(self, query, top_k, ...) -> tuple[list[dict], dict]
    def _build_entity_index(self, entities: list) -> dict
    def _extract_query_entities(self, query: str) -> list[str]
    def _build_graph_context_lines(self, query: str, ...) -> list[str]
```

Dependencies: `mem0` (search), `graph` (entity lookup), `planner` (intent/policy),
`reranker` (cross-encoder), `profile_mgr` (score adjustments for resolved
conflicts/stale items), `rollout`, `read_events_fn` (callable for local fallback),
`extractor` (entity extraction for graph queries).

The `profile_mgr` dependency is for the profile-based score adjustments in
`_retrieve_core` (lines 2097-2267 in current store.py). The `read_events_fn`
callable avoids a circular dependency with `EventIngester`.

**Naming note:** `store.py` currently assigns `self.retriever = _Mem0RuntimeInfo()`
(line 99) — a compatibility stub from `mem0_adapter.py`. This attribute is
never referenced by any caller or test (confirmed by grep). The new
`MemoryRetriever` replaces it on `self.retriever`. The dead `_Mem0RuntimeInfo`
assignment is simply removed during extraction.

### `maintenance.py` — `MemoryMaintenance` (~330 lines)

Mem0 infrastructure operations: reindex, seed, health checks, vector stats.

```python
class MemoryMaintenance:
    def __init__(
        self,
        mem0: Mem0Adapter | None,
        persistence: MemoryPersistence,
        rollout: RolloutConfig,
    ) -> None

    # Public API
    async def ensure_health(self) -> None
    def reindex_from_structured_memory(self, profile: dict, events: list[dict]) -> dict
    def seed_structured_corpus(self, ...) -> None
    def vector_points_count(self) -> int
    def history_row_count(self) -> int
    def backend_stats_for_eval(self) -> dict
    def ensure_vector_health(self) -> None
```

Dependencies: `mem0` (client, delete_all, add_text, flush, reopen), `persistence`
(read/write jsonl), `rollout`.

### `snapshot.py` — `MemorySnapshot` (~110 lines)

Memory snapshot rebuild and verification.

```python
class MemorySnapshot:
    def __init__(
        self,
        profile_mgr: ProfileManager,
        persistence: MemoryPersistence,
        read_events_fn: Callable[[], list[dict]],
        assembler: ContextAssembler,
    ) -> None

    # Public API
    def rebuild(self) -> None
    def verify(self) -> dict
```

Dependencies: `profile_mgr` (read_profile, _meta_section, verify_beliefs),
`persistence` (read/write long-term text), `read_events_fn`, `assembler`
(_profile_section_lines, _recent_unresolved).

## Thin Wrapper Removal

48 wrapper methods (~348 lines) on `MemoryStore` are removed in three phases:

### Phase 1: Remove internal-only wrappers

Wrappers whose callers are moving into the new modules:
- 6 RetrievalPlanner wrappers → callers move into `MemoryRetriever`
- 10 ContextAssembler wrappers → `get_memory_context` becomes a facade method
- 3 Persistence wrappers → callers move into new modules

### Phase 2: Expose subsystems and migrate external callers

Subsystem objects become public attributes on `MemoryStore`:
- `store.profile_mgr` (already exists)
- `store.conflict_mgr` (already exists)
- `store.eval_runner` (rename from `_eval` to public)
- `store.ingester` (new)
- `store.retriever` (new)
- `store.maintenance` (new)
- `store.snapshot` (new)

External callers (loop.py, CLI commands, tests) change from:
- `store.read_profile()` → `store.profile_mgr.read_profile()`
- `store.list_conflicts()` → `store.conflict_mgr.list_conflicts()`
- `store.retrieve(...)` → `store.retriever.retrieve(...)`
- etc.

### Phase 3: Delete wrapper methods

All 48 wrappers removed from `MemoryStore`.

### Backward compatibility during migration

Temporary aliases are added during the transition so existing tests don't break
mid-migration:

```python
# Temporary — remove after test migration
retrieve = property(lambda self: self.retriever.retrieve)
```

These are explicitly marked for removal and deleted in the final cleanup step.

## `MemoryStore` After Decomposition (~550 lines)

```python
class MemoryStore:
    def __init__(self, workspace, mem0, config, ...):
        # Foundation
        self.persistence = MemoryPersistence(workspace)
        self.rollout = RolloutConfig(overrides, mem0_enabled=bool(mem0))

        # Already extracted (unchanged)
        self.profile_mgr = ProfileManager(...)
        self.conflict_mgr = ConflictManager(...)
        self.extractor = MemoryExtractor(...)
        self.eval_runner = EvalRunner(...)

        # New extractions
        self.ingester = EventIngester(self.persistence, mem0, graph, self.rollout)
        self.retriever = MemoryRetriever(
            mem0, graph, planner, reranker,
            self.profile_mgr, self.rollout,
            read_events_fn=self.ingester.read_events,
            extractor=self.extractor,
        )
        self.maintenance = MemoryMaintenance(mem0, self.persistence, self.rollout)
        self.snapshot = MemorySnapshot(
            self.profile_mgr, self.persistence,
            read_events_fn=self.ingester.read_events,
            assembler=self._assembler,
        )

    # Facade methods (coordinate across subsystems)
    async def get_memory_context(self, query, ...) -> str
    async def consolidate(self, provider, session, ...) -> bool

    # Consolidation internals (stay here — cross-cutting)
    def _select_messages_for_consolidation(...)
    def _format_conversation_lines(...)
    def _build_consolidation_prompt(...)
    def _extract_pinned_section(...)
    def _restore_pinned_section(...)
    def _apply_save_memory_tool_result(...)
    def _finalize_consolidation(...)
```

## Shared Helpers: `helpers.py`

Static utilities currently duplicated across multiple memory modules are
consolidated into `nanobot/agent/memory/helpers.py`:

- `_utc_now_iso`, `_safe_float`, `_norm_text`, `_tokenize`
- `_extract_query_keywords`, `_GRAPH_QUERY_STOPWORDS`
- `_to_str_list`, `_to_datetime`, `_estimate_tokens`, `_contains_any`

Existing duplicates in `profile.py`, `conflicts.py`, `context_assembler.py`,
and `store.py` are replaced with imports from `helpers.py`.

## Execution Order

### Phase 1: Foundation
1. Extract `helpers.py` — shared utilities
2. Extract `rollout.py` — `RolloutConfig`

### Phase 2: Core extractions
3. Extract `ingester.py` — `EventIngester` (largest, ~745 lines)
4. Extract `retriever.py` — `MemoryRetriever` (~660 lines)
5. Extract `maintenance.py` — `MemoryMaintenance` (~324 lines)
6. Extract `snapshot.py` — `MemorySnapshot` (~103 lines)

### Phase 3: Cleanup
7. Remove thin wrappers — migrate callers, delete ~348 lines
8. Migrate existing tests — update to new API
9. Final validation — `make check`, update exports

### Why this order
- `helpers.py` first — every subsequent extraction imports from it
- `rollout.py` second — every subsequent extraction takes it as a dependency
- `ingester.py` before `retriever.py` — retriever depends on `ingester.read_events`
- Wrapper removal last — riskiest part, benefits from stable extractions

## Testing Strategy

### New unit tests (one per extracted module)

| Test file | Tests for |
|-----------|-----------|
| `test_rollout_config.py` | Load, overrides, status, validation |
| `test_ingester.py` | Coerce, classify, dedup, merge, append, mem0 sync |
| `test_retriever.py` | Retrieve, retrieve_core, scoring, graph context |
| `test_maintenance.py` | Reindex, seed, health, vector stats |
| `test_snapshot.py` | Rebuild, verify |
| `test_memory_helpers.py` | Shared utility functions |

### Existing test migration

Existing test files (`test_store_branches.py`, `test_store_helpers.py`,
`test_memory_hybrid.py`, `test_memory_metadata_policy.py`,
`test_memory_consolidation_types.py`) are updated to use the new API:

- `store.append_events(...)` → `store.ingester.append_events(...)`
- `store.retrieve(...)` → `store.retriever.retrieve(...)`
- `store.reindex_from_structured_memory(...)` → `store.maintenance.reindex_from_structured_memory(...)`
- `store.read_profile()` → `store.profile_mgr.read_profile()`
- etc.

Existing tests serve as integration tests (verify `MemoryStore` wires
everything correctly). New unit tests verify each subsystem in isolation.

### Risk mitigation

1. Extract modules with new unit tests first (passing before touching existing tests)
2. Add temporary backward-compat aliases during migration
3. Migrate existing tests one file at a time
4. Remove aliases after all tests pass

## Expected Result

| File | Before | After |
|------|--------|-------|
| `store.py` | 3028 lines | ~550 lines |
| `helpers.py` | new | ~150 lines |
| `rollout.py` | new | ~170 lines |
| `ingester.py` | new | ~750 lines |
| `retriever.py` | new | ~660 lines |
| `maintenance.py` | new | ~330 lines |
| `snapshot.py` | new | ~110 lines |

Total memory subsystem lines stay roughly the same (~2720 across files vs
~3028 in one file), but each file has one clear responsibility and can be
understood, tested, and modified independently.

## Out of Scope

- Extracting `consolidate()` from `MemoryStore` (future work — needs stable
  subsystem boundaries first)
- Refactoring the retrieval pipeline internals (only moving, not changing logic)
- Changes to the already-extracted modules (`profile.py`, `conflicts.py`,
  `retrieval_planner.py`, `context_assembler.py`, `extractor.py`, `eval.py`)
- Performance optimization
