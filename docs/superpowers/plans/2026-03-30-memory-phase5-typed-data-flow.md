# Memory Phase 5: Typed Data Flow — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `dict[str, Any]` at three memory subsystem boundaries with typed dataclasses and existing Pydantic models, enabling mypy to catch field access errors at compile time.

**Architecture:** Three independent boundary conversions: (1) retrieval pipeline gets `RetrievedMemory` + `RetrievalScores` dataclasses, (2) event ingestion accepts `MemoryEvent` instead of raw dicts, (3) profile conflicts get a `ConflictRecord` dataclass. Each conversion is self-contained and committable independently.

**Tech Stack:** Python 3.10+, dataclasses (`slots=True`), Pydantic (existing `MemoryEvent`), ruff, mypy, pytest

**Spec:** `docs/superpowers/specs/2026-03-30-typed-data-flow-design.md`

---

## File Structure

### Files to Create

| File | Responsibility |
|------|---------------|
| `nanobot/memory/read/retrieval_types.py` | `RetrievedMemory` + `RetrievalScores` dataclasses |
| `nanobot/memory/persistence/conflict_types.py` | `ConflictRecord` dataclass |

### Files to Modify

**Boundary 1 (Retrieval):**
- `nanobot/memory/read/retriever.py` — return `list[RetrievedMemory]` from `retrieve()`
- `nanobot/memory/read/scoring.py` — accept/return `list[RetrievedMemory]`
- `nanobot/memory/read/context_assembler.py` — consume `RetrievedMemory` attributes
- `nanobot/memory/read/graph_augmentation.py` — consume `RetrievedMemory` attributes
- `nanobot/memory/ranking/reranker.py` — accept `list[RetrievedMemory]`
- `nanobot/memory/ranking/onnx_reranker.py` — accept `list[RetrievedMemory]`

**Boundary 2 (Ingestion):**
- `nanobot/memory/write/ingester.py` — accept `list[MemoryEvent]`
- `nanobot/memory/write/coercion.py` — return `MemoryEvent | None`
- `nanobot/memory/consolidation_pipeline.py` — convert dicts to `MemoryEvent`
- `nanobot/memory/write/micro_extractor.py` — convert dicts to `MemoryEvent`
- `nanobot/memory/persistence/profile_correction.py` — convert dicts to `MemoryEvent`

**Boundary 3 (Conflicts):**
- `nanobot/memory/write/conflicts.py` — create/return `ConflictRecord`
- `nanobot/memory/write/conflict_interaction.py` — consume `ConflictRecord`
- `nanobot/memory/read/scoring.py` — consume `ConflictRecord`

---

## Task 1: Create Retrieval Types + Migrate Retriever

**Files:**
- Create: `nanobot/memory/read/retrieval_types.py`
- Modify: `nanobot/memory/read/retriever.py`
- Test: existing tests + `tests/test_retrieval_types.py`

- [ ] **Step 1: Create `retrieval_types.py` with the two dataclasses**

Create `nanobot/memory/read/retrieval_types.py` containing `RetrievalScores` and `RetrievedMemory` as defined in the spec. Include a factory function `retrieved_memory_from_dict(item: dict[str, Any]) -> RetrievedMemory` that handles the conversion from enriched dict to typed object (parsing metadata, unpacking extras, constructing RetrievalScores).

- [ ] **Step 2: Create `tests/test_retrieval_types.py`**

Test the factory function with:
- Minimal dict (only required keys) → defaults populated
- Full dict (all keys) → all fields mapped
- Dict with metadata JSON string → parsed correctly
- Dict with `_extra` keys → unpacked to typed fields
- Dict with `retrieval_reason` nested dict → mapped to `RetrievalScores`

- [ ] **Step 3: Modify `retriever.py`**

In `_enrich_item_metadata()`: after the existing dict enrichment, convert each item to `RetrievedMemory` using the factory function. Change `_fuse_results()` return type and `retrieve()` return type to `list[RetrievedMemory]`.

Key change in `retrieve()` signature:
```python
async def retrieve(self, query: str, *, ...) -> list[RetrievedMemory]:
```

- [ ] **Step 4: Run `make lint && make typecheck`**

Fix any mypy errors from downstream consumers that still expect `dict`. These will be fixed in Task 2, so for now add `# type: ignore` comments where needed, OR update the _Retriever Protocol in context_assembler.py to return `list[RetrievedMemory]`.

- [ ] **Step 5: Run tests, commit**

```bash
git commit -m "refactor(memory): add RetrievedMemory dataclass and migrate retriever output"
```

---

## Task 2: Migrate Scorer + Rerankers to RetrievedMemory

**Files:**
- Modify: `nanobot/memory/read/scoring.py`
- Modify: `nanobot/memory/ranking/reranker.py`
- Modify: `nanobot/memory/ranking/onnx_reranker.py`

- [ ] **Step 1: Migrate `scoring.py`**

Change `filter_items()` and `score_items()` signatures from `list[dict[str, Any]]` to `list[RetrievedMemory]`. Replace all dict access patterns:

