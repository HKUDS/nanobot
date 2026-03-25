# Memory Module Wiring Hardening

**Date:** 2026-03-25
**Topic:** Fix stale copies, eliminate post-construction wiring, harden shared mutable state in memory module
**Status:** Draft
**Related:** `2026-03-24-role-switch-propagation-design.md` (same class of bugs in agent/)

---

## Problem Statement

The memory module underwent the same monolith decomposition as the agent loop: a 4,487-LOC
`MemoryStore` was split into 34 files across 5 subdirectories. The decomposition introduced
three classes of wiring bugs — the same patterns found in the agent loop, plus one new one.

### Bug 1: Stale copy — `conflict_auto_resolve_gap`

`store.py:238-241`:
```python
self.conflict_auto_resolve_gap = float(
    self.rollout.get("conflict_auto_resolve_gap", 0.25)
)
self.conflict_mgr.conflict_auto_resolve_gap = self.conflict_auto_resolve_gap
```

A float is extracted from the rollout dict and copied to `ConflictManager`. If
`RolloutConfig.apply_overrides()` later changes the rollout dict, the conflict manager
keeps the stale value. This is identical to the `model`/`temperature` stale-copy bug
in the agent loop.

### Bug 2: Shared mutable dict without synchronization — `self.rollout`

`store.py:143`: `self.rollout = self._rollout_config.rollout`

This same dict reference is passed to 6 components: `MemoryMaintenance`, `EventIngester`,
`MemoryRetriever`, `EvalRunner`, and read at construction for `KnowledgeGraph` and
`Reranker` configuration. `RolloutConfig.apply_overrides()` mutates the dict key-by-key
in-place. If overrides are applied mid-operation (e.g., during a retrieval), one component
might see old flag values and another sees new ones.

This is the **inverse** of the agent loop bug: instead of stale copies, it's live shared
mutable state with no consistency guarantee.

**Note:** This is currently a **latent bug**, not an active one. `apply_overrides()` is
only called during `RolloutConfig.__init__()`, which runs synchronously inside
`MemoryStore.__init__()`. No runtime caller exists today. However, the in-place mutation
pattern is a trap — the next session that adds runtime rollout changes will hit
inconsistent reads without any test catching it. The fix is preventive hardening.

### Bug 3: Post-construction wiring — `ProfileStore`

`store.py:278-285`:
```python
self.profile_mgr._conflict_mgr = self.conflict_mgr
self.profile_mgr._corrector = _CorrectionOrchestrator(
    profile_store=self.profile_mgr,
    extractor=self.extractor,
    ingester=self.ingester,
    conflict_mgr=self.conflict_mgr,
    snapshot=self.snapshot,
)
```

`ProfileStore` is constructed at line 148 with `_conflict_mgr=None` and `_corrector=None`.
These fields are assigned 130 lines later at lines 278-285. Between those lines,
`profile_mgr` is already passed to other components (ingester, assembler). Methods
defensively null-check, but this is fragile — removing a guard silently breaks behavior.

Additionally, `MemoryMaintenance._reindex_fn` is post-wired at lines 177-182 via a
lambda assigned after construction.

### Why testing missed it

The existing test suites cover functional behavior (retrieval relevance, dedup, token
budgets, profile conflicts, factory wiring) but none test **construction wiring
correctness**: whether subsystems receive the right references, whether those references
stay in sync after mutation, or whether post-construction fields are non-None.

### Root cause

Same as the agent loop: when a monolith is decomposed, implicit internal state sharing
becomes explicit cross-component wiring. The decomposition extracted files and updated
imports but did not verify that runtime state contracts survived the extraction.

---

## Design

### Principle

**All component dependencies are satisfied at construction time. No post-construction
field assignment. Shared mutable state is replaced with atomic snapshots or live
callbacks.**

---

## Section 1: Replace `conflict_auto_resolve_gap` stale copy with live callback

**Current** (`store.py:238-241`): Float extracted from rollout, copied to conflict_mgr.

**After:** `ConflictManager` reads the value on demand via a callback:

```python
# In MemoryStore.__init__ (illustrative — existing params omitted for clarity):
self.conflict_mgr = ConflictManager(
    ...,  # existing params (profile_store, sanitize fns, db) unchanged
    resolve_gap_fn=lambda: float(
        self.rollout.get("conflict_auto_resolve_gap", 0.25)
    ),
)
```

