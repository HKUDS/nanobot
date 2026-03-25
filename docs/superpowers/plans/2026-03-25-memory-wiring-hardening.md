# Memory Wiring Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix stale copies, eliminate post-construction wiring, and harden shared mutable state in the memory module — the same class of decomposition bugs found in the agent loop.

**Architecture:** Replace the `conflict_auto_resolve_gap` stale copy with a live callback. Make rollout updates atomic (dict replacement). Reorder `MemoryStore.__init__` to eliminate all post-construction wiring, breaking circular deps with lazy callbacks. Add 7 wiring contract tests. Add 2 CLAUDE.md guardrails.

**Tech Stack:** Python 3.10+, dataclasses, pytest, pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-03-25-memory-wiring-hardening-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `nanobot/memory/rollout.py` | Modify | `apply_overrides()` uses atomic dict replacement |
| `nanobot/memory/write/conflicts.py` | Modify | `ConflictManager` gains `resolve_gap_fn` callback |
| `nanobot/memory/persistence/profile_io.py` | Modify | `ProfileStore` gains `conflict_mgr_fn` + `corrector_fn` lazy callbacks |
| `nanobot/memory/write/ingester.py` | Modify | Receive `rollout_fn` callback instead of dict reference |
| `nanobot/memory/read/retriever.py` | Modify | Receive `rollout_fn` callback instead of dict reference |
| `nanobot/memory/maintenance.py` | Modify | Receive `rollout_fn` callback + reindex deps at construction |
| `nanobot/memory/store.py` | Modify | Reorder `__init__`; `rollout` becomes property; eliminate all post-construction wiring |
| `CLAUDE.md` | Modify | Add 2 new prohibited patterns |
| `tests/contract/test_memory_wiring.py` | Create | 7 wiring contract tests |

---

### Task 1: Make `RolloutConfig.apply_overrides()` atomic

**Files:**
- Modify: `nanobot/memory/rollout.py:65-120`
- Test: `tests/contract/test_memory_wiring.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/contract/test_memory_wiring.py`:

```python
"""Wiring contract tests: memory subsystem construction and state propagation."""

from __future__ import annotations

from nanobot.memory.rollout import RolloutConfig


def test_rollout_override_does_not_mutate_snapshot():
    """After apply_overrides, a previously captured dict is unchanged."""
    config = RolloutConfig()
    old_snapshot = dict(config.rollout)
    old_mode = old_snapshot.get("reranker_mode")

    config.apply_overrides({"reranker_mode": "disabled"})

    # The old snapshot must be untouched (atomic replacement, not in-place mutation)
    assert old_snapshot.get("reranker_mode") == old_mode
    # The current rollout reflects the override
    assert config.rollout.get("reranker_mode") == "disabled"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/contract/test_memory_wiring.py::test_rollout_override_does_not_mutate_snapshot -v`
Expected: FAIL — `old_snapshot.get("reranker_mode")` is `"disabled"` because the current code mutates in-place.

- [ ] **Step 3: Make `apply_overrides` atomic**

In `nanobot/memory/rollout.py`, change `apply_overrides()` to build a new dict and replace atomically. Replace the method body (lines 65-120) with:

```python
    def apply_overrides(self, overrides: dict[str, Any]) -> None:
        """Merge *overrides* into the current rollout dict, with validation.

        Replaces the entire dict atomically — existing references to the old
        dict are not affected.
        """
        if not overrides:
            return
        merged = dict(self.rollout)  # shallow copy
        mode = (
            str(
                overrides.get(
                    "memory_rollout_mode",
                    merged.get("memory_rollout_mode", "enabled"),
                )
            )
            .strip()
            .lower()
        )
        if mode in self.ROLLOUT_MODES:
            merged["memory_rollout_mode"] = mode
        for key in (
            "memory_type_separation_enabled",
            "memory_router_enabled",
            "memory_reflection_enabled",
            "memory_vector_health_enabled",
            "memory_auto_reindex_on_empty_vector",
        ):
            if key in overrides:
                merged[key] = bool(overrides[key])
        if isinstance(overrides.get("rollout_gates"), dict):
            gates = dict(merged.get("rollout_gates") or {})
            for key in (
                "min_recall_at_k",
                "min_precision_at_k",
                "max_avg_memory_context_tokens",
                "max_history_fallback_ratio",
            ):
                if key not in overrides["rollout_gates"]:
                    continue
                try:
                    gates[key] = float(overrides["rollout_gates"][key])
                except (TypeError, ValueError):
                    continue
            merged["rollout_gates"] = gates
        # Reranker overrides
        if "reranker_mode" in overrides:
            rm = str(overrides["reranker_mode"]).strip().lower()
            if rm in ("enabled", "shadow", "disabled"):
                merged["reranker_mode"] = rm
        if "reranker_alpha" in overrides:
            try:
                merged["reranker_alpha"] = min(
                    max(float(overrides["reranker_alpha"]), 0.0), 1.0
                )
            except (TypeError, ValueError):
                pass
        if "reranker_model" in overrides:
            merged["reranker_model"] = str(overrides["reranker_model"]).strip()
        # Pass through any other keys (graph_enabled, conflict_auto_resolve_gap, etc.)
        # that consumers read directly from the rollout dict.
        for key in overrides:
            if key not in merged:
                merged[key] = overrides[key]
        self.rollout = merged  # atomic replacement
```

