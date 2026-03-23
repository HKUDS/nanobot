# Store Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the store decomposition by extracting the consolidation pipeline, unifying the retriever's internal pipeline, eliminating `_store` back-references, and fixing helper duplication.

**Architecture:** Extract `ConsolidationPipeline` from store.py. Restructure `retriever.py` using Pipes and Filters (Source → Graph Augment → Filter → Score → Rerank → Truncate). Inject subsystem objects into profile.py and conflicts.py to replace `_store` back-references. Fix eval.py helper duplication.

**Tech Stack:** Python 3.10+, pytest, pytest-asyncio, ruff, mypy

**Worktree:** `/home/carlos/nanobot-store-refinement` (branch `refactor/store-refinement`)

**Spec:** `docs/superpowers/specs/2026-03-22-store-refinement-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `nanobot/agent/memory/consolidation_pipeline.py` | ConsolidationPipeline — full consolidation logic |
| Create | `tests/test_consolidation_pipeline.py` | Unit tests for consolidation pipeline |
| Modify | `nanobot/agent/memory/store.py` | Remove consolidation code, delegate to pipeline |
| Modify | `nanobot/agent/memory/snapshot.py` | Add pinned-section helpers as classmethods |
| Modify | `nanobot/agent/memory/retriever.py` | Break up `_retrieve_core`, unify scoring pipeline |
| Modify | `tests/test_retriever.py` | Add tests for pipeline stages |
| Modify | `nanobot/agent/memory/conflicts.py` | Replace `_store` with callable injection |
| Modify | `nanobot/agent/memory/profile.py` | Replace `_store` with subsystem injection |
| Modify | `nanobot/agent/memory/store.py` | Update wiring for conflicts + profile |
| Modify | `nanobot/agent/memory/eval.py` | Import helpers instead of duplicating |
| Modify | `nanobot/agent/memory/__init__.py` | Add ConsolidationPipeline export |

---

### Task 1: Move pinned-section helpers to `snapshot.py`

**Files:**
- Modify: `nanobot/agent/memory/snapshot.py`
- Modify: `nanobot/agent/memory/store.py`

- [ ] **Step 1: Read current snapshot.py**

Read `snapshot.py` to understand its `__init__` signature — it currently receives `extract_pinned_section_fn` and `restore_pinned_section_fn` as callable parameters.

- [ ] **Step 2: Add pinned-section methods to `MemorySnapshot`**

Add these as classmethods on `MemorySnapshot` (copy from `store.py` lines 390-420):

```python
_PINNED_START = "<!-- user-pinned -->"
_PINNED_END = "<!-- end-user-pinned -->"

@classmethod
def _extract_pinned_section(cls, text: str) -> str | None:
    """Extract user-pinned content from MEMORY.md, if present."""
    start = text.find(cls._PINNED_START)
    end = text.find(cls._PINNED_END)
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + len(cls._PINNED_END)]

@classmethod
def _restore_pinned_section(cls, new_text: str, pinned: str) -> str:
    """Re-insert a pinned section into new MEMORY.md content."""
    existing = cls._extract_pinned_section(new_text)
    if existing:
        return new_text.replace(existing, pinned)
    lines = new_text.split("\n")
    insert_at = 0
    for i, line in enumerate(lines):
        if line.startswith("#"):
            insert_at = i + 1
            break
    lines.insert(insert_at, pinned)
    return "\n".join(lines)