**Changes to `ConflictManager`** (`write/conflicts.py`):
- Constructor gains `resolve_gap_fn: Callable[[], float]` parameter
- Remove `self.conflict_auto_resolve_gap` instance field
- Replace all reads of `self.conflict_auto_resolve_gap` with `self._resolve_gap_fn()`
- Existing constructor parameters (`profile_store`, `sanitize_mem0_text_fn`,
  `normalize_metadata_fn`, `sanitize_metadata_fn`, `db`) remain unchanged

**Changes to `MemoryStore`** (`store.py`):
- Remove `self.conflict_auto_resolve_gap` field (lines 238-241)
- Remove `self.conflict_mgr.conflict_auto_resolve_gap = ...` assignment (line 241)
- The `conflict_auto_resolve_gap` property on `MemoryStore` (if any external code reads
  it) becomes a computed property: `return float(self.rollout.get(...))`

---

## Section 2: Atomic rollout updates

**Current:** `RolloutConfig.apply_overrides()` mutates `self.rollout` dict in-place,
key by key. Components holding the same dict reference see mutations at different times.

**After:** Rollout updates replace the entire dict atomically:

**Changes to `RolloutConfig`** (`rollout.py`):
- `apply_overrides()` builds a new merged dict and replaces `self.rollout` in a single
  assignment:
  ```python
  def apply_overrides(self, overrides: dict[str, Any]) -> None:
      merged = {**self.rollout, **overrides}
      self._validate(merged)
      self.rollout = merged  # atomic replacement
  ```

**Changes to `MemoryStore`** (`store.py`):
- `self.rollout` becomes a read-only property that reads from `self._rollout_config.rollout`:
  ```python
  @property
  def rollout(self) -> dict[str, Any]:
      return self._rollout_config.rollout
  ```
- **Breaking change:** Any code that writes `store.rollout = {...}` will get
  `AttributeError`. This is intentional — mutations go through `_rollout_config`.
  A grep confirms no external code assigns to `store.rollout`; the only assignment
  is in `__init__` at line 143, which this change replaces.

**Changes to subsystem consumers** (ingester, retriever, maintenance):
- Hot-path components (retriever, ingester) capture a local reference at the start of
  each operation for within-operation consistency:
  ```python
  # In MemoryRetriever.retrieve():
  rollout = self._rollout_fn()  # snapshot for this operation
  if rollout.get("some_flag"): ...
  ```
- Constructor changes: instead of receiving `rollout=self.rollout` (a dict reference),
  receive `rollout_fn=lambda: self.rollout` (a callback that returns the current dict).
- Cold-path components (maintenance, eval) call the callback each time — always fresh.

**Synchronization contract:** Within a single `retrieve()` or `append_events()` call,
the rollout snapshot is consistent. Between calls, new overrides take effect.

---

## Section 3: Eliminate post-construction wiring

### 3a: ProfileStore — pass dependencies at construction

**Problem:** `ProfileStore` is constructed at line 148 with `_conflict_mgr=None` and
`_corrector=None`, then wired at lines 278-285.

**Root cause:** Three-way circular dependency:
- `_CorrectionOrchestrator` needs `profile_store` and `snapshot`
- `MemorySnapshot` needs `profile_mgr` (line 257)
- `ProfileStore` needs `_corrector`

This is a three-way cycle (`corrector → snapshot → profile_mgr → corrector`), not just
a two-way cycle. The original code resolved it with post-construction wiring — building
all three with None/incomplete references, then patching them afterward.

**Fix:** Break all three edges with lazy callbacks:

```python
# 1. Construct ProfileStore with lazy callbacks for conflict_mgr and corrector
self.profile_mgr = ProfileStore(
    db=self.db,
    conflict_mgr_fn=lambda: self.conflict_mgr,  # resolved at call time
    corrector_fn=lambda: self._corrector,        # resolved at call time
)

# 2. Construct ConflictManager with profile_mgr (now exists)
self.conflict_mgr = ConflictManager(
    self.profile_mgr,
    ...,  # existing sanitize fns, db
    resolve_gap_fn=lambda: float(self.rollout.get("conflict_auto_resolve_gap", 0.25)),
)

# 3. Construct MemorySnapshot with profile_mgr (now exists)
self.snapshot = MemorySnapshot(
    profile_mgr=self.profile_mgr,
    ...
)

# 4. Construct corrector with all deps available
self._corrector = _CorrectionOrchestrator(
    profile_store=self.profile_mgr,
    extractor=self.extractor,
    ingester=self.ingester,
    conflict_mgr=self.conflict_mgr,
    snapshot=self.snapshot,
)
```