Key change: `merged = dict(self.rollout)` at the top, all mutations on `merged`, then `self.rollout = merged` at the end.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/contract/test_memory_wiring.py::test_rollout_override_does_not_mutate_snapshot -v`
Expected: PASS

- [ ] **Step 5: Run lint + typecheck**

Run: `make lint && make typecheck`

- [ ] **Step 6: Commit**

```bash
git add nanobot/memory/rollout.py tests/contract/test_memory_wiring.py
git commit -m "feat: make RolloutConfig.apply_overrides atomic (dict replacement)"
```

---

### Task 2: Replace `conflict_auto_resolve_gap` stale copy with live callback

**Files:**
- Modify: `nanobot/memory/write/conflicts.py:50-67`
- Modify: `nanobot/memory/store.py:237-241`
- Test: `tests/contract/test_memory_wiring.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/contract/test_memory_wiring.py`:

```python
from pathlib import Path

from nanobot.memory.store import MemoryStore


def _make_store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(
        tmp_path,
        embedding_provider="hash",
        rollout_overrides={"graph_enabled": False},
    )


def test_conflict_resolve_gap_follows_rollout(tmp_path):
    """ConflictManager reads the current rollout value, not a stale copy."""
    store = _make_store(tmp_path)

    # Default gap is 0.25
    assert store.conflict_mgr._resolve_gap_fn() == 0.25

    # Simulate a rollout override (via _rollout_config)
    store._rollout_config.apply_overrides({"conflict_auto_resolve_gap": 0.5})

    # ConflictManager must see the new value
    assert store.conflict_mgr._resolve_gap_fn() == 0.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/contract/test_memory_wiring.py::test_conflict_resolve_gap_follows_rollout -v`
Expected: FAIL — `ConflictManager` has no `_resolve_gap_fn` attribute.

- [ ] **Step 3: Add `resolve_gap_fn` to ConflictManager**

In `nanobot/memory/write/conflicts.py`, modify `__init__` (line 50-67):

Add `resolve_gap_fn: Callable[[], float] | None = None` parameter after `db`:

```python
    def __init__(
        self,
        profile_store: ProfileStore | ProfileManager,
        *,
        sanitize_mem0_text_fn: Callable[..., str] | None = None,
        normalize_metadata_fn: Callable[..., tuple[dict, bool]] | None = None,
        sanitize_metadata_fn: Callable[[dict], dict] | None = None,
        db: UnifiedMemoryDB | None = None,
        resolve_gap_fn: Callable[[], float] | None = None,
    ) -> None:
        self.profile_mgr = profile_store
        self._sanitize_mem0_text = sanitize_mem0_text_fn
        self._normalize_metadata = normalize_metadata_fn
        self._sanitize_metadata = sanitize_metadata_fn
        self._db = db
        self._resolve_gap_fn = resolve_gap_fn or (lambda: 0.25)
