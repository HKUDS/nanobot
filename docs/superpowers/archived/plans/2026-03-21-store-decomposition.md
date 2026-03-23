# MemoryStore Decomposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decompose `nanobot/agent/memory/store.py` (3028 lines) into 6 focused modules, remove 48 thin wrappers, and leave `MemoryStore` as a ~550-line facade.

**Architecture:** Extract each responsibility cluster into its own module (`helpers.py`, `rollout.py`, `ingester.py`, `retriever.py`, `maintenance.py`, `snapshot.py`). `MemoryStore` becomes a facade that composes these modules and keeps only `consolidate()` + `get_memory_context()` as cross-cutting coordination methods. Thin wrappers are removed and callers migrated to use subsystem objects directly.

**Tech Stack:** Python 3.10+, pytest, pytest-asyncio, ruff, mypy

**Worktree:** `/home/carlos/nanobot-store-decomposition` (branch `refactor/store-decomposition`)

**Spec:** `docs/superpowers/specs/2026-03-21-store-decomposition-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `nanobot/agent/memory/helpers.py` | Shared static utilities (deduplicating from store, profile, conflicts, assembler) |
| Create | `nanobot/agent/memory/rollout.py` | `RolloutConfig` — feature flag management |
| Create | `nanobot/agent/memory/ingester.py` | `EventIngester` — full event write path |
| Create | `nanobot/agent/memory/retriever.py` | `MemoryRetriever` — full retrieval read path |
| Create | `nanobot/agent/memory/maintenance.py` | `MemoryMaintenance` — reindex, seed, health |
| Create | `nanobot/agent/memory/snapshot.py` | `MemorySnapshot` — rebuild, verify |
| Create | `tests/test_rollout_config.py` | Unit tests for RolloutConfig |
| Create | `tests/test_ingester.py` | Unit tests for EventIngester |
| Create | `tests/test_retriever.py` | Unit tests for MemoryRetriever |
| Create | `tests/test_maintenance.py` | Unit tests for MemoryMaintenance |
| Create | `tests/test_snapshot.py` | Unit tests for MemorySnapshot |
| Create | `tests/test_memory_helpers.py` | Unit tests for shared helpers |
| Modify | `nanobot/agent/memory/store.py` | Remove extracted code, wire subsystems, remove wrappers |
| Modify | `nanobot/agent/memory/__init__.py` | Add new module exports |
| Modify | `nanobot/agent/memory/profile.py` | Import helpers from `helpers.py` |
| Modify | `nanobot/agent/memory/conflicts.py` | Import helpers from `helpers.py` |
| Modify | `nanobot/agent/memory/context_assembler.py` | Import helpers from `helpers.py` |
| Modify | `nanobot/cli/commands.py` | Migrate ~15 wrapper calls to subsystem objects |
| Modify | `nanobot/agent/loop.py` | Migrate ~3 wrapper calls |
| Modify | `nanobot/agent/verifier.py` | Migrate ~1 wrapper call |
| Modify | 5 existing test files | Migrate to new API |

---

### Task 1: Extract `helpers.py` — Shared Utilities

**Files:**
- Create: `nanobot/agent/memory/helpers.py`
- Create: `tests/test_memory_helpers.py`
- Modify: `nanobot/agent/memory/store.py` — remove extracted methods, import from helpers
- Modify: `nanobot/agent/memory/profile.py` — replace duplicates with imports
- Modify: `nanobot/agent/memory/conflicts.py` — replace duplicates with imports
- Modify: `nanobot/agent/memory/context_assembler.py` — replace duplicates with imports

- [ ] **Step 1: Identify all duplicated utility functions**

Read `store.py` and identify these static/classmethod utilities:
- `_utc_now_iso` (line 197)
- `_safe_float` (line 201)
- `_norm_text` (line 208)
- `_tokenize` (line 212)
- `_GRAPH_QUERY_STOPWORDS` (line 216 — 97-line set)
- `_extract_query_keywords` (line 315)
- `_to_str_list` (line 321)
- `_to_datetime` (line 331)
- `_estimate_tokens` (line 340)
- `_contains_any` (line 513)

Then grep `profile.py`, `conflicts.py`, `context_assembler.py` for any of these that are duplicated.

- [ ] **Step 2: Create `helpers.py` with all shared utilities**

Move the canonical implementations to `helpers.py`. Each function should be a module-level function (not a classmethod/staticmethod). Include the `_GRAPH_QUERY_STOPWORDS` set.

- [ ] **Step 3: Write tests for helpers**

Create `tests/test_memory_helpers.py` with focused tests for each utility:
- `_utc_now_iso` returns ISO format string
- `_safe_float` handles None, invalid strings, normal floats
- `_norm_text` normalizes whitespace
- `_tokenize` splits and lowercases
- `_to_str_list` handles None, string, list inputs
- `_to_datetime` handles ISO strings, None, invalid
- `_estimate_tokens` approximates token count
- `_contains_any` checks substring presence

- [ ] **Step 4: Update importers**

In `store.py`, `profile.py`, `conflicts.py`, `context_assembler.py`:
- Replace local definitions/duplicates with `from .helpers import ...`
- Remove the now-redundant method definitions
- Keep thin wrappers on `MemoryStore` that delegate to these (they'll be removed in Task 7)

- [ ] **Step 5: Run tests and lint**

Run: `cd /home/carlos/nanobot-store-decomposition && make lint && make typecheck && pytest tests/ -x -q`

- [ ] **Step 6: Commit**

```bash
cd /home/carlos/nanobot-store-decomposition && git add -A && git commit -m "refactor(memory): extract shared utilities to helpers.py"
```

---

### Task 2: Extract `rollout.py` — `RolloutConfig`

**Files:**
- Create: `nanobot/agent/memory/rollout.py`
- Create: `tests/test_rollout_config.py`
- Modify: `nanobot/agent/memory/store.py` — remove rollout methods, wire `RolloutConfig`

- [ ] **Step 1: Identify rollout methods in store.py**

Extract these methods (lines 346-511):
- `_load_rollout_config` → becomes `RolloutConfig.__init__` / `RolloutConfig.load()`
- `_apply_rollout_overrides` → becomes `RolloutConfig.apply_overrides()`
- `get_rollout_status` → becomes `RolloutConfig.get_status()`
- `ROLLOUT_MODES` class variable → becomes `RolloutConfig.ROLLOUT_MODES`

- [ ] **Step 2: Create `rollout.py` with `RolloutConfig` class**

The class should:
- Accept `overrides: dict` and `mem0_enabled: bool` in `__init__`
- Build the rollout dict in `load()` (called from `__init__`)
- Expose `self.rollout` as a property (the live dict)
- Move validation logic from `_load_rollout_config` and `_apply_rollout_overrides`

- [ ] **Step 3: Write tests**

Create `tests/test_rollout_config.py`:
- `test_default_values` — verify defaults when no overrides
- `test_apply_overrides` — verify overrides merge correctly
- `test_get_status` — verify status dict structure
- `test_invalid_mode_rejected` — verify validation
- `test_mem0_disabled_sets_mode` — verify mem0_enabled=False forces mode

- [ ] **Step 4: Wire into `MemoryStore.__init__`**

Replace:
```python
self.rollout = self._load_rollout_config()
if isinstance(rollout_overrides, dict):
    self._apply_rollout_overrides(rollout_overrides)
