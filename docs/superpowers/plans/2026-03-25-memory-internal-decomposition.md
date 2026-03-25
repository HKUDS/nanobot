# Memory Internal Decomposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decompose `write/ingester.py` (918 LOC) and `read/retriever.py` (821 LOC) into focused pipeline-stage modules, resolving the last open item from the March 2026 architecture review (Problem 11).

**Architecture:** Split by pipeline stage with `store.py` as the internal composition root. New classes (`EventClassifier`, `EventCoercer`, `EventDeduplicator`, `RetrievalScorer`, `GraphAugmenter`) are constructed in `store.py` and injected into slim orchestrators. Dead mem0 code is removed.

**Tech Stack:** Python 3.10+, pytest, ruff, mypy

**Spec:** `docs/superpowers/specs/2026-03-25-memory-internal-decomposition-design.md`

---

## File Map

**New files:**
- `nanobot/memory/write/classification.py` — `EventClassifier` class (~150 LOC)
- `nanobot/memory/write/coercion.py` — `EventCoercer` class (~200 LOC)
- `nanobot/memory/write/dedup.py` — `EventDeduplicator` class (~220 LOC)
- `nanobot/memory/read/scoring.py` — `RetrievalScorer` class (~300 LOC)
- `nanobot/memory/read/graph_augmentation.py` — `GraphAugmenter` class (~200 LOC)
- `tests/test_event_classifier.py` — unit tests for EventClassifier
- `tests/test_event_coercer.py` — unit tests for EventCoercer
- `tests/test_event_deduplicator.py` — unit tests for EventDeduplicator
- `tests/test_retrieval_scorer.py` — unit tests for RetrievalScorer
- `tests/test_graph_augmenter.py` — unit tests for GraphAugmenter

**Modified files:**
- `nanobot/memory/write/ingester.py` — slim down to ~150 LOC orchestrator
- `nanobot/memory/read/retriever.py` — slim down to ~200 LOC orchestrator
- `nanobot/memory/store.py` — rewire as internal composition root
- `nanobot/memory/write/conflicts.py:51-69` — remove 3 dead `_fn` params
- `nanobot/memory/consolidation_pipeline.py:46-70,248-299` — remove dead mem0 code
- `nanobot/memory/persistence/profile_correction.py:146` — update coerce_event caller
- `tests/test_ingester.py` — remove dead code tests, update for new structure
- `tests/test_store_helpers.py` — remove dead sanitization tests
- `tests/test_memory_metadata_policy.py` — remove `_event_mem0_write_plan` test
- `tests/test_retriever.py` — remove `_augment_query_with_graph` tests
- `tests/test_conflict_manager_methods.py` — remove dead `_fn` params from fixtures

---

### Task 1: Dead Code Removal — consolidation_pipeline.py

Remove the dead mem0 block and unused constructor params from `ConsolidationPipeline`.
This is done first because it eliminates call sites that would otherwise need rewiring.

**Files:**
- Modify: `nanobot/memory/consolidation_pipeline.py:46-70` (constructor) and `:248-299` (dead block)

- [ ] **Step 1: Remove dead constructor params and stored refs**

In `nanobot/memory/consolidation_pipeline.py`, remove from `__init__`:
- `persistence: Any = None` param (line 49)
- `mem0: Any = None` param (line 55)
- `mem0_raw_turn_ingestion: bool = False` param (line 56)
- `self._persistence = persistence` (line 61)
- `self._mem0 = mem0` (line 67)
- `self._mem0_raw_turn_ingestion = mem0_raw_turn_ingestion` (line 68)

Also remove the `from .write.ingester import EventIngester` import (line 29) — it's only
used inside the dead mem0 block.

- [ ] **Step 2: Remove the dead mem0 block**

Remove lines 248-299 entirely — the `if self._mem0 is not None` guard and the
`if self._mem0 is not None and self._mem0.enabled and self._mem0_raw_turn_ingestion`
block. Both are unreachable since `_mem0` is always `None`.

- [ ] **Step 3: Run lint and typecheck**

```bash
make lint && make typecheck
```

- [ ] **Step 4: Run tests**

```bash
make test
```

- [ ] **Step 5: Commit**

```bash
git add nanobot/memory/consolidation_pipeline.py
git commit -m "refactor: remove dead mem0 code from ConsolidationPipeline"
```

---

### Task 2: Dead Code Removal — ConflictManager dead params

Remove the 3 unused callback params from `ConflictManager.__init__`.

