# Memory Internal Decomposition — Design Spec

**Date:** 2026-03-25
**Status:** Approved
**Problem:** Architecture review Problem 11 — `write/ingester.py` (918 LOC) and
`read/retriever.py` (821 LOC) exceed the 500 LOC hard limit, each handling multiple
concerns internally.

## Context

The memory subsystem's directory structure (`write/`, `read/`, `ranking/`, `persistence/`,
`graph/`) was established in PR #49. The two oversized files are the last open item from
the March 2026 architecture review. Both files contain well-documented pipeline stages
with clean internal seams — the decomposition splits along those natural boundaries.

## Approach

Split by pipeline stage. `store.py` acts as the internal composition root for the memory
subsystem — it constructs all new components and injects them into the orchestrators.
The orchestrators (`EventIngester`, `MemoryRetriever`) become thin coordinators that
receive pre-built collaborators, constructing nothing themselves.

## Write Path Decomposition

### Current: `write/ingester.py` (918 LOC)

Single `EventIngester` class handling event coercion, classification, dedup/merge,
persistence writes, graph ingestion, and legacy mem0 sync.

### After: 4 modules

#### `write/classification.py` (~150 LOC) — `EventClassifier`

Stateless classifier. No constructor dependencies.

**Methods (moved from `EventIngester`):**
- `classify_memory_type(event_type, summary, source)` → `(memory_type, stability, is_mixed)`
- `normalize_memory_metadata(metadata, event_type, summary, source)` → `(dict, is_mixed)`
- `default_topic_for_event_type(event_type)` → `str` (static)
- `distill_semantic_summary(summary)` → `str` (static)

**Constants owned:** `EVENT_TYPES`, `MEMORY_TYPES`, `MEMORY_STABILITY`.

#### `write/coercion.py` (~200 LOC) — `EventCoercer`

Normalizes raw event dicts into canonical form.

**Constructor:** `EventCoercer(classifier: EventClassifier)`

**Methods (moved from `EventIngester`):**
- `build_event_id(event_type, summary, timestamp)` → `str` (static)
- `infer_episodic_status(event_type, summary, raw_status)` → `str | None`
- `coerce_event(raw, source_span, channel, chat_id)` → `dict | None`
- `ensure_event_provenance(event)` → `dict`

**Constants owned:** `EPISODIC_STATUS_OPEN`, `EPISODIC_STATUS_RESOLVED`.

#### `write/dedup.py` (~220 LOC) — `EventDeduplicator`

Semantic dedup, supersession detection, and event merging.

**Constructor:** `EventDeduplicator(coercer: EventCoercer, conflict_pair_fn: Callable | None)`

**Methods (moved from `EventIngester`):**
- `event_similarity(left, right)` → `(float, float)` (static)
- `find_semantic_duplicate(candidate, existing)` → `(int | None, float)`
- `find_semantic_supersession(candidate, existing)` → `int | None`
- `merge_events(base, incoming, similarity)` → `dict`
- `merge_source_span(base, incoming)` → `list[int]` (static)

#### `write/ingester.py` (~150 LOC) — slim `EventIngester`

Thin orchestrator: coerce → dedup → persist → graph ingest.

**Constructor (changed — receives pre-built collaborators):**
```python
EventIngester(
    *,
    coercer: EventCoercer,
    dedup: EventDeduplicator,
    graph: KnowledgeGraph | None,
    rollout_fn: Callable[[], dict[str, Any]],
    db: UnifiedMemoryDB | None = None,
    embedder: Embedder | None = None,
)
```

**Methods retained:**
- `append_events(events)` → `int` — main entry point, uses `self._dedup` and
  `self._coercer` instead of calling methods directly
- `read_events(limit)` → `list[dict]` — DB read with metadata unpacking
- `_ingest_graph_triples(events)` → `int` — async graph ingestion

**Dead code removed:**
- `_sync_events_to_mem0()` — no-op stub (returns 0)
- `_event_mem0_write_plan()` — no production callers (only tests)
- `_sanitize_mem0_text()`, `_sanitize_mem0_metadata()`, `_looks_blob_like_summary()` —
  removed entirely (all call sites are dead code being removed in this change)

## Read Path Decomposition

### Current: `read/retriever.py` (821 LOC)