```

With:
```python
self.rollout_config = RolloutConfig(
    overrides=rollout_overrides or {},
    mem0_enabled=True,  # adjusted after mem0 init
)
self.rollout = self.rollout_config.rollout  # backward compat alias
```

Remove the three methods from `MemoryStore`. Update all `self.rollout` reads to work with the dict (they already do — `self.rollout` stays as a dict reference).

- [ ] **Step 5: Run tests and lint**

Run: `cd /home/carlos/nanobot-store-decomposition && make lint && make typecheck && pytest tests/ -x -q`

- [ ] **Step 6: Commit**

```bash
cd /home/carlos/nanobot-store-decomposition && git add -A && git commit -m "refactor(memory): extract RolloutConfig from MemoryStore"
```

---

### Task 3: Extract `ingester.py` — `EventIngester`

**Files:**
- Create: `nanobot/agent/memory/ingester.py`
- Create: `tests/test_ingester.py`
- Modify: `nanobot/agent/memory/store.py` — remove ~745 lines, wire `EventIngester`

This is the largest extraction. The implementer should read the full source carefully.

- [ ] **Step 1: Identify all ingestion methods in store.py**

Methods to extract (organized by pipeline stage):

**Event coercion & ID building** (lines 1691-1788):
- `_build_event_id`, `_infer_episodic_status`, `_coerce_event`

**Classification & metadata** (lines 552-787):
- `_default_topic_for_event_type`, `_classify_memory_type`, `_distill_semantic_summary`
- `_normalize_memory_metadata`, `_event_mem0_write_plan`
- `_looks_blob_like_summary`, `_sanitize_mem0_metadata`, `_sanitize_mem0_text`

**Dedup & merge** (lines 1191-1601):
- `read_events`, `_merge_source_span`, `_ensure_event_provenance`
- `_event_similarity`, `_find_semantic_duplicate`, `_find_semantic_supersession`
- `_merge_events`, `append_events`, `_ingest_graph_triples`

**Mem0 sync** (lines 2843-2868):
- `_sync_events_to_mem0`

- [ ] **Step 2: Create `ingester.py` with `EventIngester` class**

Constructor takes: `persistence`, `mem0`, `graph`, `rollout_config` (the `RolloutConfig` from Task 2).

Move all methods listed above. Replace `self.rollout` reads with `self._rollout.rollout`. Import shared helpers from `helpers.py`.

Class constants needed: `EVENT_TYPES`, `MEMORY_TYPES`, `MEMORY_STABILITY`, `EPISODIC_STATUS_OPEN`, `EPISODIC_STATUS_RESOLVED`.

**Critical:** `_coerce_event` is also used by `MemoryExtractor.__init__` (passed as a callable). After extraction, `MemoryStore.__init__` must pass `self.ingester._coerce_event` to `MemoryExtractor`.

**Critical:** `profile.py` calls `store.append_events()` and `store.rebuild_memory_snapshot()` via `self._store`. After extraction, these calls should go through `self._store.ingester.append_events()`. This is addressed in Task 7 (wrapper removal).

- [ ] **Step 3: Write tests**

Create `tests/test_ingester.py`:
- `test_coerce_event_valid` — valid event passes through
- `test_coerce_event_invalid_type` — rejected
- `test_classify_memory_type_semantic` — fact/preference → semantic
- `test_classify_memory_type_episodic` — task/decision → episodic
- `test_find_semantic_duplicate` — high similarity detected
- `test_find_no_duplicate` — different events not matched
- `test_merge_events` — merged event has unioned entities, averaged confidence
- `test_append_events_dedup` — duplicate merged on append
- `test_append_events_supersession` — contradicting event supersedes
- `test_sanitize_mem0_text` — strips runtime context, enforces length
- `test_read_events_caching` — mtime cache works

Use `tmp_path` for workspace, mock `mem0` and `graph`.

- [ ] **Step 4: Wire into `MemoryStore.__init__`**

```python
self.ingester = EventIngester(
    persistence=self.persistence,
    mem0=self.mem0,
    graph=self.graph,
    rollout_config=self.rollout_config,
)
```

Update `MemoryExtractor` construction to use `self.ingester._coerce_event`.

Add temporary backward-compat aliases:
```python
# Temporary — remove in Task 7
append_events = property(lambda self: self.ingester.append_events)
read_events = property(lambda self: self.ingester.read_events)
```

- [ ] **Step 5: Run tests and lint**

Run: `cd /home/carlos/nanobot-store-decomposition && make lint && make typecheck && pytest tests/ -x -q`

- [ ] **Step 6: Commit**

```bash
cd /home/carlos/nanobot-store-decomposition && git add -A && git commit -m "refactor(memory): extract EventIngester from MemoryStore (~745 lines)"
```

---

### Task 4: Extract `retriever.py` — `MemoryRetriever`

**Files:**
- Create: `nanobot/agent/memory/retriever.py`
- Create: `tests/test_retriever.py`
- Modify: `nanobot/agent/memory/store.py` — remove ~660 lines, wire `MemoryRetriever`

- [ ] **Step 1: Identify all retrieval methods in store.py**

Methods to extract:

**Core retrieval** (lines 1790-2349):
- `retrieve` (174 lines — the public entry point with mem0-enabled/disabled branches)
- `_retrieve_core` (385 lines — the mem0 retrieval pipeline)

**Graph context** (lines 2355-2457):
- `_build_entity_index`, `_extract_query_entities`, `_build_graph_context_lines`

- [ ] **Step 2: Create `retriever.py` with `MemoryRetriever` class**

Constructor takes: `mem0`, `graph`, `planner` (RetrievalPlanner), `reranker`, `profile_mgr` (ProfileManager), `rollout_config`, `read_events_fn` (callable), `extractor` (optional, for entity extraction).

Move all methods listed above. Key dependencies within `_retrieve_core`:
- `self._planner.plan(query)` → passed as constructor arg
- `self.mem0.search(...)` → passed as constructor arg
- `self._reranker.rerank(...)` → passed as constructor arg
- `self.profile_mgr.read_profile()` and `self.profile_mgr._meta_section(...)` → passed as constructor arg
- `_local_retrieve(...)` and `_topic_fallback_retrieve(...)` → import from `retrieval.py`
- `self.extractor._extract_entities(...)` → passed as constructor arg (optional)
- `self.read_events()` → passed as `read_events_fn` callable

**Critical:** `self.retriever` currently holds `_Mem0RuntimeInfo()` (dead code). Remove that assignment and replace with the new `MemoryRetriever`.

**Critical:** `ContextAssembler.__init__` receives `retrieve_fn=lambda *a, **kw: self.retrieve(*a, **kw)`. After extraction, this should become `retrieve_fn=lambda *a, **kw: self.retriever.retrieve(*a, **kw)`.

- [ ] **Step 3: Write tests**

Create `tests/test_retriever.py`:
- `test_retrieve_mem0_disabled` — uses local BM25 path
- `test_retrieve_mem0_enabled` — calls _retrieve_core
- `test_retrieve_core_empty_results` — empty mem0 returns empty
- `test_retrieve_core_with_graph_augmentation` — graph terms expand query
- `test_retrieve_core_reranking` — reranker is called when enabled
- `test_retrieve_core_type_boost` — semantic/episodic type boosts applied
- `test_retrieve_core_profile_adjustments` — resolved conflicts adjust scores
- `test_build_graph_context_lines` — graph context formatting

Use mocked `mem0`, `graph`, `planner`, `reranker`, `profile_mgr`.

- [ ] **Step 4: Wire into `MemoryStore.__init__`**

```python
self.retriever = MemoryRetriever(
    mem0=self.mem0,
    graph=self.graph,
    planner=self._planner,
    reranker=self._reranker,
    profile_mgr=self.profile_mgr,
    rollout_config=self.rollout_config,
    read_events_fn=self.ingester.read_events,
    extractor=self.extractor,
)
```

Update `ContextAssembler` to use `self.retriever.retrieve`.

Add temporary backward-compat alias:
```python
# Temporary — remove in Task 7
retrieve = property(lambda self: self.retriever.retrieve)
```

- [ ] **Step 5: Run tests and lint**

Run: `cd /home/carlos/nanobot-store-decomposition && make lint && make typecheck && pytest tests/ -x -q`

- [ ] **Step 6: Commit**

```bash
cd /home/carlos/nanobot-store-decomposition && git add -A && git commit -m "refactor(memory): extract MemoryRetriever from MemoryStore (~660 lines)"
```

---

### Task 5: Extract `maintenance.py` — `MemoryMaintenance`

**Files:**
- Create: `nanobot/agent/memory/maintenance.py`
- Create: `tests/test_maintenance.py`
- Modify: `nanobot/agent/memory/store.py` — remove ~324 lines, wire `MemoryMaintenance`

- [ ] **Step 1: Identify all maintenance methods in store.py**

**Reindex/Seed** (lines 874-1113):
- `_event_compaction_key`, `_compact_events_for_reindex`
- `reindex_from_structured_memory` (147 lines)
- `seed_structured_corpus` (48 lines)

**Mem0/Vector infrastructure** (lines 789-872, 1115-1141):
- `_mem0_get_all_rows`, `_vector_points_count`, `_history_row_count`
- `_backend_stats_for_eval`, `ensure_health`, `_ensure_vector_health`

Also move the TTL cache attributes: `_vector_count_cache`, `_history_count_cache`, `_COUNT_CACHE_TTL`.

- [ ] **Step 2: Create `maintenance.py` with `MemoryMaintenance` class**

Constructor takes: `mem0`, `persistence`, `rollout_config`.

- [ ] **Step 3: Write tests**

Create `tests/test_maintenance.py`:
- `test_vector_points_count` — returns count from mem0
- `test_history_row_count` — returns count from sqlite
- `test_ensure_health_calls_vector_check` — async health check
- `test_reindex_clears_and_rebuilds` — full reindex flow
- `test_compact_events` — deduplication during compaction
- `test_seed_structured_corpus` — seed with sample data

- [ ] **Step 4: Wire into `MemoryStore.__init__`**

```python
self.maintenance = MemoryMaintenance(
    mem0=self.mem0,
    persistence=self.persistence,
    rollout_config=self.rollout_config,
)
```

Add temporary backward-compat aliases for `reindex_from_structured_memory`, `seed_structured_corpus`, `ensure_health`.

- [ ] **Step 5: Run tests, lint, commit**

```bash
cd /home/carlos/nanobot-store-decomposition && make lint && make typecheck && pytest tests/ -x -q
git add -A && git commit -m "refactor(memory): extract MemoryMaintenance from MemoryStore (~324 lines)"
```

---

### Task 6: Extract `snapshot.py` — `MemorySnapshot`

**Files:**
- Create: `nanobot/agent/memory/snapshot.py`
- Create: `tests/test_snapshot.py`
- Modify: `nanobot/agent/memory/store.py` — remove ~103 lines, wire `MemorySnapshot`

- [ ] **Step 1: Identify snapshot methods in store.py**

**Snapshot & Verification** (lines 2632-2741):
- `rebuild_memory_snapshot` (34 lines)
- `verify_memory` (68 lines)

Note: `verify_beliefs` is a ProfileManager wrapper — it stays on profile_mgr.

- [ ] **Step 2: Create `snapshot.py` with `MemorySnapshot` class**

Constructor takes: `profile_mgr`, `persistence`, `read_events_fn`, `assembler`.

`rebuild_memory_snapshot` needs: `profile_mgr.read_profile()`, `read_events_fn()`, `assembler._profile_section_lines()`, `assembler._recent_unresolved()`, `persistence.read_text()`, `persistence.write_text()`.

`verify_memory` needs: `profile_mgr.read_profile()`, `profile_mgr._meta_section()`, `profile_mgr.verify_beliefs()`, `read_events_fn()`, helpers (`_to_datetime`, `_to_str_list`), class constants (`PROFILE_KEYS`, status constants).

Move the class constants needed by `verify_memory` to `snapshot.py` or import from a shared location.

- [ ] **Step 3: Write tests**

Create `tests/test_snapshot.py`:
- `test_rebuild_writes_memory_md` — snapshot produces MEMORY.md content
- `test_rebuild_empty_profile` — handles empty profile gracefully
- `test_verify_detects_stale_items` — items older than threshold flagged
- `test_verify_detects_missing_meta` — items without metadata flagged
- `test_verify_reports_event_stats` — event counts in report

- [ ] **Step 4: Wire into `MemoryStore.__init__`**

```python
self.snapshot = MemorySnapshot(
    profile_mgr=self.profile_mgr,
    persistence=self.persistence,
    read_events_fn=self.ingester.read_events,
    assembler=self._assembler,
)
```

Add temporary backward-compat aliases for `rebuild_memory_snapshot`, `verify_memory`.

- [ ] **Step 5: Run tests, lint, commit**

```bash
cd /home/carlos/nanobot-store-decomposition && make lint && make typecheck && pytest tests/ -x -q
git add -A && git commit -m "refactor(memory): extract MemorySnapshot from MemoryStore (~103 lines)"
```

---

### Task 7: Remove thin wrappers and migrate callers

**Files:**
- Modify: `nanobot/agent/memory/store.py` — delete ~348 lines of wrappers + temp aliases
- Modify: `nanobot/cli/commands.py` — migrate ~15 calls
- Modify: `nanobot/agent/loop.py` — migrate ~3 calls
- Modify: `nanobot/agent/verifier.py` — migrate ~1 call
- Modify: `nanobot/agent/memory/profile.py` — update `self._store` references
- Modify: `nanobot/agent/memory/conflicts.py` — update `self._store` references

- [ ] **Step 1: Inventory all external callers**

Search for all calls to wrapper methods on `MemoryStore` instances outside of `store.py`:

**cli/commands.py** (~15 calls):
- `store.verify_memory()` → `store.snapshot.verify()`
- `store.read_events()` → `store.ingester.read_events()`
- `store.rebuild_memory_snapshot(...)` → `store.snapshot.rebuild(...)`
- `store.reindex_from_structured_memory(...)` → `store.maintenance.reindex_from_structured_memory(...)`
- `store.list_conflicts(...)` → `store.conflict_mgr.list_conflicts(...)`
- `store.resolve_conflict_details(...)` → `store.conflict_mgr.resolve_conflict_details(...)`
- `store.set_item_pin(...)` → `store.profile_mgr.set_item_pin(...)`
- `store.mark_item_outdated(...)` → `store.profile_mgr.mark_item_outdated(...)`

**loop.py** (~3 calls):
- `memory_store.apply_live_user_correction(...)` → `memory_store.profile_mgr.apply_live_user_correction(...)`
- `self.context.memory.ensure_health()` → `self.context.memory.maintenance.ensure_health()`

**verifier.py** (~1 call):
- `self._memory.retrieve(...)` → `self._memory.retriever.retrieve(...)` (NOTE: `self._memory` here is a `MemoryStore` instance — check the type)

**profile.py** (internal, via `self._store`):
- `store.append_events(...)` → `store.ingester.append_events(...)`
- `store.rebuild_memory_snapshot(...)` → `store.snapshot.rebuild(...)`

**conflicts.py** (internal, via `self._store`):
- Uses `self.list_conflicts(...)`, `self.resolve_conflict_details(...)` — these are ConflictManager's own methods, not store wrappers. No change needed.

- [ ] **Step 2: Migrate external callers**

Update each file listed above. For each call:
1. Find the exact line
2. Replace `store.method(...)` with `store.subsystem.method(...)`
3. Verify the subsystem object is the correct one

- [ ] **Step 3: Rename `_eval` to `eval_runner` (public)**

In `MemoryStore.__init__`, rename `self._eval` to `self.eval_runner`. Update any callers.

- [ ] **Step 4: Delete all wrapper methods from `MemoryStore`**

Remove:
- 15 ProfileManager wrappers
- 10 ConflictManager wrappers
- 6 RetrievalPlanner wrappers (already internal-only after Task 4)
- 10 ContextAssembler wrappers (already internal-only after facade)
- 4 EvalRunner wrappers
- 3 Persistence wrappers
- All temporary backward-compat property aliases from Tasks 3-6

- [ ] **Step 5: Remove `_Mem0RuntimeInfo` assignment**

Delete `self.retriever = _Mem0RuntimeInfo()` (line 99) — now replaced by `MemoryRetriever`.

- [ ] **Step 6: Run tests and lint**

Run: `cd /home/carlos/nanobot-store-decomposition && make lint && make typecheck && pytest tests/ -x -q`

Expect some test failures in existing test files — these are addressed in Task 8.

- [ ] **Step 7: Commit (even if some tests fail — Task 8 fixes them)**

```bash
cd /home/carlos/nanobot-store-decomposition && git add -A && git commit -m "refactor(memory): remove thin wrappers, migrate callers to subsystem objects"
```

---

### Task 8: Migrate existing tests

**Files:**
- Modify: `tests/test_store_branches.py`
- Modify: `tests/test_store_helpers.py`
- Modify: `tests/test_memory_hybrid.py`
- Modify: `tests/test_memory_metadata_policy.py`
- Modify: `tests/test_memory_consolidation_types.py`
- Modify: `tests/test_memory_cli_commands.py` — `_FakeStore` must expose subsystem attributes
- Potentially modify: any other test files that call `MemoryStore` wrapper methods

- [ ] **Step 1: Run test suite and capture failures**

Run: `cd /home/carlos/nanobot-store-decomposition && pytest tests/ -x --tb=short 2>&1 | head -100`

Identify which tests fail and why (most will be `AttributeError: 'MemoryStore' object has no attribute 'X'`).

- [ ] **Step 2: Migrate each failing test file**

For each test file, apply these replacements systematically:
- `store.append_events(...)` → `store.ingester.append_events(...)`
- `store.read_events(...)` → `store.ingester.read_events(...)`
- `store.retrieve(...)` → `store.retriever.retrieve(...)`
- `store.reindex_from_structured_memory(...)` → `store.maintenance.reindex_from_structured_memory(...)`
- `store.seed_structured_corpus(...)` → `store.maintenance.seed_structured_corpus(...)`
- `store.verify_memory(...)` → `store.snapshot.verify(...)`
- `store.rebuild_memory_snapshot(...)` → `store.snapshot.rebuild(...)`
- `store.read_profile(...)` → `store.profile_mgr.read_profile(...)`
- `store.write_profile(...)` → `store.profile_mgr.write_profile(...)`
- `store.list_conflicts(...)` → `store.conflict_mgr.list_conflicts(...)`
- `store.resolve_conflict(...)` → `store.conflict_mgr.resolve_conflict(...)`
- `store.resolve_conflict_details(...)` → `store.conflict_mgr.resolve_conflict_details(...)`
- `store.auto_resolve_conflicts(...)` → `store.conflict_mgr.auto_resolve_conflicts(...)`
- `store.set_item_pin(...)` → `store.profile_mgr.set_item_pin(...)`
- `store.mark_item_outdated(...)` → `store.profile_mgr.mark_item_outdated(...)`
- `store.apply_live_user_correction(...)` → `store.profile_mgr.apply_live_user_correction(...)`
- `store.read_long_term(...)` → `store.persistence.read_text(...)`
- `store.write_long_term(...)` → `store.persistence.write_text(...)`
- `store.ensure_health()` → `store.maintenance.ensure_health()`
- `store.get_rollout_status()` → `store.rollout_config.get_status()`
- `store._eval.X(...)` → `store.eval_runner.X(...)`
- `store.get_observability_report(...)` → `store.eval_runner.get_observability_report(...)`
- `store.evaluate_retrieval_cases(...)` → `store.eval_runner.evaluate_retrieval_cases(...)`
- `store.save_evaluation_report(...)` → `store.eval_runner.save_evaluation_report(...)`
- `store.evaluate_rollout_gates(...)` → `store.eval_runner.evaluate_rollout_gates(...)`
- `store.get_memory_context(...)` — stays on `MemoryStore` (facade method)
- `store.consolidate(...)` — stays on `MemoryStore` (facade method)

Also check for MagicMock patches that reference removed methods (e.g., `patch.object(store, 'append_events', ...)`).

- [ ] **Step 3: Run tests iteratively**

After each file migration, run: `pytest tests/<file> -v`

Continue until all tests pass.

- [ ] **Step 4: Run full test suite**

Run: `cd /home/carlos/nanobot-store-decomposition && make check`

All tests must pass.

- [ ] **Step 5: Commit**

```bash
cd /home/carlos/nanobot-store-decomposition && git add -A && git commit -m "test(memory): migrate existing tests to new subsystem API"
```

---

### Task 9: Final cleanup and validation

**Files:**
- Modify: `nanobot/agent/memory/__init__.py` — add new module exports
- Modify: `nanobot/agent/memory/store.py` — final cleanup

- [ ] **Step 1: Update `__init__.py` exports**

Add to imports and `__all__`:
```python
from .helpers import ...  # only if any are part of public API
from .ingester import EventIngester
from .maintenance import MemoryMaintenance
from .retriever import MemoryRetriever
from .rollout import RolloutConfig
from .snapshot import MemorySnapshot
```

Add to `__all__`: `"EventIngester"`, `"MemoryRetriever"`, `"MemoryMaintenance"`, `"MemorySnapshot"`, `"RolloutConfig"`.

Remove `_Mem0RuntimeInfo` from exports if no longer used externally.

- [ ] **Step 2: Update `store.py` module docstring**

Update the docstring to reflect the new facade role:

```python
"""Memory store facade — coordinates subsystem modules.

``MemoryStore`` is a thin facade that composes focused subsystem modules:

- ``EventIngester`` — event write path (classify, dedup, merge, append)
- ``MemoryRetriever`` — retrieval read path (mem0, BM25, reranking)
- ``MemoryMaintenance`` — reindex, seed, health checks
- ``MemorySnapshot`` — rebuild and verify MEMORY.md
- ``RolloutConfig`` — feature flag management

Cross-cutting coordination (``consolidate``, ``get_memory_context``) stays
on ``MemoryStore``.  Callers access subsystems directly for specific
operations: ``store.ingester.append_events(...)``.
"""
```

- [ ] **Step 3: Verify `store.py` line count**

Run: `wc -l nanobot/agent/memory/store.py`
Expected: ~550 lines (down from 3028)

- [ ] **Step 4: Run `make check`**

Run: `cd /home/carlos/nanobot-store-decomposition && make check`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
cd /home/carlos/nanobot-store-decomposition && git add -A && git commit -m "refactor(memory): finalize store.py as facade, update exports and docs"
```

- [ ] **Step 6: Commit spec and plan**

```bash
cd /home/carlos/nanobot-store-decomposition && git add docs/superpowers/specs/2026-03-21-store-decomposition-design.md docs/superpowers/plans/2026-03-21-store-decomposition.md && git commit -m "docs: add store decomposition spec and plan"
```