**Files:**
- Modify: `nanobot/memory/write/conflicts.py:51-69`
- Modify: `nanobot/memory/store.py:216-221`
- Modify: `tests/test_conflict_manager_methods.py`

- [ ] **Step 1: Remove dead params from ConflictManager constructor**

In `nanobot/memory/write/conflicts.py`, remove from `__init__` (lines 55-57, 63-65):
- `sanitize_mem0_text_fn: Callable[..., str] | None = None` param
- `normalize_metadata_fn: Callable[..., tuple[dict, bool]] | None = None` param
- `sanitize_metadata_fn: Callable[[dict], dict] | None = None` param
- `self._sanitize_mem0_text = sanitize_mem0_text_fn`
- `self._normalize_metadata = normalize_metadata_fn`
- `self._sanitize_metadata = sanitize_metadata_fn`

Keep `db` and `resolve_gap_fn` — they're actively used.

- [ ] **Step 2: Update store.py wiring**

In `nanobot/memory/store.py`, update `ConflictManager` construction (lines 216-225).
Remove the 3 dead kwargs:
```python
# Before
self.conflict_mgr = ConflictManager(
    self.profile_mgr,
    sanitize_mem0_text_fn=self.ingester._sanitize_mem0_text,
    normalize_metadata_fn=self.ingester._normalize_memory_metadata,
    sanitize_metadata_fn=EventIngester._sanitize_mem0_metadata,
    db=self.db,
    resolve_gap_fn=lambda: float(
        self._rollout_config.rollout.get("conflict_auto_resolve_gap", 0.25)
    ),
)
# After
self.conflict_mgr = ConflictManager(
    self.profile_mgr,
    db=self.db,
    resolve_gap_fn=lambda: float(
        self._rollout_config.rollout.get("conflict_auto_resolve_gap", 0.25)
    ),
)
```

- [ ] **Step 3: Update test fixtures**

In `tests/test_conflict_manager_methods.py`, remove `sanitize_mem0_text_fn`,
`normalize_metadata_fn`, `sanitize_metadata_fn` from all `ConflictManager(...)` calls.

- [ ] **Step 4: Run lint, typecheck, tests**

```bash
make lint && make typecheck && make test
```

- [ ] **Step 5: Commit**

```bash
git add nanobot/memory/write/conflicts.py nanobot/memory/store.py tests/test_conflict_manager_methods.py
git commit -m "refactor: remove 3 dead callback params from ConflictManager"
```

---

### Task 3: Dead Code Removal — ingester.py dead methods

Remove dead methods from `EventIngester` and their tests.

**Files:**
- Modify: `nanobot/memory/write/ingester.py`
- Modify: `tests/test_ingester.py`
- Modify: `tests/test_store_helpers.py`
- Modify: `tests/test_memory_metadata_policy.py`

- [ ] **Step 1: Remove dead methods from EventIngester**

Remove these methods from `nanobot/memory/write/ingester.py`:
- `_sync_events_to_mem0()` (lines 913-918)
- `_event_mem0_write_plan()` (lines 332-375)
- `_looks_blob_like_summary()` (lines 378-398)
- `_sanitize_mem0_metadata()` (lines 401-420)
- `_sanitize_mem0_text()` (lines 422-437)

- [ ] **Step 2: Remove dead tests**

In `tests/test_ingester.py`:
- Remove `test_sync_events_to_mem0_noop_with_db` (line 415)
- Remove tests for `_sanitize_mem0_text` (around lines 250-270)
- Remove tests for `_looks_blob_like_summary` (around lines 352-362)
- Remove tests for `_sanitize_mem0_metadata` (around lines 343-347)

In `tests/test_store_helpers.py`:
- Remove `_event_mem0_write_plan` tests (around line 95)
- Remove `_looks_blob_like_summary` tests (around line 108)
- Remove `_sanitize_mem0_metadata` tests (around line 111)
- Remove `_sanitize_mem0_text` tests (around line 118)

In `tests/test_memory_metadata_policy.py`:
- Remove `_event_mem0_write_plan` test (around line 39)

- [ ] **Step 3: Run lint, typecheck, tests**

```bash
make lint && make typecheck && make test
```

- [ ] **Step 4: Commit**

```bash
git add nanobot/memory/write/ingester.py tests/test_ingester.py tests/test_store_helpers.py tests/test_memory_metadata_policy.py
git commit -m "refactor: remove dead mem0 methods from EventIngester"
```

---

### Task 4: Dead Code Removal — retriever.py dead method