The key insight: `ProfileStore` doesn't need `conflict_mgr` or `corrector` at
construction — it needs them at call time (when conflict/correction methods are invoked).
So `ProfileStore` receives two lazy callbacks that resolve after their targets are built.
By the time any conflict or correction method is called, both `self.conflict_mgr` and
`self._corrector` are fully constructed.

`ConflictManager`, `_CorrectionOrchestrator`, and `MemorySnapshot` all receive
`profile_mgr` directly (not as callbacks) because `profile_mgr` is constructed first.

**Changes to `ProfileStore`** (`persistence/profile_io.py`):
- Replace `_conflict_mgr: ... | None = None` with `conflict_mgr_fn: Callable[[], Any]`
- Replace `_corrector: ... | None = None` with `corrector_fn: Callable[[], Any]`
- Access conflict_mgr via `self._conflict_mgr_fn()` at call time
- Access corrector via `self._corrector_fn()` at call time
- Remove all defensive null-checks for these fields

**Changes to `_CorrectionOrchestrator`** (`persistence/profile_correction.py`):
- No signature change — it still receives `profile_store: ProfileStore` directly

**Construction order rewrite in `MemoryStore.__init__`:**

```
db → embedder → rollout_config
  → extractor
  → graph (needs: db)
  → ingester (needs: db, embedder, graph, rollout_fn)
  → profile_mgr (needs: db, conflict_mgr_fn*, corrector_fn*)
  → conflict_mgr (needs: profile_mgr, ingester sanitize fns, db, resolve_gap_fn)
  → assembler (needs: profile_mgr, ingester, db, embedder)
  → snapshot (needs: profile_mgr, assembler, ingester, db)
  → corrector (needs: profile_mgr, extractor, ingester, conflict_mgr, snapshot)
  → retriever (needs: db, embedder, graph, rollout_fn)
  → maintenance (needs: db, rollout_fn, reindex deps)
  → consolidation_pipeline (needs: all above)
```

*Two lazy callbacks on `ProfileStore`:
- `conflict_mgr_fn=lambda: self.conflict_mgr` — resolved when conflict methods are called
- `corrector_fn=lambda: self._corrector` — resolved when correction methods are called

Both are constructed immediately after `profile_mgr`, so the lazy references resolve
before any runtime call. All other dependencies are direct references, fully constructed
before use. No post-construction field assignment.

### 3b: MemoryMaintenance._reindex_fn — pass at construction

**Current** (`store.py:177-182`): Lambda assigned to `self.maintenance._reindex_fn` after
construction.

**Fix:** Pass the reindex dependencies at construction time:

```python
self.maintenance = MemoryMaintenance(
    db=self.db,
    rollout_fn=lambda: self.rollout,
    reindex_fn=lambda: self.maintenance.reindex_from_structured_memory(
        read_profile_fn=self.profile_mgr.read_profile,
        read_events_fn=self.ingester.read_events,
        ingester=self.ingester,
        profile_keys=self.PROFILE_KEYS,
    ),
)
```

**Issue:** `self.maintenance` doesn't exist yet when the lambda is defined (it references
`self.maintenance.reindex_from_structured_memory`). This is a self-reference in the
constructor.

**Resolution:** The lambda captures `self`, not `self.maintenance`. By the time the lambda
is called (at runtime, not construction time), `self.maintenance` exists. This is safe.
However, for clarity, restructure `MemoryMaintenance` so `reindex_from_structured_memory`
is a standalone function or accepts its dependencies as parameters, eliminating the
self-reference:

```python
self.maintenance = MemoryMaintenance(
    db=self.db,
    rollout_fn=lambda: self.rollout,
    reindex_deps=ReindexDeps(
        read_profile_fn=lambda: self.profile_mgr.read_profile(),
        read_events_fn=lambda **kw: self.ingester.read_events(**kw),
        ingester_ref=lambda: self.ingester,
        profile_keys=self.PROFILE_KEYS,
    ),
)
```

Where `ReindexDeps` is a simple dataclass holding the callbacks. `MemoryMaintenance`
calls them at reindex time.

---

## Section 4: Wiring contract tests

New file: `tests/contract/test_memory_wiring.py`

All tests use `MemoryStore(tmp_path, embedding_provider="hash")` — real components,
no API key needed.