```

Remove `self.conflict_auto_resolve_gap: float = 0.25` (line 67).

Find every read of `self.conflict_auto_resolve_gap` in the file (line ~291) and replace with `self._resolve_gap_fn()`.

- [ ] **Step 3.5: Grep for external usages of `conflict_auto_resolve_gap`**

Run: `grep -rn "conflict_auto_resolve_gap" nanobot/ tests/`

Verify: only `store.py` and `conflicts.py` reference this field. If any test directly
sets `store.conflict_auto_resolve_gap = X` or `conflict_mgr.conflict_auto_resolve_gap = X`,
update those tests to use the new rollout override pattern instead.

- [ ] **Step 4: Wire callback in MemoryStore**

In `nanobot/memory/store.py`, modify ConflictManager construction (line 216-222) to pass `resolve_gap_fn`:

```python
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
```

Remove lines 237-241 (`self.conflict_auto_resolve_gap` field and the assignment to `conflict_mgr`).

Make `self.conflict_auto_resolve_gap` a computed property on MemoryStore if any external code reads it:

```python
    @property
    def conflict_auto_resolve_gap(self) -> float:
        return float(self._rollout_config.rollout.get("conflict_auto_resolve_gap", 0.25))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/contract/test_memory_wiring.py -v`
Expected: ALL PASS

- [ ] **Step 6: Run lint + typecheck**

Run: `make lint && make typecheck`

- [ ] **Step 7: Commit**

```bash
git add nanobot/memory/write/conflicts.py nanobot/memory/store.py tests/contract/test_memory_wiring.py
git commit -m "feat: replace conflict_auto_resolve_gap stale copy with live callback"
```

---

### Task 3: Switch ingester and retriever to `rollout_fn` callback

**Files:**
- Modify: `nanobot/memory/write/ingester.py:63-76`
- Modify: `nanobot/memory/read/retriever.py:71-92`
- Modify: `nanobot/memory/maintenance.py:26-33`
- Modify: `nanobot/memory/store.py` (update construction calls)
- Test: `tests/contract/test_memory_wiring.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/contract/test_memory_wiring.py`:

```python
def test_subsystem_rollout_fn_reflects_property_change(tmp_path):
    """After rollout is replaced, subsystem callbacks return new dict."""
    store = _make_store(tmp_path)

    old_graph = store._rollout_config.rollout.get("graph_enabled")

    # Replace rollout via overrides
    store._rollout_config.apply_overrides({"graph_enabled": not old_graph})

    # Subsystem callbacks should reflect the change
    new_rollout = store.rollout
    assert new_rollout.get("graph_enabled") == (not old_graph)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/contract/test_memory_wiring.py::test_subsystem_rollout_fn_reflects_property_change -v`
Expected: FAIL — `store.rollout` is still a plain attribute, not a property yet.

- [ ] **Step 3: Make `store.rollout` a property**

In `nanobot/memory/store.py`, remove line 143 (`self.rollout = self._rollout_config.rollout`).

Add a property after `__init__`:

```python
    @property
    def rollout(self) -> dict[str, Any]:
        """Live rollout config — always returns the current dict from RolloutConfig."""
        return self._rollout_config.rollout