Remove `_augment_query_with_graph` and its tests.

**Files:**
- Modify: `nanobot/memory/read/retriever.py:263-286`
- Modify: `tests/test_retriever.py`

- [ ] **Step 1: Remove `_augment_query_with_graph` from MemoryRetriever**

Remove lines 263-286 from `nanobot/memory/read/retriever.py`.

- [ ] **Step 2: Remove tests**

In `tests/test_retriever.py`, remove the `_augment_query_with_graph` test (around
line 222, including all test methods that call `_augment_query_with_graph`).

- [ ] **Step 3: Run lint, typecheck, tests**

```bash
make lint && make typecheck && make test
```

- [ ] **Step 4: Commit**

```bash
git add nanobot/memory/read/retriever.py tests/test_retriever.py
git commit -m "refactor: remove dead _augment_query_with_graph from MemoryRetriever"
```

---

### Task 5: Extract Write Path + Rewire store.py (atomic)

Extract `EventClassifier`, `EventCoercer`, `EventDeduplicator` from `EventIngester`,
update `EventIngester` constructor to receive collaborators, and rewire `store.py` —
all in one commit. This avoids intermediate states with prohibited inline construction
or broken lambdas.

**Files:**
- Create: `nanobot/memory/write/classification.py`
- Create: `nanobot/memory/write/coercion.py`
- Create: `nanobot/memory/write/dedup.py`
- Create: `tests/test_event_classifier.py`
- Create: `tests/test_event_coercer.py`
- Create: `tests/test_event_deduplicator.py`
- Modify: `nanobot/memory/write/ingester.py`
- Modify: `nanobot/memory/store.py`
- Modify: `nanobot/memory/persistence/profile_correction.py`

- [ ] **Step 1: Write failing tests for all three new classes**

Create `tests/test_event_classifier.py`:

```python
"""Tests for EventClassifier — memory type classification and metadata enrichment."""
from __future__ import annotations

from nanobot.memory.write.classification import EventClassifier


class TestClassifyMemoryType:
    def test_preference_is_semantic_high(self) -> None:
        classifier = EventClassifier()
        mem_type, stability, is_mixed = classifier.classify_memory_type(
            event_type="preference", summary="User prefers dark mode", source="chat"
        )
        assert mem_type == "semantic"
        assert stability == "high"
        assert is_mixed is False

    def test_task_is_episodic(self) -> None:
        classifier = EventClassifier()
        mem_type, stability, _ = classifier.classify_memory_type(
            event_type="task", summary="Fix the login bug", source="chat"
        )
        assert mem_type == "episodic"

    def test_reflection_source_returns_reflection(self) -> None:
        classifier = EventClassifier()
        mem_type, _, _ = classifier.classify_memory_type(
            event_type="fact", summary="anything", source="reflection"
        )
        assert mem_type == "reflection"

    def test_mixed_semantic_with_incident_markers(self) -> None:
        classifier = EventClassifier()
        _, _, is_mixed = classifier.classify_memory_type(
            event_type="preference",
            summary="User prefers Python because it failed with Go last time",
            source="chat",
        )
        assert is_mixed is True


class TestNormalizeMemoryMetadata:
    def test_basic_normalization(self) -> None:
        classifier = EventClassifier()
        meta, is_mixed = classifier.normalize_memory_metadata(
            None, event_type="fact", summary="Sky is blue", source="chat"
        )
        assert meta["memory_type"] == "semantic"
        assert meta["stability"] == "high"
        assert meta["source"] == "chat"
        assert isinstance(meta["evidence_refs"], list)

    def test_reflection_without_evidence_downgraded(self) -> None:
        classifier = EventClassifier()
        meta, _ = classifier.normalize_memory_metadata(
            {"memory_type": "reflection"},
            event_type="fact", summary="A reflection", source="reflection",
        )
        assert meta["memory_type"] == "episodic"
        assert meta["stability"] == "low"


class TestDefaultTopicForEventType:
    def test_known_types(self) -> None:
        assert EventClassifier.default_topic_for_event_type("preference") == "user_preference"
        assert EventClassifier.default_topic_for_event_type("task") == "task_progress"

    def test_unknown_type(self) -> None:
        assert EventClassifier.default_topic_for_event_type("unknown") == "general"


class TestDistillSemanticSummary:
    def test_strips_causal_clause(self) -> None:
        result = EventClassifier.distill_semantic_summary(
            "User prefers Python because Go was hard"
        )
        assert result == "User prefers Python"

    def test_short_result_returns_full(self) -> None:
        result = EventClassifier.distill_semantic_summary("Short because reason")
        assert result == "Short because reason"
```