| Before | After |
|--------|-------|
| `item.get("type")` | `item.type` |
| `item.get("memory_type")` | `item.memory_type` |
| `item.get("score")` | `item.scores.final_score` |
| `item["score"] = value` | `item.scores.final_score = value` |
| `item.get("retrieval_reason", {})` | `item.scores` |
| `reason["recency"] = value` | `item.scores.recency = value` |
| `item.get("stability")` | `item.stability` |
| `item.get("entities")` | `item.entities` |
| `item.get("superseded_by_event_id")` | `item.superseded_by_event_id` |
| `item.get("timestamp")` | `item.timestamp` |
| `item.get("summary")` | `item.summary` |
| `item.get("status")` | `item.status` |
| `item.get("evidence_refs")` | `item.evidence_refs` |
| `item.get("topic")` | `item.topic` |

- [ ] **Step 2: Migrate `reranker.py` (CompositeReranker)**

Change `rerank()` signature from `list[dict[str, Any]]` to `list[RetrievedMemory]`. Replace dict access with attribute access. Update `Reranker` Protocol.

- [ ] **Step 3: Migrate `onnx_reranker.py` (OnnxCrossEncoderReranker)**

Same pattern as CompositeReranker.

- [ ] **Step 4: Run `make lint && make typecheck && make test`**

- [ ] **Step 5: Commit**

```bash
git commit -m "refactor(memory): migrate scorer and rerankers to RetrievedMemory"
```

---

## Task 3: Migrate ContextAssembler + GraphAugmenter to RetrievedMemory

**Files:**
- Modify: `nanobot/memory/read/context_assembler.py`
- Modify: `nanobot/memory/read/graph_augmentation.py`

- [ ] **Step 1: Migrate `context_assembler.py`**

Update the `_Retriever` Protocol return type to `list[RetrievedMemory]`. In `build()`, replace dict access on retrieved items:

| Before | After |
|--------|-------|
| `item.get("timestamp", "")[:16]` | `item.timestamp[:16]` |
| `item.get("type", "fact")` | `item.type` |
| `item.get("summary", "")` | `item.summary` |
| `reason.get("semantic", 0)` | `item.scores.semantic` |
| `reason.get("recency", 0)` | `item.scores.recency` |
| `reason.get("provider", "vector")` | `item.scores.provider` |

Update `_memory_item_line()` to accept `RetrievedMemory` instead of `dict[str, Any]`.

Update `_EventReader` and `_GraphAugmenter` Protocol types if they reference dicts for retrieved items.

- [ ] **Step 2: Migrate `graph_augmentation.py`**

In `build_graph_context_lines()`, replace:
| Before | After |
|--------|-------|
| `item.get("entities")` | `item.entities` |
| `evt.get("triples")` | `evt.triples` |

Update the `_GraphAugmenter` Protocol in `context_assembler.py` if its signature references item types.

- [ ] **Step 3: Run `make lint && make typecheck && make test`**

- [ ] **Step 4: Commit**

```bash
git commit -m "refactor(memory): migrate context assembler and graph augmenter to RetrievedMemory"
```

---

## Task 4: Migrate Event Ingestion to MemoryEvent

**Files:**
- Modify: `nanobot/memory/write/coercion.py`
- Modify: `nanobot/memory/write/ingester.py`
- Modify: `nanobot/memory/consolidation_pipeline.py`
- Modify: `nanobot/memory/write/micro_extractor.py`
- Modify: `nanobot/memory/persistence/profile_correction.py`

- [ ] **Step 1: Change `EventCoercer.coerce_event()` to return `MemoryEvent | None`**

Currently returns `dict[str, Any] | None`. Change to construct and return a `MemoryEvent` instance. The coercion logic stays identical — just wrap the output dict in `MemoryEvent.from_dict()` at the end.

- [ ] **Step 2: Change `EventIngester.append_events()` to accept `list[MemoryEvent]`**

Internally, convert each MemoryEvent to dict via `.to_dict()` for the existing dedup/merge/pack logic. This is the pragmatic boundary — validation at entry, dicts for internal mutation.

```python
def append_events(self, events: list[MemoryEvent]) -> int:
    raw_events = [e.to_dict() for e in events]
    # ... existing logic on raw_events ...
```

Also update `read_events()` to return `list[MemoryEvent]` by wrapping results in `MemoryEvent.from_dict()`.

- [ ] **Step 3: Update callers**

- `consolidation_pipeline.py:220` — events are already coerced dicts; wrap in `MemoryEvent.from_dict()` before calling `append_events()`
- `micro_extractor.py:122` — same pattern
- `profile_correction.py:194` — same pattern
- `heuristic_extractor.py` — `extract_events_heuristic()` returns dicts; caller wraps

- [ ] **Step 4: Update tests that call `append_events()` with raw dicts**

Find with: `grep -rn "append_events" tests/ --include="*.py"`
Each test must wrap raw dicts in `MemoryEvent.from_dict()` or construct `MemoryEvent` directly.

- [ ] **Step 5: Run `make lint && make typecheck && make test`**

- [ ] **Step 6: Commit**

```bash
git commit -m "refactor(memory): migrate event ingestion boundary to MemoryEvent

EventCoercer returns MemoryEvent. EventIngester accepts list[MemoryEvent].
Callers convert at the boundary. Internal dedup/merge stays dict-based."
```