```

- [ ] **Step 4: Switch EventIngester to `rollout_fn` callback**

In `nanobot/memory/write/ingester.py`, change `__init__` (line 63):

```python
    def __init__(
        self,
        graph: KnowledgeGraph | None,
        rollout_fn: Callable[[], dict[str, Any]],
        *,
        conflict_pair_fn: Callable[[str, str], bool] | None = None,
        db: UnifiedMemoryDB | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self._graph = graph
        self._rollout_fn = rollout_fn
        ...
```

Replace `self._rollout` reads with `self._rollout_fn()` at lines 73 and 430.

Update `store.py` ingester construction (line 207):

```python
        self.ingester = EventIngester(
            graph=self.graph,
            rollout_fn=lambda: self.rollout,
            conflict_pair_fn=lambda old, new: self.profile_mgr._conflict_pair(old, new),
            db=self.db,
            embedder=self._embedder,
        )
```

- [ ] **Step 5: Switch MemoryRetriever to `rollout_fn` callback**

In `nanobot/memory/read/retriever.py`, change `__init__` (line 71):

Change `rollout: dict[str, Any]` to `rollout_fn: Callable[[], dict[str, Any]]`.
Store as `self._rollout_fn = rollout_fn`.
Replace `self._rollout` reads with `self._rollout_fn()` at lines 88 and 623.

Update `store.py` retriever construction (line 225):

```python
        self.retriever = MemoryRetriever(
            graph=self.graph,
            planner=self._planner,
            reranker=self._reranker,
            profile_mgr=self.profile_mgr,
            rollout_fn=lambda: self.rollout,
            read_events_fn=self.ingester.read_events,
            extractor=self.extractor,
            db=self.db,
            embedder=self._embedder,
        )
```

- [ ] **Step 6: Switch MemoryMaintenance to `rollout_fn` callback**

In `nanobot/memory/maintenance.py`, change `__init__` (line 26):

Change `rollout: dict[str, Any]` to `rollout_fn: Callable[[], dict[str, Any]]`.
Add `reindex_fn: Callable[[], None] | None = None` parameter.
Store as `self._rollout_fn = rollout_fn` and `self._reindex_fn = reindex_fn`.
Replace `self.rollout` reads with `self._rollout_fn()`.
Remove external assignment pattern for `_reindex_fn`.

Update `store.py` maintenance construction (line 172) — note: the full construction
with `reindex_fn` happens in Task 4 (needs ingester/profile_mgr to exist first).
For now, pass just the rollout_fn:

```python
        self.maintenance = MemoryMaintenance(
            rollout_fn=lambda: self.rollout,
            db=self.db,
        )
```

- [ ] **Step 7: Run tests**

Run: `python -m pytest tests/contract/test_memory_wiring.py tests/contract/test_memory_contracts.py tests/integration/test_memory_retrieval_pipeline.py -v`
Expected: ALL PASS

- [ ] **Step 8: Run lint + typecheck**

Run: `make lint && make typecheck`

- [ ] **Step 9: Commit**

```bash
git add nanobot/memory/store.py nanobot/memory/write/ingester.py nanobot/memory/read/retriever.py nanobot/memory/maintenance.py tests/contract/test_memory_wiring.py
git commit -m "feat: switch memory subsystems to rollout_fn callback + rollout property"
```

---

### Task 4: Eliminate post-construction wiring in MemoryStore

**Files:**
- Modify: `nanobot/memory/persistence/profile_io.py:97-114`
- Modify: `nanobot/memory/store.py:145-285`
- Test: `tests/contract/test_memory_wiring.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/contract/test_memory_wiring.py`:

```python
def test_profile_mgr_has_conflict_mgr_at_construction(tmp_path):
    """ProfileStore._conflict_mgr_fn resolves immediately after MemoryStore construction."""
    store = _make_store(tmp_path)
    assert store.profile_mgr._conflict_mgr_fn() is not None


def test_profile_mgr_corrector_fn_resolves(tmp_path):
    """ProfileStore._corrector_fn resolves to a CorrectionOrchestrator after construction."""
    store = _make_store(tmp_path)
    corrector = store.profile_mgr._corrector_fn()
    assert corrector is not None


def test_maintenance_reindex_runs_without_error(tmp_path):
    """MemoryMaintenance.reindex runs without AttributeError (all deps wired)."""
    store = _make_store(tmp_path)
    # Seed a minimal event so reindex has something to process
    store.ingester.append_events([{
        "type": "fact",
        "summary": "Test fact for reindex.",
        "timestamp": "2026-03-01T10:00:00+00:00",
        "source": "test",
    }])
    # Should not raise AttributeError from missing _reindex_fn
    try:
        store.maintenance.reindex_from_structured_memory(
            read_profile_fn=store.profile_mgr.read_profile,
            read_events_fn=store.ingester.read_events,
            ingester=store.ingester,
            profile_keys=store.PROFILE_KEYS,
        )
    except Exception as e:
        # reindex may fail for other reasons in test context, but must NOT
        # fail with AttributeError from missing wiring
        assert not isinstance(e, AttributeError), f"Wiring error: {e}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/contract/test_memory_wiring.py -k "profile_mgr_has or corrector_fn" -v`
Expected: FAIL — `ProfileStore` has no `_conflict_mgr_fn` attribute.

- [ ] **Step 3: Modify ProfileStore to use lazy callbacks**

In `nanobot/memory/persistence/profile_io.py`, change `__init__` (line 97).

**Background:** The current code constructs `ProfileStore` with only `db=self.db` at
`store.py:148`, then post-wires `_extractor`, `_ingester`, `_conflict_mgr`, `_snapshot`,
`_corrector` at lines 278-285. In the new construction order, `ProfileStore` is built
first (before ingester, conflict_mgr, snapshot, corrector). Since all these dependencies
are only needed at **call time** (not construction time), convert them all to lazy
callbacks:

```python
    def __init__(
        self,
        *,
        db: UnifiedMemoryDB | None = None,
        conflict_mgr_fn: Callable[[], Any] | None = None,
        corrector_fn: Callable[[], Any] | None = None,
        extractor_fn: Callable[[], Any] | None = None,
        ingester_fn: Callable[[], Any] | None = None,
        snapshot_fn: Callable[[], Any] | None = None,
    ) -> None:
        self._db = db
        self._conflict_mgr_fn = conflict_mgr_fn
        self._corrector_fn = corrector_fn
        self._extractor_fn = extractor_fn
        self._ingester_fn = ingester_fn
        self._snapshot_fn = snapshot_fn
        self._cache = ProfileCache()
```

Add `from typing import Callable` to imports if not already present.

Replace all reads of `self._conflict_mgr` with `self._conflict_mgr_fn()`:
- Line 648: `self._conflict_mgr_fn()._conflict_pair(old_value, new_value)`
- Line 659: `self._conflict_mgr_fn()._apply_profile_updates(...)`
- Line 690: `self._conflict_mgr_fn().has_open_conflict(profile, key)`

Replace `self._corrector` reads with `self._corrector_fn()`:
- Line 721-722: Remove `assert self._corrector is not None`, change to `self._corrector_fn()`

Replace `self._extractor` reads with `self._extractor_fn()`, `self._ingester` with
`self._ingester_fn()`, `self._snapshot` with `self._snapshot_fn()` at all call sites.

Then update `MemoryStore.__init__` (Task 4, Step 4) to pass all lazy callbacks:

```python
        self.profile_mgr = ProfileStore(
            db=self.db,
            conflict_mgr_fn=lambda: self.conflict_mgr,
            corrector_fn=lambda: self._corrector,
            extractor_fn=lambda: self.extractor,
            ingester_fn=lambda: self.ingester,
            snapshot_fn=lambda: self.snapshot,
        )
```

- [ ] **Step 4: Reorder MemoryStore.__init__ construction**

In `nanobot/memory/store.py`, rewrite the construction order starting after the DB/embedder/extractor/rollout setup (~line 137).

The new order:

```python
        # 1. Profile manager — lazy callbacks for conflict_mgr and corrector
        self.profile_mgr = ProfileStore(
            db=self.db,
            conflict_mgr_fn=lambda: self.conflict_mgr,
            corrector_fn=lambda: self._corrector,
        )

        # 2. Planner, budget allocator (no deps on profile_mgr cycle)
        self._planner = RetrievalPlanner()
        self._budget_allocator = TokenBudgetAllocator(DEFAULT_SECTION_WEIGHTS)

        # 3. Reranker and graph (need rollout values, read at construction)
        reranker_model = str(self.rollout.get("reranker_model", "...")).strip()
        reranker_alpha = float(self.rollout.get("reranker_alpha", 0.5))
        # ... reranker construction unchanged ...

        graph_enabled = self.rollout.get("graph_enabled", True)
        # ... graph construction unchanged ...

        # 4. Ingester (needs graph, rollout_fn)
        self.ingester = EventIngester(
            graph=self.graph,
            rollout_fn=lambda: self.rollout,
            conflict_pair_fn=lambda old, new: self.profile_mgr._conflict_pair(old, new),
            db=self.db,
            embedder=self._embedder,
        )

        # 5. Conflict manager (needs profile_mgr, ingester fns)
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

        # 6. Retriever (needs graph, rollout_fn, profile_mgr)
        self.retriever = MemoryRetriever(
            graph=self.graph,
            planner=self._planner,
            reranker=self._reranker,
            profile_mgr=self.profile_mgr,
            rollout_fn=lambda: self.rollout,
            read_events_fn=self.ingester.read_events,
            extractor=self.extractor,
            db=self.db,
            embedder=self._embedder,
        )

        # 7. Context assembler (needs retriever, ingester, profile_mgr)
        self._assembler = ContextAssembler(
            profile_mgr=self.profile_mgr,
            retrieve_fn=lambda *a, **kw: self.retriever.retrieve(*a, **kw),
            # ... rest unchanged ...
        )

        # 8. Maintenance (needs rollout_fn, db, reindex deps as callbacks)
        self.maintenance = MemoryMaintenance(
            rollout_fn=lambda: self.rollout,
            db=self.db,
            reindex_fn=lambda: self.maintenance.reindex_from_structured_memory(
                read_profile_fn=self.profile_mgr.read_profile,
                read_events_fn=self.ingester.read_events,
                ingester=self.ingester,
                profile_keys=self.PROFILE_KEYS,
            ),
        )
        # Note: the lambda captures `self` — by the time it's called at runtime,
        # self.maintenance exists. No post-construction assignment needed.

        # 9. Snapshot (needs profile_mgr, assembler, ingester)
        self.snapshot = MemorySnapshot(
            profile_mgr=self.profile_mgr,
            # ... rest unchanged ...
        )

        # 10. Corrector — ALL deps now available, no post-wiring needed
        from .persistence.profile_correction import (
            CorrectionOrchestrator as _CorrectionOrchestrator,
        )
        self._corrector = _CorrectionOrchestrator(
            profile_store=self.profile_mgr,
            extractor=self.extractor,
            ingester=self.ingester,
            conflict_mgr=self.conflict_mgr,
            snapshot=self.snapshot,
        )

        # 11. Consolidation pipeline (needs all above)
        self._consolidation = ConsolidationPipeline(...)

        # 12. Eval runner (needs retriever, maintenance)
        # ... unchanged ...
```

**Remove** the old post-construction wiring block (lines 273-285):
```python
# DELETE these lines:
self.profile_mgr._conflict_mgr = self.conflict_mgr
self.profile_mgr._corrector = _CorrectionOrchestrator(...)
```

- [ ] **Step 5: Run ALL tests**

Run: `python -m pytest tests/contract/test_memory_wiring.py tests/contract/test_memory_contracts.py tests/integration/test_memory_retrieval_pipeline.py tests/integration/test_profile_conflicts.py -v`
Expected: ALL PASS

- [ ] **Step 6: Run full check**

Run: `make check`

- [ ] **Step 7: Commit**

```bash
git add nanobot/memory/store.py nanobot/memory/persistence/profile_io.py tests/contract/test_memory_wiring.py
git commit -m "feat: eliminate post-construction wiring in MemoryStore

Reorder __init__ so all deps are available before use. ProfileStore
uses lazy callbacks (conflict_mgr_fn, corrector_fn) to break the
three-way cycle with ConflictManager and CorrectionOrchestrator."
```

---

### Task 5: Add rollout consistency test

**Files:**
- Test: `tests/contract/test_memory_wiring.py`

- [ ] **Step 1: Write the test**

Append to `tests/contract/test_memory_wiring.py`:

```python
def test_rollout_override_atomic_consistency(tmp_path):
    """After overrides, ingester and retriever see the same rollout values."""
    store = _make_store(tmp_path)

    store._rollout_config.apply_overrides({"reranker_mode": "disabled"})

    # Both subsystems' rollout_fn should return the same dict
    ingester_rollout = store.ingester._rollout_fn()
    retriever_rollout = store.retriever._rollout_fn()

    assert ingester_rollout is retriever_rollout
    assert ingester_rollout.get("reranker_mode") == "disabled"
```

- [ ] **Step 2: Run test**

Run: `python -m pytest tests/contract/test_memory_wiring.py::test_rollout_override_atomic_consistency -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/contract/test_memory_wiring.py
git commit -m "test: add rollout consistency contract test for memory subsystems"
```

---

### Task 6: Add CLAUDE.md guardrails

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add prohibited pattern — post-construction field assignment**

In `CLAUDE.md`, under **Prohibited Patterns > Wiring violations**, add:

```markdown
- Assigning to another component's private fields after construction
  (e.g., `component._field = value` outside `__init__`). If a component
  needs a dependency, pass it at construction time. If a circular dependency
  prevents this, use a lazy callback (`lambda: self.dependency`) to break
  the cycle — never leave a field as None with defensive null-checks.
```

- [ ] **Step 2: Add prohibited pattern — shared mutable collections**

In the same section, add:

```markdown
- Sharing mutable collections (dicts, lists, sets) across multiple components
  without a documented synchronization strategy. Either pass immutable snapshots
  (replace atomically, not mutate in-place), or document the sharing contract
  with a comment at each receiver: `# shared-ref: <what>, <mutation contract>`.
```

- [ ] **Step 3: Run full check**

Run: `make check`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add post-construction wiring and shared-mutable-state guardrails to CLAUDE.md"
```

---

### Task 7: Final validation

- [ ] **Step 1: Run full CI check**

Run: `make check`
Expected: ALL PASS

- [ ] **Step 2: Run all memory-related tests**

Run: `python -m pytest tests/contract/test_memory_wiring.py tests/contract/test_memory_contracts.py tests/integration/test_memory_retrieval_pipeline.py tests/integration/test_profile_conflicts.py tests/integration/test_knowledge_graph_ingest.py -v`
Expected: ALL PASS

- [ ] **Step 3: Verify no import boundary violations**

Run: `make import-check`
Expected: PASS

- [ ] **Step 4: Review git log**

Run: `git log --oneline -10`
Verify: 6 clean commits, one per task.