Create `tests/test_event_coercer.py`:

```python
"""Tests for EventCoercer — event normalization and provenance."""
from __future__ import annotations

from nanobot.memory.write.classification import EventClassifier
from nanobot.memory.write.coercion import EventCoercer


class TestBuildEventId:
    def test_deterministic(self) -> None:
        id1 = EventCoercer.build_event_id("fact", "Sky is blue", "2026-01-01T00:00")
        id2 = EventCoercer.build_event_id("fact", "Sky is blue", "2026-01-01T00:00")
        assert id1 == id2
        assert len(id1) == 16

    def test_different_inputs_different_ids(self) -> None:
        id1 = EventCoercer.build_event_id("fact", "Sky is blue", "2026-01-01T00:00")
        id2 = EventCoercer.build_event_id("fact", "Grass is green", "2026-01-01T00:00")
        assert id1 != id2


class TestCoerceEvent:
    def test_basic_coercion(self) -> None:
        coercer = EventCoercer(EventClassifier())
        result = coercer.coerce_event(
            {"summary": "User likes Python", "type": "preference"}, source_span=[0, 10],
        )
        assert result is not None
        assert result["summary"] == "User likes Python"
        assert result["type"] == "preference"
        assert result["id"]

    def test_missing_summary_returns_none(self) -> None:
        coercer = EventCoercer(EventClassifier())
        assert coercer.coerce_event({"type": "fact"}, source_span=[0, 0]) is None

    def test_invalid_type_defaults_to_fact(self) -> None:
        coercer = EventCoercer(EventClassifier())
        result = coercer.coerce_event(
            {"summary": "test", "type": "invalid_type"}, source_span=[0, 5],
        )
        assert result is not None
        assert result["type"] == "fact"


class TestInferEpisodicStatus:
    def test_task_defaults_to_open(self) -> None:
        coercer = EventCoercer(EventClassifier())
        assert coercer.infer_episodic_status(event_type="task", summary="Fix the bug") == "open"

    def test_non_task_returns_none(self) -> None:
        coercer = EventCoercer(EventClassifier())
        assert coercer.infer_episodic_status(event_type="preference", summary="Likes Python") is None


class TestEnsureEventProvenance:
    def test_adds_canonical_id(self) -> None:
        coercer = EventCoercer(EventClassifier())
        result = coercer.ensure_event_provenance(
            {"id": "abc123", "type": "fact", "summary": "test"}
        )
        assert result["canonical_id"] == "abc123"
        assert isinstance(result["evidence"], list)
```

Create `tests/test_event_deduplicator.py`:

```python
"""Tests for EventDeduplicator — semantic dedup, supersession, and merge."""
from __future__ import annotations

from nanobot.memory.write.classification import EventClassifier
from nanobot.memory.write.coercion import EventCoercer
from nanobot.memory.write.dedup import EventDeduplicator


class TestEventSimilarity:
    def test_identical_events(self) -> None:
        a = {"type": "fact", "summary": "User likes Python", "entities": ["Python"]}
        lex, sem = EventDeduplicator.event_similarity(a, a)
        assert lex == 1.0

    def test_different_events(self) -> None:
        a = {"type": "fact", "summary": "Sky is blue", "entities": []}
        b = {"type": "fact", "summary": "Grass is green", "entities": []}
        lex, sem = EventDeduplicator.event_similarity(a, b)
        assert lex < 0.5


class TestFindSemanticDuplicate:
    def test_finds_exact_duplicate(self) -> None:
        dedup = EventDeduplicator(coercer=EventCoercer(EventClassifier()))
        candidate = {"type": "fact", "summary": "User likes Python", "entities": ["Python"]}
        existing = [dict(candidate)]
        idx, score = dedup.find_semantic_duplicate(candidate, existing)
        assert idx == 0

    def test_no_duplicate(self) -> None:
        dedup = EventDeduplicator(coercer=EventCoercer(EventClassifier()))
        idx, _ = dedup.find_semantic_duplicate(
            {"type": "fact", "summary": "Sky is blue", "entities": []},
            [{"type": "fact", "summary": "Grass is green", "entities": []}],
        )
        assert idx is None


class TestMergeSourceSpan:
    def test_merges_two_spans(self) -> None:
        assert EventDeduplicator.merge_source_span([5, 10], [2, 8]) == [2, 10]

    def test_invalid_base(self) -> None:
        assert EventDeduplicator.merge_source_span(None, [2, 8]) == [0, 8]


class TestMergeEvents:
    def test_unions_entities(self) -> None:
        dedup = EventDeduplicator(coercer=EventCoercer(EventClassifier()))
        base = {
            "id": "a", "type": "fact", "summary": "test",
            "entities": ["Python"], "confidence": 0.7, "salience": 0.6,
            "source_span": [0, 5], "timestamp": "2026-01-01T00:00:00",
        }
        incoming = {
            "id": "b", "type": "fact", "summary": "test",
            "entities": ["Go"], "confidence": 0.8, "salience": 0.7,
            "source_span": [5, 10], "timestamp": "2026-01-02T00:00:00",
        }
        merged = dedup.merge_events(base, incoming, similarity=0.9)
        assert "Python" in merged["entities"]
        assert "Go" in merged["entities"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_event_classifier.py tests/test_event_coercer.py tests/test_event_deduplicator.py -v
```