```

- [ ] **Step 3: Update `MemorySnapshot.__init__` to remove callable injection**

Remove `extract_pinned_section_fn` and `restore_pinned_section_fn` parameters. Update `rebuild_memory_snapshot` to call `self._extract_pinned_section` and `self._restore_pinned_section` directly.

- [ ] **Step 4: Update `MemoryStore.__init__` wiring**

Remove the pinned-section lambdas passed to `MemorySnapshot()`. Remove `_PINNED_START`, `_PINNED_END`, `_extract_pinned_section`, `_restore_pinned_section` from `MemoryStore`.

- [ ] **Step 5: Run tests and lint**

```bash
cd /home/carlos/nanobot-store-refinement && make lint && make typecheck && pytest tests/ -x -q
```

- [ ] **Step 6: Commit**

```bash
cd /home/carlos/nanobot-store-refinement && git add -A && git commit -m "refactor(memory): move pinned-section helpers to MemorySnapshot"
```

---

### Task 2: Extract `ConsolidationPipeline` from `store.py`

**Files:**
- Create: `nanobot/agent/memory/consolidation_pipeline.py`
- Create: `tests/test_consolidation_pipeline.py`
- Modify: `nanobot/agent/memory/store.py`
- Modify: `nanobot/agent/memory/__init__.py`

- [ ] **Step 1: Create `consolidation_pipeline.py`**

Read `store.py` lines 340-597 — the entire consolidation section. Move ALL of these methods into a new `ConsolidationPipeline` class:

- `_select_messages_for_consolidation` (lines 340-366)
- `_format_conversation_lines` (lines 368-378, static)
- `_build_consolidation_prompt` (lines 380-388, static)
- `_apply_save_memory_tool_result` (lines 422-428)
- `_finalize_consolidation` (lines 430-438)
- `consolidate` (lines 440-597)

Constructor:
```python
class ConsolidationPipeline:
    def __init__(
        self,
        *,
        persistence: MemoryPersistence,
        extractor: MemoryExtractor,
        ingester: EventIngester,
        profile_mgr: ProfileManager,
        conflict_mgr: ConflictManager,
        snapshot: MemorySnapshot,
        mem0: _Mem0Adapter,
        mem0_raw_turn_ingestion: bool,
        memory_file: Path,
        history_file: Path,
    ) -> None:
```

Import `MemorySnapshot._extract_pinned_section` and `._restore_pinned_section` from snapshot.py (used in `consolidate()` if pinned content exists — check if consolidation actually uses them; if not, skip).

Import helpers from `helpers.py`: `_utc_now_iso`, `_contains_any`.

Import `prompts` from `prompt_loader` and `_SAVE_MEMORY_TOOL` from `constants`.

- [ ] **Step 2: Create `tests/test_consolidation_pipeline.py`**

Write focused tests (construct `ConsolidationPipeline` directly, mock all deps):
- `test_select_messages_archive_all` — returns all messages
- `test_select_messages_normal` — returns old messages beyond keep window
- `test_select_messages_too_few` — returns None
- `test_format_conversation_lines` — formats with timestamps and roles
- `test_build_consolidation_prompt` — includes memory and conversation
- `test_consolidate_no_tool_call` — LLM doesn't call save_memory → returns False
- `test_consolidate_success` — full happy path with mocked provider
- `test_consolidate_exception` — crash-barrier returns False
- `test_finalize_updates_session_pointer` — session.last_consolidated updated

- [ ] **Step 3: Wire into `MemoryStore.__init__`**

```python
from .consolidation_pipeline import ConsolidationPipeline

self._consolidation = ConsolidationPipeline(
    persistence=self.persistence,
    extractor=self.extractor,
    ingester=self.ingester,
    profile_mgr=self.profile_mgr,
    conflict_mgr=self.conflict_mgr,
    snapshot=self.snapshot,
    mem0=self.mem0,
    mem0_raw_turn_ingestion=self._mem0_raw_turn_ingestion,
    memory_file=self.memory_file,
    history_file=self.history_file,
)
```

Replace `MemoryStore.consolidate()` with a one-line delegation:
```python
async def consolidate(self, session, provider, model, **kwargs):
    return await self._consolidation.consolidate(session, provider, model, **kwargs)
```

Delete ALL consolidation helper methods from `MemoryStore`.

- [ ] **Step 4: Update `__init__.py` exports**

Add `ConsolidationPipeline` to imports and `__all__`.

- [ ] **Step 5: Run tests and lint**

```bash
cd /home/carlos/nanobot-store-refinement && make lint && make typecheck && pytest tests/ -x -q
```

- [ ] **Step 6: Commit**

```bash
cd /home/carlos/nanobot-store-refinement && git add -A && git commit -m "refactor(memory): extract ConsolidationPipeline from MemoryStore (~221 lines)"
```

---

### Task 3: Restructure retriever — extract pipeline stages

**Files:**
- Modify: `nanobot/agent/memory/retriever.py`
- Modify: `tests/test_retriever.py`

This is the most complex task. Read `retriever.py` fully before starting.

- [ ] **Step 1: Read `retriever.py` and map the current structure**

Understand:
- `retrieve()` (lines ~89-260): dispatcher with BM25 branch + mem0 branch + shadow mode
- `_retrieve_core()` (lines ~263-681): the 419-line monolith

- [ ] **Step 2: Extract `_augment_query_with_graph()`**

This logic appears in both paths. Extract into:
```python
def _augment_query_with_graph(self, query: str) -> tuple[str, set[str]]:
    """Expand query with graph entity names. Returns (augmented_query, extra_terms)."""