Single `MemoryRetriever` class handling RRF fusion, graph augmentation, filtering,
scoring, reranking, entity collection, and graph context building.

### After: 3 modules

#### `read/scoring.py` (~300 LOC) — `RetrievalScorer`

Owns the filter → score → rerank stages.

**Constructor:**
```python
RetrievalScorer(
    *,
    profile_mgr: ProfileManager,
    reranker: Reranker,
    rollout_fn: Callable[[], dict[str, Any]],
)
```

**Methods (moved from `MemoryRetriever`):**
- `filter_items(items, plan)` → `(list, dict)` — intent-based routing filters
- `score_items(items, plan, profile_data, graph_entities, ...)` → `list` — unified scoring
- `load_profile_scoring_data()` → `dict` — profile + resolved-conflict data
- `rerank_items(query, items)` → `list` — cross-encoder (enabled/shadow/disabled)

**Constants moved here:** `PROFILE_KEYS`, `PROFILE_STATUS_STALE`, `PROFILE_STATUS_CONFLICTED`,
`_STABILITY_BOOST`, `_FIELD_BY_EVENT_TYPE`.

**Helper moved here:** `_contains_norm_phrase()` (module-level function).

#### `read/graph_augmentation.py` (~200 LOC) — `GraphAugmenter`

Owns all graph-related retrieval operations.

**Constructor:**
```python
GraphAugmenter(
    *,
    graph: KnowledgeGraph | None,
    extractor: MemoryExtractor | None = None,
    read_events_fn: Callable[..., list[dict[str, Any]]],
)
```

**Methods (moved from `MemoryRetriever`):**
- `collect_graph_entity_names(query, events)` → `set[str]`
- `build_entity_index(events)` → `set[str]`
- `extract_query_entities(query, entity_index)` → `set[str]`
- `build_graph_context_lines(query, retrieved, max_tokens)` → `list[str]`

**State owned:** `_graph_cache: dict[frozenset[str], set[str]]` — per-request cache,
reset by `MemoryRetriever.retrieve()` calling a `reset_cache()` method.

#### `read/retriever.py` (~200 LOC) — slim `MemoryRetriever`

Thin orchestrator: embed → dual source → RRF fuse → delegate to scorer/augmenter.

**Constructor (changed — receives pre-built collaborators):**
```python
MemoryRetriever(
    *,
    scorer: RetrievalScorer,
    graph_aug: GraphAugmenter,
    planner: RetrievalPlanner,
    db: UnifiedMemoryDB | None = None,
    embedder: Embedder | None = None,
)
```

**Methods retained:**
- `retrieve(query, top_k, ...)` → `list[dict]` — public entry point
- `_retrieve_unified(query, top_k, ...)` → `list[dict]` — pipeline orchestration
- `_fuse_results(vec_results, fts_results, ...)` → `list[dict]` (static) — RRF fusion
- `_enrich_item_metadata(items)` → `None` — metadata promotion

## Dead Code & Sanitization Cleanup

### Dead code removed

| Item | Location | Reason |
|------|----------|--------|
| `_sync_events_to_mem0()` | `write/ingester.py` | No-op stub returning 0 |
| `_event_mem0_write_plan()` | `write/ingester.py` | No production callers (only tests) |
| `_augment_query_with_graph()` | `read/retriever.py` | Never called in production code (only tests) |
| `sanitize_mem0_text_fn` param | `ConflictManager.__init__` | Stored but never called |
| `normalize_metadata_fn` param | `ConflictManager.__init__` | Stored but never called |
| `sanitize_metadata_fn` param | `ConflictManager.__init__` | Stored but never called |
| Entire mem0 block (lines 248-299) | `consolidation_pipeline.py` | Guarded by `self._mem0 is not None`; `_mem0` is always `None` |
| `mem0` constructor param | `ConsolidationPipeline.__init__` | Never passed by `store.py` |
| `mem0_raw_turn_ingestion` param | `ConsolidationPipeline.__init__` | Never passed by `store.py` |
| `persistence` constructor param | `ConsolidationPipeline.__init__` | Never passed by `store.py` |
| `_sanitize_mem0_text()` | `write/ingester.py` | All callers removed (dead mem0 block) |
| `_sanitize_mem0_metadata()` | `write/ingester.py` | All callers removed (dead mem0 block) |
| `_looks_blob_like_summary()` | `write/ingester.py` | Only called by `_sanitize_mem0_text` |