Expected: `ModuleNotFoundError` for all three.

- [ ] **Step 3: Create `classification.py`**

Create `nanobot/memory/write/classification.py`. Move from `ingester.py`:
- `_classify_memory_type` (lines 205-253) → `classify_memory_type`
- `_normalize_memory_metadata` (lines 273-330) → `normalize_memory_metadata`
- `_default_topic_for_event_type` (lines 193-203) → `default_topic_for_event_type` (static)
- `_distill_semantic_summary` (lines 256-271) → `distill_semantic_summary` (static)
- Constants: `EVENT_TYPES`, `MEMORY_TYPES`, `MEMORY_STABILITY` (lines 46-48)

Imports: `from .._text import _contains_any, _utc_now_iso, _safe_float`.
No constructor dependencies — stateless class.

- [ ] **Step 4: Create `coercion.py`**

Create `nanobot/memory/write/coercion.py`. Move from `ingester.py`:
- `_build_event_id` (lines 83-86) → `build_event_id` (static)
- `_infer_episodic_status` (lines 88-102) → `infer_episodic_status`
- `_coerce_event` (lines 104-186) → `coerce_event`
- `_ensure_event_provenance` (lines 490-569) → `ensure_event_provenance`
- Constants: `EPISODIC_STATUS_OPEN`, `EPISODIC_STATUS_RESOLVED` (lines 49-50)

Constructor: `EventCoercer(classifier: EventClassifier)`.

**IMPORTANT:** Inside `ensure_event_provenance`, update the internal call
`self._infer_episodic_status(...)` to `self.infer_episodic_status(...)` — both methods
live on the same `EventCoercer` class after the move, so the underscore-prefixed name
no longer applies.

Imports: `hashlib`, `re`, `from .._text import _norm_text, _safe_float, _to_str_list, _utc_now_iso`,
`from ..event import is_resolved_task_or_decision, memory_type_for_item`,
`from .classification import EventClassifier, EVENT_TYPES, MEMORY_TYPES, MEMORY_STABILITY`.

- [ ] **Step 5: Create `dedup.py`**

Create `nanobot/memory/write/dedup.py`. Move from `ingester.py`:
- `_event_similarity` (lines 572-590) → `event_similarity` (static)
- `_find_semantic_duplicate` (lines 592-632) → `find_semantic_duplicate`
- `_find_semantic_supersession` (lines 634-687) → `find_semantic_supersession`
- `_merge_events` (lines 689-759) → `merge_events`
- `_merge_source_span` (lines 474-488) → `merge_source_span` (static)

Constructor: `EventDeduplicator(coercer: EventCoercer, conflict_pair_fn: Callable | None = None)`.
Uses `self._coercer.ensure_event_provenance()` and `self._coercer.infer_episodic_status()`
in `merge_events`. Uses `self._conflict_pair_fn` in `find_semantic_supersession`.

Imports: `from .._text import _norm_text, _safe_float, _to_str_list, _tokenize, _utc_now_iso`,
`from ..event import memory_type_for_item`,
`from .coercion import EventCoercer, EPISODIC_STATUS_OPEN, EPISODIC_STATUS_RESOLVED`.

- [ ] **Step 6: Slim down `ingester.py` and update its constructor**

Remove all moved methods from `nanobot/memory/write/ingester.py`. The remaining
`EventIngester` should contain only:
- `__init__` — receives pre-built collaborators (no inline construction)
- `append_events()` — calls `self._coercer.*` and `self._dedup.*`
- `read_events()` — unchanged
- `_ingest_graph_triples()` — unchanged

