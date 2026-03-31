# Typed Data Flow at Memory Subsystem Boundaries

> Design spec for Phase 5 of the memory architecture improvement.
> Date: 2026-03-30. Status: Approved.

## Problem

The memory subsystem passes `dict[str, Any]` at every internal boundary:
- Retrieval pipeline: items flow as dicts with 25+ keys accumulated across 4 stages
- Event ingestion: `MemoryEvent` Pydantic model exists but is never used in production
- Profile conflicts: structure is implicit — no type, no validation, no mypy coverage

This means mypy cannot check field access, missing keys fail silently at runtime,
and every new contributor (human or LLM) must read source code to know which keys
exist on a dict at any given pipeline stage.

## Design Principles

1. **Type safety is the goal, not immutability** — use `@dataclass(slots=True)` for
   pipeline objects that are built incrementally. Use `frozen=True` only for objects
   that are truly immutable after creation.
2. **Typed at boundaries, dicts at persistence** — the EventStore layer continues to
   work with dicts (SQLite rows). Conversion to typed objects happens at the boundary
   where data enters the subsystem logic.
3. **Use existing models** — `MemoryEvent` and `BeliefRecord` already exist. Use them
   instead of creating duplicates.

## Boundary 1: Retrieval Pipeline

### Current

`MemoryRetriever.retrieve()` returns `list[dict[str, Any]]`. The scorer mutates
each dict in-place, adding `score`, `retrieval_reason`, `memory_type`, etc.
ContextAssembler reads these keys without any compile-time checking.

### Proposed

Two new dataclasses in `nanobot/memory/read/retrieval_types.py`:

```python
@dataclass(slots=True)
class RetrievalScores:
    """Scoring signals accumulated during the retrieval pipeline."""
    rrf_score: float = 0.0
    final_score: float = 0.0
    recency: float = 0.0
    type_boost: float = 0.0
    stability_boost: float = 0.0
    reflection_penalty: float = 0.0
    profile_adjustment: float = 0.0
    profile_adjustment_reasons: list[str] = field(default_factory=list)
    intent: str = ""
    semantic: float = 0.0
    provider: str = "vector"
    # Optional reranker scores
    ce_score: float | None = None
    blended_score: float | None = None
    reranker_alpha: float | None = None

@dataclass(slots=True)
class RetrievedMemory:
    """A memory item flowing through the retrieval pipeline."""
    # From database (always present)
    id: str
    type: str
    summary: str
    timestamp: str
    source: str = ""
    status: str = "active"
    created_at: str = ""
    # From metadata unpacking
    memory_type: str = "episodic"
    topic: str = ""
    stability: str = "medium"
    entities: list[str] = field(default_factory=list)
    triples: list[dict[str, Any]] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    confidence: float = 0.7
    superseded_by_event_id: str = ""
    # Computed during pipeline
    scores: RetrievalScores = field(default_factory=RetrievalScores)
    # Raw metadata for pass-through (keys not explicitly modeled)
    raw_metadata: dict[str, Any] = field(default_factory=dict)
```

### Conversion Boundary

In `MemoryRetriever._enrich_item_metadata()`: after parsing metadata JSON and
unpacking `_extra`, construct a `RetrievedMemory` from the dict. Everything
downstream receives typed objects.

### Impact

- `RetrievalScorer.filter_items()` and `score_items()`: change `list[dict]` →
  `list[RetrievedMemory]`. Replace `item["score"]` with `item.scores.final_score`,
  `item.get("retrieval_reason", {})` with `item.scores`, etc.
- `ContextAssembler.build()`: change item access to typed attributes.
- `GraphAugmenter.build_graph_context_lines()`: change entity/triple access.
- `CompositeReranker.rerank()` and `OnnxCrossEncoderReranker.rerank()`: change
  score access patterns.

## Boundary 2: Event Ingestion

### Current

`EventIngester.append_events()` accepts `list[dict[str, Any]]`. The `MemoryEvent`
Pydantic model exists with `from_dict()` and `to_dict()` but is only used in tests.

### Proposed

Make `MemoryEvent` the contract type at the ingestion boundary:

1. `EventIngester.append_events()` accepts `list[MemoryEvent]` instead of `list[dict]`.
2. Callers convert at the boundary: `MemoryEvent.from_dict(raw_dict)` in
   `ConsolidationPipeline` and `MicroExtractor` after coercion.