**Note:** Removing the 3 dead `ConflictManager` params preserves `resolve_gap_fn` and
`db` which are actively used.

## Wiring Changes in `store.py`

`store.py` acts as the internal composition root. All new components are constructed
there and injected into orchestrators.

### Construction order

All components stored on `self` so they're accessible for lazy lambda callbacks
(e.g. the assembler's `build_graph_context_lines_fn`).

```python
self._classifier = EventClassifier()                           # no deps
self._coercer = EventCoercer(self._classifier)                 # needs classifier
self.extractor = MemoryExtractor(
    coerce_event=lambda raw, **kw: self._coercer.coerce_event(raw, **kw),
    ...
)
self._dedup = EventDeduplicator(
    coercer=self._coercer,
    conflict_pair_fn=lambda old, new: self.profile_mgr._conflict_pair(old, new),
)
self.ingester = EventIngester(
    coercer=self._coercer, dedup=self._dedup, graph=self.graph, ...
)
self._scorer = RetrievalScorer(
    profile_mgr=self.profile_mgr, reranker=self._reranker, rollout_fn=...
)
self._graph_aug = GraphAugmenter(
    graph=self.graph, extractor=self.extractor,
    read_events_fn=self.ingester.read_events,
)
self.retriever = MemoryRetriever(
    scorer=self._scorer, graph_aug=self._graph_aug, planner=self._planner, ...
)
```

`conflict_pair_fn` is passed directly to `EventDeduplicator` by `store.py` — it does
not route through the slim `EventIngester`.

### Callback updates

| Caller | Old | New |
|--------|-----|-----|
| `store.py` extractor wiring | `lambda: self.ingester._coerce_event(...)` | `lambda: self._coercer.coerce_event(...)` |
| `store.py` ConflictManager | 3 `_fn` params | Removed (dead) |
| `store.py` assembler | `self.retriever._build_graph_context_lines` | `self._graph_aug.build_graph_context_lines` |
| `store.py` `_ensure_assembler` | `self.retriever._build_graph_context_lines` | `self._graph_aug.build_graph_context_lines` |

**`consolidation_pipeline.py` — entire mem0 block removed:**

The block at lines 248-299 is guarded by `if self._mem0 is not None`. Since `store.py`
never passes `mem0=` to the pipeline constructor, `self._mem0` is always `None` — the
entire block is dead code. This eliminates all calls to `_sync_events_to_mem0`,
`_normalize_memory_metadata`, `_sanitize_mem0_text`, and `_sanitize_mem0_metadata` from
the pipeline. The `mem0`, `mem0_raw_turn_ingestion`, and `persistence` constructor
parameters are also removed.

The `EventIngester` import in `consolidation_pipeline.py` (line 29, used only for
`EventIngester._sanitize_mem0_metadata`) is removed.

## Test Updates

- Remove tests for dead code: `_sync_events_to_mem0`, `_event_mem0_write_plan`,
  `_sanitize_mem0_text`, `_sanitize_mem0_metadata`, `_looks_blob_like_summary`,
  `_augment_query_with_graph`, `_event_mem0_write_plan`
- Remove dead `_fn` params from `test_conflict_manager_methods.py` fixtures
- Add unit tests for each new class (`EventClassifier`, `EventCoercer`,
  `EventDeduplicator`, `RetrievalScorer`, `GraphAugmenter`) — each testable
  independently since dependencies are injected
- Existing integration tests continue to work through `MemoryStore` facade

## Structural Impact

| Metric | Before | After | Limit |
|--------|--------|-------|-------|
| `write/` file count (excl. `__init__.py`) | 3 | 6 | 15 |
| `read/` file count (excl. `__init__.py`) | 3 | 5 | 15 |
| Largest file (write) | 918 | ~220 | 500 |
| Largest file (read) | 821 | ~300 | 500 |
| `memory/__init__.py` exports | 8 | 8 (unchanged) | 12 |
| Total memory LOC | ~10,035 | ~9,800 (dead code removed) | advisory 5k |

No file exceeds 500 LOC after the split. All structural limits respected.