New constructor:
```python
def __init__(
    self,
    *,
    coercer: EventCoercer,
    dedup: EventDeduplicator,
    graph: KnowledgeGraph | None,
    rollout_fn: Callable[[], dict[str, Any]],
    db: UnifiedMemoryDB | None = None,
    embedder: Embedder | None = None,
) -> None:
    self._coercer = coercer
    self._dedup = dedup
    self._graph = graph
    self._rollout_fn = rollout_fn
    self._db = db
    self._embedder = embedder
```

Keep class-level constant aliases (`EventIngester.EVENT_TYPES = EVENT_TYPES` etc.)
for backward compat with external code.

Add imports: `from .classification import EventClassifier, EVENT_TYPES, MEMORY_TYPES, MEMORY_STABILITY`,
`from .coercion import EventCoercer, EPISODIC_STATUS_OPEN, EPISODIC_STATUS_RESOLVED`,
`from .dedup import EventDeduplicator`.

- [ ] **Step 7: Rewire `store.py` for write path**

In `nanobot/memory/store.py`, add imports:
```python
from .write.classification import EventClassifier
from .write.coercion import EventCoercer
from .write.dedup import EventDeduplicator
```

Add early construction (before extractor, around line 137):
```python
self._classifier = EventClassifier()
self._coercer = EventCoercer(self._classifier)
```

Update extractor wiring (line 139):
```python
coerce_event=lambda raw, **kw: self._coercer.coerce_event(raw, **kw),
```

After graph construction, add dedup and update ingester construction:
```python
self._dedup = EventDeduplicator(
    coercer=self._coercer,
    conflict_pair_fn=lambda old, new: self.profile_mgr._conflict_pair(old, new),
)
self.ingester = EventIngester(
    coercer=self._coercer,
    dedup=self._dedup,
    graph=self.graph,
    rollout_fn=lambda: self._rollout_config.rollout,
    db=self.db,
    embedder=self._embedder,
)
```

- [ ] **Step 8: Update `profile_correction.py`**

In `nanobot/memory/persistence/profile_correction.py`, add `coercer` as a new
constructor parameter on `CorrectionOrchestrator`. Update the call at line 146:
`self._ingester._coerce_event(...)` → `self._coercer.coerce_event(...)`.

In `nanobot/memory/store.py`, update the `CorrectionOrchestrator` construction
(around line 279) to pass `coercer=self._coercer`.

- [ ] **Step 9: Run tests**

```bash
pytest tests/test_event_classifier.py tests/test_event_coercer.py tests/test_event_deduplicator.py -v && make lint && make typecheck && make test
```

- [ ] **Step 10: Commit**

```bash
git add nanobot/memory/write/classification.py nanobot/memory/write/coercion.py nanobot/memory/write/dedup.py nanobot/memory/write/ingester.py nanobot/memory/store.py nanobot/memory/persistence/profile_correction.py tests/test_event_classifier.py tests/test_event_coercer.py tests/test_event_deduplicator.py
git commit -m "refactor: extract write path classes and rewire store.py composition root"
```

---

### Task 6: Extract Read Path + Rewire store.py (atomic)

Extract `RetrievalScorer` and `GraphAugmenter` from `MemoryRetriever`, update
`MemoryRetriever` constructor, and rewire `store.py` — all in one commit.

**Files:**
- Create: `nanobot/memory/read/scoring.py`
- Create: `nanobot/memory/read/graph_augmentation.py`
- Create: `tests/test_retrieval_scorer.py`
- Create: `tests/test_graph_augmenter.py`
- Modify: `nanobot/memory/read/retriever.py`
- Modify: `nanobot/memory/store.py`

- [ ] **Step 1: Write failing tests for both new classes**

Create `tests/test_retrieval_scorer.py`:

```python
"""Tests for RetrievalScorer — filter, score, and rerank pipeline."""
from __future__ import annotations

from unittest.mock import MagicMock

from nanobot.memory.read.retrieval_planner import RetrievalPlanner
from nanobot.memory.read.scoring import RetrievalScorer


def _make_scorer() -> RetrievalScorer:
    profile_mgr = MagicMock()
    profile_mgr.read_profile.return_value = {
        "preferences": [], "stable_facts": [], "active_projects": [],
        "relationships": [], "constraints": [],
    }
    reranker = MagicMock()
    reranker.rerank.side_effect = lambda q, items: items
    return RetrievalScorer(
        profile_mgr=profile_mgr,
        reranker=reranker,
        rollout_fn=lambda: {"reranker_mode": "disabled"},
    )


class TestFilterItems:
    def test_empty_input(self) -> None:
        scorer = _make_scorer()
        plan = RetrievalPlanner().plan("anything")
        filtered, counts = scorer.filter_items([], plan)
        assert filtered == []


class TestScoreItems:
    def test_assigns_score(self) -> None:
        scorer = _make_scorer()
        plan = RetrievalPlanner().plan("test query")
        profile_data = scorer.load_profile_scoring_data()
        items = [{
            "type": "fact", "summary": "test", "score": 0.5,
            "stability": "high", "memory_type": "semantic",
            "timestamp": "2026-01-01T00:00:00",
        }]
        scored = scorer.score_items(
            items, plan, profile_data, set(),
            use_recency=True, router_enabled=True, type_separation_enabled=True,
        )
        assert len(scored) == 1
        assert "score" in scored[0]


class TestRerankItems:
    def test_disabled_returns_unchanged(self) -> None:
        scorer = _make_scorer()
        items = [{"id": "1", "summary": "test"}]
        assert scorer.rerank_items("query", items) == items
```

Create `tests/test_graph_augmenter.py`:

```python
"""Tests for GraphAugmenter — graph-related retrieval operations."""
from __future__ import annotations

from nanobot.memory.read.graph_augmentation import GraphAugmenter


class TestBuildEntityIndex:
    def test_collects_entities(self) -> None:
        aug = GraphAugmenter(graph=None, read_events_fn=lambda **kw: [])
        index = aug.build_entity_index([
            {"entities": ["Python", "Go"]}, {"entities": ["Rust"]},
        ])
        assert {"python", "go", "rust"} <= index

    def test_empty_events(self) -> None:
        aug = GraphAugmenter(graph=None, read_events_fn=lambda **kw: [])
        assert aug.build_entity_index([]) == set()


class TestExtractQueryEntities:
    def test_matches_known_entities(self) -> None:
        aug = GraphAugmenter(graph=None, read_events_fn=lambda **kw: [])
        assert "python" in aug.extract_query_entities("Tell me about python", {"python", "go"})

    def test_bigram_matching(self) -> None:
        aug = GraphAugmenter(graph=None, read_events_fn=lambda **kw: [])
        assert "github actions" in aug.extract_query_entities(
            "set up github actions", {"github actions"}
        )


class TestCollectGraphEntityNames:
    def test_no_graph_returns_empty(self) -> None:
        aug = GraphAugmenter(graph=None, read_events_fn=lambda **kw: [])
        assert aug.collect_graph_entity_names("test", []) == set()


class TestResetCache:
    def test_clears_cache(self) -> None:
        aug = GraphAugmenter(graph=None, read_events_fn=lambda **kw: [])
        aug._graph_cache[frozenset({"a"})] = {"b"}
        aug.reset_cache()
        assert aug._graph_cache == {}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_retrieval_scorer.py tests/test_graph_augmenter.py -v
```

Expected: `ModuleNotFoundError` for both.

- [ ] **Step 3: Create `scoring.py`**

Create `nanobot/memory/read/scoring.py`. Move from `retriever.py`:
- `_load_profile_scoring_data` (lines 292-328) → `load_profile_scoring_data`
- `_filter_items` (lines 334-456) → `filter_items`
- `_score_items` (lines 462-611) → `score_items`
- `_rerank_items` (lines 617-637) → `rerank_items`
- Constants: `_FIELD_BY_EVENT_TYPE` (lines 39-46), `_STABILITY_BOOST` (lines 48-52)
- Helper: `_contains_norm_phrase` (lines 55-61)
- Class constants: `PROFILE_KEYS`, `PROFILE_STATUS_STALE`, `PROFILE_STATUS_CONFLICTED`

Constructor: `RetrievalScorer(*, profile_mgr, reranker, rollout_fn)`.

Imports: `copy`, `from .._text import _contains_any, _norm_text`,
`from .retrieval_planner import RetrievalPlan, RetrievalPlanner`.
TYPE_CHECKING: `ProfileManager` (from `..persistence.profile_io`), `Reranker` (from `..ranking.reranker`).

- [ ] **Step 4: Create `graph_augmentation.py`**