```

Pull the graph keyword extraction + `get_related_entity_names_sync` calls into this method. Update both `retrieve()` BM25 path and `_retrieve_core()` to use it.

- [ ] **Step 3: Extract `_source_from_bm25()`**

Move the BM25 candidate sourcing from `retrieve()` into:
```python
def _source_from_bm25(
    self, query: str, augmented_query: str, plan: RetrievalPlan, top_k: int,
    graph_entities: set[str],
) -> list[dict[str, Any]]:
    """Source candidates via local BM25 keyword search."""
```

This includes: `read_events_fn()`, `_local_retrieve()`, `_topic_fallback_retrieve()`, and the entity boost loop.

- [ ] **Step 4: Extract `_source_from_mem0()`**

Move the mem0 search call from `_retrieve_core()` into:
```python
def _source_from_mem0(
    self, query: str, plan: RetrievalPlan, candidate_k: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Source candidates via mem0 vector search. Returns (items, source_stats)."""
```

Includes: `self._mem0.search()` call + result unpacking + supplementary BM25 merge.

- [ ] **Step 5: Extract `_load_profile_scoring_data()`**

```python
def _load_profile_scoring_data(self) -> dict[str, Any]:
    """Load profile and compute conflict resolution scoring data."""
```

Includes: `profile_mgr.read_profile()`, extracting resolved conflicts, building keep_new/keep_old sets.

- [ ] **Step 6: Extract `_filter_items()`**

```python
def _filter_items(
    self, items: list[dict], plan: RetrievalPlan, *, reflection_enabled: bool,
) -> list[dict]:
    """Apply intent-based filtering. Returns items that pass all filters."""
```

Move the intent filtering loop from `_retrieve_core()`. This includes: focus_task_decision, focus_planning, focus_architecture, status hints, constraints_lookup, debug_history, conflict_review, rollout_status, reflection filtering.

- [ ] **Step 7: Extract `_score_items()` — UNIFIED for both paths**

```python
def _score_items(
    self,
    items: list[dict],
    plan: RetrievalPlan,
    profile_data: dict[str, Any],
    graph_entities: set[str],
) -> list[dict]:
    """Apply unified scoring formula to candidate items."""
```

This is the key unification step. The scoring factors are:
- Recency signal (half-life decay)
- Type boost (semantic/episodic/reflection weights)
- Stability boost (high/medium/low)
- Graph entity boost
- Profile adjustments (resolved conflicts, stale, superseded)
- Reflection penalty

Both the BM25 path and mem0 path should call this with the same formula. Extract the scoring logic from `_retrieve_core` and verify that the BM25 path's scoring (currently inline in `_source_from_bm25`) matches or is reconciled.

- [ ] **Step 8: Extract `_rerank_items()`**

```python
def _rerank_items(self, query: str, items: list[dict]) -> list[dict]:
    """Apply cross-encoder reranking if enabled."""
```

Includes the enabled/shadow/disabled mode logic.

- [ ] **Step 9: Extract `_build_result_stats()`**

```python
def _build_result_stats(
    self, items: list[dict], source_stats: dict,
) -> dict[str, Any]:
    """Build count and type statistics for the result set."""
```

- [ ] **Step 10: Rewrite `retrieve()` as a dispatcher**

The new `retrieve()` should be ~50-60 lines:
```python
def retrieve(self, query, top_k=10, ...):
    plan = self._planner.plan(query, ...)
    augmented_query, graph_entities = self._augment_query_with_graph(query)
    profile_data = self._load_profile_scoring_data()

    if mem0_disabled:
        candidates = self._source_from_bm25(query, augmented_query, plan, top_k, graph_entities)
    else:
        candidates, source_stats = self._source_from_mem0(query, plan, candidate_k)
        # optional: inject rollout status record
        candidates = self._inject_rollout_status(candidates, plan)

    filtered = self._filter_items(candidates, plan, reflection_enabled=...)
    scored = self._score_items(filtered, plan, profile_data, graph_entities)
    reranked = self._rerank_items(query, scored)
    final = reranked[:max(1, top_k)]

    # Shadow mode comparison (if enabled)
    ...

    return final
```

Delete `_retrieve_core`.

- [ ] **Step 11: Add tests for pipeline stages**

Add to `tests/test_retriever.py`:
- `test_augment_query_with_graph` — expands with entity names
- `test_augment_query_no_graph` — returns original when graph disabled
- `test_filter_items_focus_task` — filters by task intent
- `test_filter_items_reflection_disabled` — filters out reflections
- `test_score_items_recency_boost` — recent items score higher
- `test_score_items_type_boost` — semantic scores higher than episodic
- `test_score_items_unified` — BM25 and mem0 candidates scored identically
- `test_rerank_items_enabled` — cross-encoder called
- `test_rerank_items_disabled` — passthrough

- [ ] **Step 12: Run tests and lint**

```bash
cd /home/carlos/nanobot-store-refinement && make lint && make typecheck && pytest tests/ -x -q
```

- [ ] **Step 13: Commit**

```bash
cd /home/carlos/nanobot-store-refinement && git add -A && git commit -m "refactor(retriever): unify BM25/mem0 scoring pipeline, break up _retrieve_core"
```

---

### Task 4: Eliminate `_store` from `conflicts.py`

**Files:**
- Modify: `nanobot/agent/memory/conflicts.py`
- Modify: `nanobot/agent/memory/store.py`

- [ ] **Step 1: Read `conflicts.py` to find all `_store` usages**

Search for `self._store` and `store.` — there should be exactly 3 ingester method calls in `resolve_conflict()` (around lines 386, 396-407):
- `store.ingester._sanitize_mem0_text(new_value, allow_archival=False)`
- `store.ingester._normalize_memory_metadata({...}, event_type=..., summary=..., source=...)`
- `store.ingester._sanitize_mem0_metadata(conflict_metadata)`

- [ ] **Step 2: Add callable parameters to `ConflictManager.__init__`**

Add keyword-only parameters:
```python
def __init__(
    self,
    profile_mgr: ProfileManager,
    mem0: _Mem0Adapter,
    *,
    sanitize_mem0_text_fn: Callable[..., str] | None = None,
    normalize_metadata_fn: Callable[..., tuple[dict, bool]] | None = None,
    sanitize_metadata_fn: Callable[[dict], dict] | None = None,
) -> None:
```

Store as `self._sanitize_mem0_text`, `self._normalize_metadata`, `self._sanitize_metadata`.

- [ ] **Step 3: Update `resolve_conflict()` to use the callables**

Replace `store.ingester._sanitize_mem0_text(...)` with `self._sanitize_mem0_text(...)`, etc.

- [ ] **Step 4: Remove `self._store` attribute and `self._store: Any = None`**

- [ ] **Step 5: Update `MemoryStore.__init__` wiring**

Wire the callables:
```python
self.conflict_mgr = ConflictManager(
    self.profile_mgr,
    self.mem0,
    sanitize_mem0_text_fn=self.ingester._sanitize_mem0_text,
    normalize_metadata_fn=self.ingester._normalize_memory_metadata,
    sanitize_metadata_fn=EventIngester._sanitize_mem0_metadata,
)
```

Remove `self.conflict_mgr._store = self`.

- [ ] **Step 6: Run tests and lint**

```bash
cd /home/carlos/nanobot-store-refinement && make lint && make typecheck && pytest tests/ -x -q
```

- [ ] **Step 7: Commit**

```bash
cd /home/carlos/nanobot-store-refinement && git add -A && git commit -m "refactor(conflicts): replace _store back-reference with callable injection"
```

---

### Task 5: Eliminate `_store` from `profile.py`

**Files:**
- Modify: `nanobot/agent/memory/profile.py`
- Modify: `nanobot/agent/memory/store.py`

- [ ] **Step 1: Read `profile.py` to find all `_store` usages**

In `apply_live_user_correction()` (lines 803-978), there are 10 `store.` accesses:
- `store.extractor.extract_explicit_preference_corrections(text)` (line 807)
- `store.extractor.extract_explicit_fact_corrections(text)` (line 808)
- `store.ingester._coerce_event(...)` (line 894)
- `store.ingester.append_events(events)` (line 937)
- `store.conflict_mgr.auto_resolve_conflicts(max_items=10)` (line 942)
- `store.conflict_mgr.ask_user_for_conflict()` (line 945)
- `store.ingester._normalize_memory_metadata(...)` (line 948)
- `store.ingester._sanitize_mem0_text(...)` (line 962)
- `store.ingester._sanitize_mem0_metadata(...)` (line 963)
- `store.snapshot.rebuild_memory_snapshot(write=False)` (line 971)

- [ ] **Step 2: Add subsystem object parameters to `ProfileManager.__init__`**

Add keyword-only parameters for the 4 subsystem objects:
```python
def __init__(
    self,
    persistence: MemoryPersistence,
    profile_file: Path,
    mem0: _Mem0Adapter,
    *,
    extractor: Any | None = None,
    ingester: Any | None = None,
    conflict_mgr: Any | None = None,
    snapshot: Any | None = None,
) -> None:
```

Use `Any` for type hints (with `TYPE_CHECKING` imports if desired) to avoid circular imports.

Store as `self._extractor`, `self._ingester`, `self._conflict_mgr`, `self._snapshot`.

- [ ] **Step 3: Update `apply_live_user_correction()` to use injected objects**

Replace all `store.extractor.X(...)` with `self._extractor.X(...)`, etc.

Remove `store = self._store` and `self._store: Any = None`.

- [ ] **Step 4: Update `MemoryStore.__init__` wiring**

Wire the subsystems after they are all constructed:
```python
self.profile_mgr = ProfileManager(
    self.persistence, self.persistence.profile_file, self.mem0,
)
# ... construct other subsystems ...
# Wire profile_mgr subsystem dependencies (must happen after all are built)
self.profile_mgr._extractor = self.extractor
self.profile_mgr._ingester = self.ingester
self.profile_mgr._conflict_mgr = self.conflict_mgr
self.profile_mgr._snapshot = self.snapshot
```

Remove `self.profile_mgr._store = self`.

Note: The wiring order matters — `profile_mgr` is constructed before `conflict_mgr` and `snapshot`, so the subsystem references must be set after all are built. This is the same pattern already used for `_store`, just more explicit.

- [ ] **Step 5: Run tests and lint**

```bash
cd /home/carlos/nanobot-store-refinement && make lint && make typecheck && pytest tests/ -x -q
```

- [ ] **Step 6: Commit**

```bash
cd /home/carlos/nanobot-store-refinement && git add -A && git commit -m "refactor(profile): replace _store back-reference with subsystem injection"
```

---

### Task 6: Fix `eval.py` helper duplication

**Files:**
- Modify: `nanobot/agent/memory/eval.py`

- [ ] **Step 1: Find duplicated helpers**

Search `eval.py` for `_utc_now_iso` and `_safe_float` defined locally.

- [ ] **Step 2: Replace with imports**

Remove the local definitions. Add:
```python
from .helpers import _safe_float, _utc_now_iso
```

If they were staticmethods, update call sites from `self._utc_now_iso()` to `_utc_now_iso()`.

- [ ] **Step 3: Run tests and lint**

```bash
cd /home/carlos/nanobot-store-refinement && make lint && make typecheck && pytest tests/ -x -q
```

- [ ] **Step 4: Commit**

```bash
cd /home/carlos/nanobot-store-refinement && git add -A && git commit -m "fix(eval): import helpers instead of duplicating _utc_now_iso and _safe_float"
```

---

### Task 7: Final validation and cleanup

**Files:**
- Modify: `nanobot/agent/memory/store.py` — update docstring
- Modify: `nanobot/agent/memory/__init__.py` — verify exports

- [ ] **Step 1: Verify `store.py` line count**

```bash
wc -l nanobot/agent/memory/store.py
```
Expected: ~376 lines

- [ ] **Step 2: Verify no `_store` back-references remain**

```bash
grep -rn "_store" nanobot/agent/memory/profile.py nanobot/agent/memory/conflicts.py
```
Expected: no matches

- [ ] **Step 3: Update `store.py` docstring**

Replace with facade description noting that consolidation is now also extracted.

- [ ] **Step 4: Run `make check`**

```bash
cd /home/carlos/nanobot-store-refinement && make check
```
Expected: All pass

- [ ] **Step 5: Commit**

```bash
cd /home/carlos/nanobot-store-refinement && git add -A && git commit -m "refactor(memory): finalize store.py as pure facade, verify module independence"
```

- [ ] **Step 6: Commit spec and plan docs**

```bash
cd /home/carlos/nanobot-store-refinement && git add docs/superpowers/specs/2026-03-22-store-refinement-design.md docs/superpowers/plans/2026-03-22-store-refinement.md && git commit -m "docs: add store refinement spec and plan"
```