3. Internally, the ingester can call `event.to_dict()` when it needs dict access
   for dedup/merge operations and `EventStore.insert_event()`.

### Why not refactor dedup/merge to work with MemoryEvent?

The dedup/merge code does heavy dict mutation (union entities, average confidence,
track merge counts). Refactoring all of this to work with MemoryEvent objects would
be a large behavioral change with high risk. The pragmatic approach: validate at the
boundary (accept MemoryEvent), convert to dict internally for mutation, then persist.

### Impact

- `EventIngester.append_events()`: signature change
- `ConsolidationPipeline`: add `MemoryEvent.from_dict()` calls after extraction
- `MicroExtractor`: same
- `EventCoercer.coerce_event()`: return `MemoryEvent` instead of `dict | None`
- Tests that call `append_events()` with raw dicts: update to use `MemoryEvent`

## Boundary 3: Profile Conflict Records

### Current

Profile conflicts are `list[dict[str, Any]]` with 15+ implicit keys. No type,
no validation, no documentation other than what grep reveals.

### Proposed

New dataclass in `nanobot/memory/persistence/conflict_types.py`:

```python
@dataclass(slots=True)
class ConflictRecord:
    """A detected contradiction between two profile beliefs."""
    timestamp: str
    field: str
    old: str
    new: str
    status: str = "open"  # open | needs_user | resolved
    # Belief tracking
    belief_id_old: str = ""
    belief_id_new: str = ""
    old_memory_id: str = ""
    new_memory_id: str = ""
    # Confidence at detection time
    old_confidence: float = 0.65
    new_confidence: float = 0.65
    old_last_seen_at: str = ""
    new_last_seen_at: str = ""
    # Resolution
    resolution: str = ""  # keep_old | keep_new | dismiss
    resolved_at: str = ""
    source: str = "consolidation"
    # User interaction
    asked_at: str = ""
    # Runtime (not persisted)
    index: int = -1
```

### Conversion Boundary

- `ConflictManager._apply_profile_updates()`: creates `ConflictRecord` instead of
  raw dict when detecting conflicts. Stores as `conflict.to_dict()` in the profile
  (profile dict stays as-is for persistence compatibility).
- `ConflictManager.list_conflicts()`: converts stored dicts to `ConflictRecord`
  objects before returning.
- Consumers (`ask_user_for_conflict`, `resolve_conflict_details`, `RetrievalScorer`)
  receive typed `ConflictRecord` objects.

### Why not type the full profile dict?

The profile dict has 30+ in-place mutation sites across 6 files. Typing it as a
dataclass would require refactoring every mutation site — a massive change with
high risk and low incremental value over typing just the conflict sub-structure
(which is the implicit, undocumented part). Profile section lists (`list[str]`)
and the meta dict structure are already well-understood through `BeliefRecord`
and `PROFILE_KEYS`.

## What's NOT in Scope

- **EventStore return types** — stays `list[dict]` (SQLite row conversion). Typed
  objects are constructed by consumers, not by the store.
- **Profile dict top-level structure** — stays `dict[str, Any]`. Too many mutation
  sites for safe conversion.
- **GraphStore return types** — stays `list[dict]`. Only consumed by KnowledgeGraph
  which already has its own `Entity` typed model.

## Deviations

- **Scorer, reranker, and graph augmenter remain dict-based internally.** Conversion to
  `RetrievedMemory` happens at the retriever's output boundary only (step 9 of
  `_retrieve_unified`). This was a pragmatic choice — the scorer does heavy in-place dict
  mutation (`item["score"] = ...`, `reason["recency"] = ...`) and converting all mutation
  sites would be high-risk for low incremental value. The typed boundary at `retrieve()`
  output is sufficient for compile-time safety at consumer boundaries.
- **`ingester.read_events()` still returns `list[dict]`.** Only `append_events()` was
  tightened to `Sequence[MemoryEvent]`. The read path returns raw SQLite rows with
  metadata unpacking — converting these to `MemoryEvent` would require handling the
  `_extra` roundtrip differently.
- **`append_events()` was originally dual-typed** (`Sequence[MemoryEvent | dict[str, Any]]`)
  to support legacy callers. All production callers now pass `MemoryEvent`, so the dict
  union was removed in a follow-up code review fix.

## Testing Strategy

- Contract tests verify that `RetrievedMemory` fields match what the scorer actually
  sets and what the assembler actually reads.
- Existing tests updated to use typed objects at boundaries.
- mypy catches any field access errors at compile time — that's the primary value.