Create `nanobot/memory/read/graph_augmentation.py`. Move from `retriever.py`:
- `_collect_graph_entity_names` (lines 673-711) → `collect_graph_entity_names`
- `_build_entity_index` (lines 717-724) → `build_entity_index`
- `_extract_query_entities` (lines 726-747) → `extract_query_entities`
- `_build_graph_context_lines` (lines 749-821) → `build_graph_context_lines`

Add `_graph_cache` dict and `reset_cache()` method.

Constructor: `GraphAugmenter(*, graph, extractor=None, read_events_fn)`.

Imports: `re`, `from ..graph._keywords import _extract_query_keywords`.
TYPE_CHECKING: `KnowledgeGraph`, `MemoryExtractor`.

- [ ] **Step 5: Slim down `retriever.py` and update its constructor**

Remove all moved methods from `nanobot/memory/read/retriever.py`. Remaining:
- `__init__` — receives pre-built collaborators
- `retrieve()` — calls `self._graph_aug.reset_cache()` at start
- `_retrieve_unified()` — delegates to `self._scorer.*` and `self._graph_aug.*`
- `_fuse_results()` (static) — unchanged
- `_enrich_item_metadata()` — unchanged

New constructor:
```python
def __init__(
    self,
    *,
    scorer: RetrievalScorer,
    graph_aug: GraphAugmenter,
    planner: RetrievalPlanner,
    db: UnifiedMemoryDB | None = None,
    embedder: Embedder | None = None,
) -> None:
    self._scorer = scorer
    self._graph_aug = graph_aug
    self._planner = planner
    self._db = db
    self._embedder = embedder
```

- [ ] **Step 6: Rewire `store.py` for read path**

Add imports:
```python
from .read.scoring import RetrievalScorer
from .read.graph_augmentation import GraphAugmenter
```

After reranker construction, add scorer and graph_aug, and update retriever:
```python
self._scorer = RetrievalScorer(
    profile_mgr=self.profile_mgr,
    reranker=self._reranker,
    rollout_fn=lambda: self._rollout_config.rollout,
)
self._graph_aug = GraphAugmenter(
    graph=self.graph,
    extractor=self.extractor,
    read_events_fn=self.ingester.read_events,
)
self.retriever = MemoryRetriever(
    scorer=self._scorer,
    graph_aug=self._graph_aug,
    planner=self._planner,
    db=self.db,
    embedder=self._embedder,
)
```

Update assembler `build_graph_context_lines_fn` (lines 169-171 and 345-346):
```python
build_graph_context_lines_fn=lambda *a, **kw: self._graph_aug.build_graph_context_lines(
    *a, **kw
),
```

- [ ] **Step 7: Run tests**

```bash
pytest tests/test_retrieval_scorer.py tests/test_graph_augmenter.py -v && make lint && make typecheck && make test
```

- [ ] **Step 8: Commit**

```bash
git add nanobot/memory/read/scoring.py nanobot/memory/read/graph_augmentation.py nanobot/memory/read/retriever.py nanobot/memory/store.py tests/test_retrieval_scorer.py tests/test_graph_augmenter.py
git commit -m "refactor: extract read path classes and rewire store.py composition root"
```

---

### Task 7: Final Validation

Run the full validation suite and verify structural limits.

**Files:** None (validation only)

- [ ] **Step 1: Run full check**

```bash
make check
```

All must pass: lint, typecheck, import-check, structure-check, prompt-check, unit tests,
integration tests.

- [ ] **Step 2: Verify structural limits**

```bash
# write/ file count (limit: 15)
find nanobot/memory/write -maxdepth 1 -name '*.py' ! -name '__init__.py' | wc -l
# Expected: 6

# read/ file count (limit: 15)
find nanobot/memory/read -maxdepth 1 -name '*.py' ! -name '__init__.py' | wc -l
# Expected: 5

# Largest file in write/ (limit: 500)
wc -l nanobot/memory/write/*.py | sort -n
# Expected: all under 500

# Largest file in read/ (limit: 500)
wc -l nanobot/memory/read/*.py | sort -n
# Expected: scoring.py ~300, graph_augmentation.py ~200, retriever.py ~200
# Note: context_assembler.py (593) and retrieval_planner.py (343) are unchanged, out of scope

# __init__.py exports (limit: 12)
grep -c ',' nanobot/memory/__init__.py
# Expected: unchanged at 8
```

- [ ] **Step 3: Final commit if any fixups needed**

```bash
git add -A && git commit -m "fix: address validation issues from memory decomposition"
```

Only if Step 1 or 2 revealed issues that needed fixing.
