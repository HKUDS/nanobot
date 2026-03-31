# Memory Phase 2: Lambda Callback Elimination — Implementation Record

> **Status:** Completed and merged (PR #104).
> **Date:** 2026-03-30.
> **Predecessor:** Phase 0 (#99), Phase 1 (#101).

**Goal:** Eliminate the remaining 12 lambda callbacks in `store.py` that were
used to break circular dependencies between subsystems.

**Architecture:** Three strategies applied in sequence: (1) delete dead code,
(2) post-construction wiring for genuine circular deps, (3) reorder
construction so dependencies exist before consumers.

**Outcome:** Lambda count in `store.py`: 12 → 0. Total across Phases 0-2: 23 → 0.

---

## Context

After Phase 0 eliminated 11 unnecessary wrapper lambdas and Phase 1 replaced
`UnifiedMemoryDB` with focused repositories, `store.py` still had 12 lambda
callbacks — all claimed to break genuine circular dependencies. Investigation
revealed:

- **3 were dead code** (stored but never called)
- **2 were genuine circular deps** (ProfileStore ↔ ConflictManager)
- **3 + 3 duplicates existed because ContextAssembler was constructed too early**
- **2 called private methods** on ContextAssembler from MemorySnapshot

## What Was Done

### Task 2.1: Remove Dead Callback Params from ProfileStore

**Commit:** `6995875`
**Files:** `persistence/profile_io.py`, `store.py`
**Change:** Removed `extractor`, `ingester_fn`, and `snapshot_fn` parameters
from `ProfileStore.__init__`. These were stored as attributes but never
accessed by any method. Removed corresponding lambda wrappers from `store.py`.

**Investigation that justified the change:**
```bash
grep -n "_ingester_fn\|_snapshot_fn\|_extractor" nanobot/memory/persistence/profile_io.py
```
Returned only the assignment lines — no usage anywhere in the class.

**Lambda reduction:** 12 → 9.

### Task 2.2: Replace ProfileStore Lambdas with Post-Construction Wiring

**Commit:** `078bdbf`
**Files:** `persistence/profile_io.py`, `store.py`, `tests/contract/test_memory_wiring.py`, `tests/test_profile_correction.py`

**Problem:** `ProfileStore` needs `ConflictManager` (for `_conflict_pair`,
`_apply_profile_updates`, `has_open_conflict`), but `ConflictManager` needs
`ProfileStore` in its constructor. Genuine circular dependency — cannot be
resolved by reordering.

**Solution:** Post-construction wiring. ProfileStore is constructed with
`db` only. After `ConflictManager` and `CorrectionOrchestrator` are built,
explicit setter methods wire them in:

```python
# store.py construction sequence:
self.profile_mgr = ProfileStore(db=self.db)
# ... (construct conflict_mgr, corrector) ...
self.profile_mgr.set_conflict_mgr(self.conflict_mgr)
self.profile_mgr.set_corrector(self._corrector)
```

**Why post-construction wiring, not a Mediator:** The assessment proposed
a Mediator pattern to break the ProfileStore ↔ ConflictManager cycle.
Investigation showed ConflictManager uses ~20 private methods on ProfileStore
— too deeply entangled for a clean Mediator extraction without a much larger
refactoring. Post-construction wiring is the pragmatic fix: explicit, testable,
and eliminates the lambda indirection.

**Contract test update:** `test_profile_mgr_has_conflict_mgr_at_construction`
changed from testing `_conflict_mgr_fn()` callable resolution to testing
`_conflict_mgr is store.conflict_mgr` identity.

**Lambda reduction:** 9 → 7.

### Task 2.3: Reorder ContextAssembler Construction

**Commit:** `0e665bd`
**Files:** `store.py`, `read/context_assembler.py`

**Problem:** ContextAssembler was constructed at line ~127, but its
dependencies (`retriever`, `ingester`, `_graph_aug`) weren't constructed
until lines ~170-195. Three lambda callbacks deferred the resolution.
A duplicate set of 3 lambdas existed in the `_ensure_assembler()` fallback.

**Solution:** Moved ContextAssembler construction to after all its
dependencies are built (~line 203). Replaced lambda callbacks with
Protocol-typed collaborator objects passed directly.

**ContextAssembler interface change:**

Before:
```python
ContextAssembler(
    retrieve_fn=lambda *a, **kw: self.retriever.retrieve(*a, **kw),
    read_events_fn=lambda **kw: self.ingester.read_events(**kw),
    build_graph_context_lines_fn=lambda *a, **kw: ...,
)
```

After:
```python
ContextAssembler(
    retriever=self.retriever,         # _Retriever Protocol
    event_reader=self.ingester,       # _EventReader Protocol
    graph_augmenter=self._graph_aug,  # _GraphAugmenter Protocol
)
```

Three Protocol classes (`_Retriever`, `_EventReader`, `_GraphAugmenter`)
defined in `context_assembler.py` provide structural typing. This preserves
test monkeypatching compatibility (method lookup at call time on the object,
not captured at construction).

**Deleted:** `_ensure_assembler()` method (~30 LOC) — existed only to support
test monkeypatching via `MemoryStore.__new__` bypass. No longer needed since
ContextAssembler construction is straightforward.

**Lambda reduction:** 7 → 0 (3 in `__init__` + 3 in `_ensure_assembler` + 1 `get_memory_context` indirection).

### Task 2.4: Replace MemorySnapshot Lambdas with Direct Bound Methods

**Commit:** `0e665bd` (same as Task 2.3)

**Problem:** MemorySnapshot received lambdas wrapping private ContextAssembler
methods (`_profile_section_lines`, `_recent_unresolved`).

**Solution:** After reordering (Task 2.3), ContextAssembler is constructed
before MemorySnapshot. Pass bound methods directly:

```python
self.snapshot = MemorySnapshot(
    profile_section_lines_fn=self._assembler._profile_section_lines,
    recent_unresolved_fn=self._assembler._recent_unresolved,
    ...
)
```

### Task 2.5: Fix Code Scanning Alerts

**Commit:** `1114fbb`
**Files:** `read/context_assembler.py`

**Problem:** GitHub code scanning flagged 3 "statement has no effect" alerts
on Protocol method stubs using `...` (Ellipsis) syntax.

**Solution:** Replaced `...` stubs with docstring bodies and concrete default
parameter values instead of `= ...`.

---

## Deviations from Assessment

| Assessment proposed | What we did | Why |
|---|---|---|
| Mediator pattern for ProfileStore ↔ ConflictManager | Post-construction wiring (`set_conflict_mgr()`) | ConflictManager uses ~20 private ProfileStore methods — too entangled for clean Mediator extraction |
| Split `profile_io.py` into `store.py` + `belief.py` | Deferred | The circular dep was resolved without splitting; file split is Phase 4 scope |
| Split `conflicts.py` into `conflict.py` + `resolution.py` | Deferred | Same — dep resolved without split |
| Builder pattern (Phase 3) | **Skipped entirely** | With 0 lambdas, `store.py` is 318 LOC with clean construction order — Builder would add ceremony without value |

## Files Changed

| File | Lines changed | What changed |
|------|--------------|-------------|
| `nanobot/memory/store.py` | -93 / +99 | Removed lambdas, reordered construction, deleted `_ensure_assembler()` |
| `nanobot/memory/persistence/profile_io.py` | -20 / +19 | Removed 5 callback params, added `set_conflict_mgr()`/`set_corrector()` |
| `nanobot/memory/read/context_assembler.py` | -16 / +45 | Replaced Callable params with Protocol-typed collaborators |
| `tests/contract/test_memory_wiring.py` | -10 / +9 | Updated wiring contract tests |
| `tests/test_profile_correction.py` | -1 / +1 | `_corrector_fn = lambda` → `set_corrector()` |

## Verification

- All 2222 unit tests pass
- `make pre-push` passes (lint + typecheck + coverage 86% + integration)
- Zero lambda callbacks in `store.py`
- Wiring contract tests verify post-construction dependencies resolve correctly