| Test | Verifies |
|------|----------|
| `test_conflict_resolve_gap_follows_rollout` | Construct store, change rollout value, verify conflict_mgr reads new value via callback |
| `test_rollout_override_atomic_consistency` | Apply overrides, verify ingester and retriever see same rollout values within a single call |
| `test_rollout_override_does_not_mutate_snapshot` | Capture rollout dict before override, apply override, verify old dict is unchanged |
| `test_subsystem_rollout_fn_reflects_property_change` | Replace `_rollout_config.rollout`, verify ingester/retriever callbacks return the new dict |
| `test_profile_mgr_has_conflict_mgr_at_construction` | `store.profile_mgr._conflict_mgr is not None` immediately after `MemoryStore()` |
| `test_profile_mgr_corrector_fn_resolves` | `store.profile_mgr._corrector_fn()` returns a non-None `_CorrectionOrchestrator` instance |
| `test_maintenance_reindex_runs_without_error` | `store.maintenance.reindex(...)` completes without AttributeError |

These tests complement (not duplicate) the existing integration suite:
- `tests/integration/test_memory_retrieval_pipeline.py` — tests retrieval relevance
- `tests/integration/test_profile_conflicts.py` — tests conflict storage behavior
- `tests/contract/test_memory_wiring.py` — tests that construction wiring is correct

---

## Section 5: CLAUDE.md guardrail additions

Two new entries under **Prohibited Patterns > Wiring violations**:

**Post-construction field assignment:**
```markdown
- Assigning to another component's private fields after construction
  (e.g., `component._field = value` outside `__init__`). If a component
  needs a dependency, pass it at construction time. If a circular dependency
  prevents this, use a lazy callback (`lambda: self.dependency`) to break
  the cycle — never leave a field as None with defensive null-checks.
```

**Shared mutable collections:**
```markdown
- Sharing mutable collections (dicts, lists, sets) across multiple components
  without a documented synchronization strategy. Either pass immutable snapshots
  (replace atomically, not mutate in-place), or document the sharing contract
  with a comment at each receiver: `# shared-ref: <what>, <mutation contract>`.
```

---

## Section 6: Files changed

| File | Change |
|------|--------|
| `nanobot/memory/store.py` | Reorder `__init__` construction; replace rollout with property; remove post-construction wiring; pass conflict_mgr/corrector to ProfileStore at construction |
| `nanobot/memory/rollout.py` | `apply_overrides()` uses atomic dict replacement |
| `nanobot/memory/write/conflicts.py` | `ConflictManager` gains `resolve_gap_fn` callback; removes `conflict_auto_resolve_gap` field |
| `nanobot/memory/write/ingester.py` | Receive `rollout_fn` callback instead of dict reference |
| `nanobot/memory/read/retriever.py` | Receive `rollout_fn` callback; capture snapshot at start of `retrieve()` |
| `nanobot/memory/maintenance.py` | Receive `rollout_fn` and `reindex_deps` at construction; remove `_reindex_fn` post-wiring |
| `nanobot/memory/persistence/profile_io.py` | `ProfileStore.__init__` gains `conflict_mgr_fn` and `corrector_fn` lazy callbacks; remove null-checks |
| `nanobot/memory/persistence/profile_correction.py` | No signature change (receives `profile_store` directly) |
| `CLAUDE.md` | Add 2 new prohibited patterns |
| `tests/contract/test_memory_wiring.py` | New: 7 wiring contract tests |

## Section 7: What this does NOT change

- **File size decomposition** — ingester (918 LOC) and retriever (821 LOC) decomposition
  is a separate concern tracked in `project_problem11_memory_internals.md`.
- **ContextAssembler lambda closures** — capture `self`, follow reassignment correctly.
  No change needed.
- **UnifiedMemoryDB shared reference** — intentionally shared, all mutations expected.
- **Embedder selection** — set once, never changed. No stale-copy risk.
- **EvalRunner** — already uses `get_rollout_fn=lambda: self.rollout` callback pattern
  (`store.py:251`). After `self.rollout` becomes a property, the callback automatically
  returns the current value. No change needed.
- **ConsolidationPipeline** — receives subsystem object references (extractor, ingester,
  profile_mgr, conflict_mgr, snapshot) at `store.py:288-296`. These are all object
  references, not primitive copies — they follow the live instance. No stale-copy risk.
- **Existing integration tests** — `tests/integration/test_memory_*.py` test functional
  behavior. Our wiring tests are complementary, not replacing.

## Out of scope

- Adding rollout override mutation at runtime (no current caller does this outside of
  construction, but the atomic replacement makes it safe if needed in future).
- Replacing lambdas with Protocol types — lambdas are sufficient for breaking circular
  dependencies in the composition root.
- Thread safety — nanobot is single-threaded async. The atomic replacement prevents
  inconsistency within a single event loop tick, which is sufficient.