---

## Task 5: Create ConflictRecord + Migrate Conflict Consumers

**Files:**
- Create: `nanobot/memory/persistence/conflict_types.py`
- Modify: `nanobot/memory/write/conflicts.py`
- Modify: `nanobot/memory/write/conflict_interaction.py`
- Modify: `nanobot/memory/read/scoring.py`

- [ ] **Step 1: Create `conflict_types.py` with ConflictRecord dataclass**

As defined in the spec. Include `to_dict()` and `from_dict()` methods for conversion to/from the profile dict storage format.

```python
@dataclass(slots=True)
class ConflictRecord:
    timestamp: str
    field: str
    old: str
    new: str
    status: str = "open"
    belief_id_old: str = ""
    belief_id_new: str = ""
    old_memory_id: str = ""
    new_memory_id: str = ""
    old_confidence: float = 0.65
    new_confidence: float = 0.65
    old_last_seen_at: str = ""
    new_last_seen_at: str = ""
    resolution: str = ""
    resolved_at: str = ""
    source: str = "consolidation"
    asked_at: str = ""
    index: int = -1

    def to_dict(self) -> dict[str, Any]: ...
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConflictRecord: ...
```

- [ ] **Step 2: Create tests for ConflictRecord**

Test `from_dict()` roundtrip, default values, missing keys handling.

- [ ] **Step 3: Migrate `conflicts.py`**

- `_apply_profile_updates()`: create `ConflictRecord` instead of raw dict. Store as `conflict.to_dict()` in `profile["conflicts"]` (profile storage stays dict-based).
- `list_conflicts()`: return `list[ConflictRecord]` by wrapping stored dicts in `ConflictRecord.from_dict()`.
- `resolve_conflict_details()`: work with `ConflictRecord` attributes instead of dict keys.

- [ ] **Step 4: Migrate `conflict_interaction.py`**

Update all 5 functions to receive/consume `ConflictRecord` instead of `dict`:
- `ask_user_for_conflict()`: access `conflict.old`, `conflict.new`, `conflict.asked_at` etc.
- `handle_user_conflict_reply()`: access `conflict.index`
- `conflict_relevant_to()`: access `conflict.old`, `conflict.new`

- [ ] **Step 5: Migrate `scoring.py` conflict consumption**

In `load_profile_scoring_data()`: wrap profile conflicts in `ConflictRecord.from_dict()` and access typed attributes.

- [ ] **Step 6: Run `make lint && make typecheck && make test`**

- [ ] **Step 7: Commit**

```bash
git commit -m "refactor(memory): add ConflictRecord dataclass and migrate conflict consumers

Profile storage remains dict-based. ConflictRecord used at all
consumption boundaries for type-safe field access."
```

---

## Task 6: Contract Tests + Final Verification

**Files:**
- Create: `tests/contract/test_typed_boundaries.py`

- [ ] **Step 1: Write contract tests verifying type consistency**

```python
class TestRetrievedMemoryContract:
    """Verify RetrievedMemory fields match what scorer sets and assembler reads."""

    def test_scorer_fields_exist_on_scores(self):
        """Every field the scorer writes exists on RetrievalScores."""
        scores = RetrievalScores()
        # These are set by scorer — must exist as attributes
        assert hasattr(scores, "final_score")
        assert hasattr(scores, "recency")
        assert hasattr(scores, "type_boost")
        assert hasattr(scores, "stability_boost")
        assert hasattr(scores, "reflection_penalty")
        assert hasattr(scores, "profile_adjustment")
        assert hasattr(scores, "intent")

    def test_assembler_fields_exist_on_memory(self):
        """Every field the assembler reads exists on RetrievedMemory."""
        mem = RetrievedMemory(id="t", type="fact", summary="test", timestamp="2026-01-01")
        assert hasattr(mem, "timestamp")
        assert hasattr(mem, "type")
        assert hasattr(mem, "summary")
        assert hasattr(mem, "scores")

class TestEventIngestionContract:
    """Verify MemoryEvent covers all coerced event fields."""

    def test_coerced_event_roundtrips_through_model(self):
        """A coerced event dict can create a MemoryEvent and roundtrip."""
        ...

class TestConflictRecordContract:
    """Verify ConflictRecord covers all conflict dict keys."""

    def test_all_conflict_keys_are_fields(self):
        """Every key used in conflicts.py is a ConflictRecord field."""
        ...
```

- [ ] **Step 2: Run `make pre-push`**

- [ ] **Step 3: Dispatch code review**

- [ ] **Step 4: Push and create PR**

---

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

## Risks

| Risk | Mitigation |
|------|-----------|
| Scorer mutation patterns break with attribute access | Mechanical replacement; mypy catches mismatches |
| Tests pass raw dicts to append_events | Each test updated in same commit |
| Reranker Protocol change breaks | Update Protocol in same commit as reranker |
| Profile dict storage changes | It doesn't — ConflictRecord.to_dict() preserves storage format |
| Performance of dataclass construction | Negligible — retrieval returns <100 items |
