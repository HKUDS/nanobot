# Memory Phase 0: Constants Consolidation & Unnecessary Lambda Elimination

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate duplicated constant definitions across the memory subsystem and remove 11 unnecessary lambda wrappers in `store.py`, establishing a clean baseline for subsequent architectural phases.

**Architecture:** All memory domain constants (event types, memory types, stability levels, profile keys, status constants) move to `memory/constants.py` as the single source of truth. All consumers import from there — no class-level aliases, no re-definitions. Separately, 11 lambda callbacks in `store.py` that exist only as unnecessary lazy wrappers (not circular dependency breakers) are replaced with direct object references.

**Tech Stack:** Python 3.10+, ruff, mypy, pytest

**Context documents:**
- Assessment: `docs/superpowers/plans/2026-03-30-memory-architecture-assessment.md`
- Architecture: `.claude/rules/architecture.md`
- Change protocol: `.claude/rules/change-protocol.md`
- Prohibited patterns: `.claude/rules/prohibited-patterns.md`

---

## File Structure

### Files to Modify

| File | Change |
|------|--------|
| `nanobot/memory/constants.py` | Add domain constants (PROFILE_KEYS, status constants, type sets) |
| `nanobot/memory/store.py` | Remove class-level constant aliases; replace 11 unnecessary lambdas with direct refs |
| `nanobot/memory/event.py` | Remove `MEMORY_TYPES` frozenset; import from constants |
| `nanobot/memory/write/classification.py` | Remove module-level `EVENT_TYPES`, `MEMORY_TYPES`, `MEMORY_STABILITY`; remove class aliases; import from constants |
| `nanobot/memory/write/coercion.py` | Remove `EPISODIC_STATUS_*`; import from constants |
| `nanobot/memory/write/conflicts.py` | Remove `CONFLICT_STATUS_*` definitions; import from constants |
| `nanobot/memory/write/ingester.py` | Remove class-level type set aliases; import from constants |
| `nanobot/memory/persistence/profile_io.py` | Remove `PROFILE_KEYS`, `PROFILE_STATUS_*` definitions and class aliases; import from constants |
| `nanobot/memory/persistence/snapshot.py` | Remove `PROFILE_KEYS`, status constant definitions; import from constants |
| `nanobot/memory/read/context_assembler.py` | Remove `PROFILE_KEYS`, status class attributes; import from constants |
| `nanobot/memory/read/scoring.py` | Remove `PROFILE_KEYS` definition; import from constants |

### Files to Create

| File | Purpose |
|------|---------|
| `tests/contract/test_memory_constants.py` | Contract tests verifying constant consistency and cross-component data contracts |

---

## Task 1: Add Domain Constants to constants.py

**Files:**
- Modify: `nanobot/memory/constants.py`
- Test: `tests/contract/test_memory_constants.py`

- [ ] **Step 1: Write contract tests for the new constants**

```python
"""Contract tests for memory domain constants.

Verifies that all memory constants are defined in a single location
and that cross-component data contracts hold.
"""
from __future__ import annotations

from nanobot.memory.constants import (
    CONFLICT_STATUS_NEEDS_USER,
    CONFLICT_STATUS_OPEN,
    CONFLICT_STATUS_RESOLVED,
    EPISODIC_STATUS_OPEN,
    EPISODIC_STATUS_RESOLVED,
    EVENT_TYPES,
    MEMORY_STABILITY,
    MEMORY_TYPES,
    PROFILE_KEYS,
    PROFILE_STATUS_ACTIVE,
    PROFILE_STATUS_CONFLICTED,
    PROFILE_STATUS_STALE,
)


class TestConstantsExist:
    """All domain constants are importable from constants.py."""

    def test_profile_keys_is_tuple(self) -> None:
        assert isinstance(PROFILE_KEYS, tuple)
        assert len(PROFILE_KEYS) == 5
        assert "preferences" in PROFILE_KEYS
        assert "stable_facts" in PROFILE_KEYS
        assert "active_projects" in PROFILE_KEYS
        assert "relationships" in PROFILE_KEYS
        assert "constraints" in PROFILE_KEYS

    def test_event_types(self) -> None:
        assert isinstance(EVENT_TYPES, frozenset)
        assert EVENT_TYPES == {"preference", "fact", "task", "decision", "constraint", "relationship"}

    def test_memory_types(self) -> None:
        assert isinstance(MEMORY_TYPES, frozenset)
        assert MEMORY_TYPES == {"semantic", "episodic", "reflection"}

    def test_memory_stability(self) -> None:
        assert isinstance(MEMORY_STABILITY, frozenset)
        assert MEMORY_STABILITY == {"high", "medium", "low"}

    def test_conflict_statuses(self) -> None:
        assert CONFLICT_STATUS_OPEN == "open"
        assert CONFLICT_STATUS_NEEDS_USER == "needs_user"
        assert CONFLICT_STATUS_RESOLVED == "resolved"

    def test_episodic_statuses(self) -> None:
        assert EPISODIC_STATUS_OPEN == "open"
        assert EPISODIC_STATUS_RESOLVED == "resolved"

    def test_profile_statuses(self) -> None:
        assert PROFILE_STATUS_ACTIVE == "active"
        assert PROFILE_STATUS_CONFLICTED == "conflicted"
        assert PROFILE_STATUS_STALE == "stale"


class TestEventTypeConsistency:
    """The MemoryEvent Pydantic model and constants agree on valid types."""

    def test_event_type_literal_matches_set(self) -> None:
        """EventType Literal and EVENT_TYPES frozenset contain the same values."""
        from typing import get_args

        from nanobot.memory.event import EventType

        literal_values = set(get_args(EventType))
        assert literal_values == EVENT_TYPES

    def test_memory_type_literal_matches_set(self) -> None:
        from typing import get_args

        from nanobot.memory.event import MemoryType

        literal_values = set(get_args(MemoryType))
        assert literal_values == MEMORY_TYPES

    def test_stability_literal_matches_set(self) -> None:
        from typing import get_args

        from nanobot.memory.event import Stability

        literal_values = set(get_args(Stability))
        assert literal_values == MEMORY_STABILITY
```

Create this file at `tests/contract/test_memory_constants.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/contract/test_memory_constants.py -v`
Expected: FAIL — constants not yet exported from `constants.py`

- [ ] **Step 3: Add domain constants to constants.py**

Add the following block at the top of `nanobot/memory/constants.py`, after the existing `from __future__ import annotations` and before the tool schema definitions:

```python
# ---------------------------------------------------------------------------
# Domain constants — single source of truth for the memory subsystem.
# All consumers import from here. No re-definitions elsewhere.
# ---------------------------------------------------------------------------

PROFILE_KEYS: tuple[str, ...] = (
    "preferences",
    "stable_facts",
    "active_projects",
    "relationships",
    "constraints",
)

EVENT_TYPES: frozenset[str] = frozenset(
    {"preference", "fact", "task", "decision", "constraint", "relationship"}
)
MEMORY_TYPES: frozenset[str] = frozenset({"semantic", "episodic", "reflection"})
MEMORY_STABILITY: frozenset[str] = frozenset({"high", "medium", "low"})

# Profile belief statuses
PROFILE_STATUS_ACTIVE: str = "active"
PROFILE_STATUS_CONFLICTED: str = "conflicted"
PROFILE_STATUS_STALE: str = "stale"

# Conflict resolution statuses
CONFLICT_STATUS_OPEN: str = "open"
CONFLICT_STATUS_NEEDS_USER: str = "needs_user"
CONFLICT_STATUS_RESOLVED: str = "resolved"

# Episodic event statuses
EPISODIC_STATUS_OPEN: str = "open"
EPISODIC_STATUS_RESOLVED: str = "resolved"
```

Note: `EVENT_TYPES` and `MEMORY_TYPES` are `frozenset` (immutable), not `set`. This prevents accidental mutation and matches what `event.py` already uses.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/contract/test_memory_constants.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run lint and typecheck**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nanobot/memory/constants.py tests/contract/test_memory_constants.py
git commit -m "refactor(memory): add domain constants to constants.py as single source of truth"
```

---

## Task 2: Migrate Consumers to Import from constants.py

This task updates every file that defines or re-defines these constants to import
from `constants.py` instead. Each sub-step is one file.

**Files:**
- Modify: 10 files (listed below)
- Test: existing tests + `tests/contract/test_memory_constants.py`

- [ ] **Step 1: Update `nanobot/memory/event.py`**

Remove the `MEMORY_TYPES` frozenset definition (line 18). Add import from constants:

```python
# Replace line 18:
# MEMORY_TYPES: frozenset[str] = frozenset({"semantic", "episodic", "reflection"})
# With:
from .constants import MEMORY_TYPES
```

The `memory_type_for_item()` function on line 40 already uses `MEMORY_TYPES` — no other changes needed.

- [ ] **Step 2: Update `nanobot/memory/write/classification.py`**

Remove lines 18-20 (module-level constant definitions) and lines 27-29 (class-level aliases). Add import:

```python
# Replace:
# EVENT_TYPES: set[str] = {"preference", "fact", "task", "decision", "constraint", "relationship"}
# MEMORY_TYPES: set[str] = {"semantic", "episodic", "reflection"}
# MEMORY_STABILITY: set[str] = {"high", "medium", "low"}
# With:
from ..constants import EVENT_TYPES, MEMORY_STABILITY, MEMORY_TYPES
```

Remove the class-level aliases inside `EventClassifier`:
```python
# DELETE these lines:
#     EVENT_TYPES = EVENT_TYPES
#     MEMORY_TYPES = MEMORY_TYPES
#     MEMORY_STABILITY = MEMORY_STABILITY
```

Then update any code that accesses them via `self.EVENT_TYPES` or `cls.EVENT_TYPES` to use the module-level import directly. Check for references via `self._classifier.EVENT_TYPES` in coercion.py — those need updating too.

- [ ] **Step 3: Update `nanobot/memory/write/coercion.py`**

Remove `EPISODIC_STATUS_OPEN` and `EPISODIC_STATUS_RESOLVED` definitions (lines 22-23) and class-level aliases (lines 29-30). Add import:

```python
from ..constants import EPISODIC_STATUS_OPEN, EPISODIC_STATUS_RESOLVED
```

Update any `self.EPISODIC_STATUS_*` references in the class to use the module-level constants directly. Also update `dedup.py` which accesses these via `self._coercer.EPISODIC_STATUS_*`.

- [ ] **Step 4: Update `nanobot/memory/write/conflicts.py`**

Remove lines 28-30 (module-level definitions):
```python
# DELETE:
# CONFLICT_STATUS_OPEN = "open"
# CONFLICT_STATUS_NEEDS_USER = "needs_user"
# CONFLICT_STATUS_RESOLVED = "resolved"
```

Add import:
```python
from ..constants import CONFLICT_STATUS_NEEDS_USER, CONFLICT_STATUS_OPEN, CONFLICT_STATUS_RESOLVED
```

- [ ] **Step 5: Update `nanobot/memory/write/ingester.py`**

Remove class-level aliases (lines 36-38) and the import from classification (line 21 for these constants). Add import:

```python
from ..constants import EVENT_TYPES, MEMORY_STABILITY, MEMORY_TYPES
```

Update any `self.EVENT_TYPES` / `self.MEMORY_TYPES` / `self.MEMORY_STABILITY` references to use the module-level imports.

- [ ] **Step 6: Update `nanobot/memory/persistence/profile_io.py`**

Remove lines 30-40 (module-level `PROFILE_KEYS`, `PROFILE_STATUS_*` definitions). Remove class-level aliases on `ProfileStore` (lines 86-96 approximately). Update the `__all__` export list to remove these constants. Add import:

```python
from ..constants import (
    CONFLICT_STATUS_NEEDS_USER,
    CONFLICT_STATUS_OPEN,
    CONFLICT_STATUS_RESOLVED,
    PROFILE_KEYS,
    PROFILE_STATUS_ACTIVE,
    PROFILE_STATUS_CONFLICTED,
    PROFILE_STATUS_STALE,
)
```

Update any `self.PROFILE_KEYS`, `self.PROFILE_STATUS_*`, `self.CONFLICT_STATUS_*` references in the class to use module-level constants.

Also update `profile_correction.py` which accesses these via `self._profile_store.CONFLICT_STATUS_OPEN`.

- [ ] **Step 7: Update `nanobot/memory/persistence/snapshot.py`**

Remove the local definitions of `PROFILE_KEYS` (lines 19-25), `PROFILE_STATUS_STALE` (line 26), and `CONFLICT_STATUS_*` (lines 27-28). Add import:

```python
from ..constants import (
    CONFLICT_STATUS_NEEDS_USER,
    CONFLICT_STATUS_OPEN,
    PROFILE_KEYS,
    PROFILE_STATUS_STALE,
)
```

- [ ] **Step 8: Update `nanobot/memory/read/context_assembler.py`**

Remove the class-level attributes `PROFILE_KEYS` (lines 45-51), `PROFILE_STATUS_STALE` (line 53), and `EPISODIC_STATUS_RESOLVED` (line 54). Add import:

```python
from ..constants import EPISODIC_STATUS_RESOLVED, PROFILE_KEYS, PROFILE_STATUS_STALE
```

Update `self.PROFILE_KEYS`, `self.PROFILE_STATUS_STALE`, `self.EPISODIC_STATUS_RESOLVED` references to use the module-level imports.

- [ ] **Step 9: Update `nanobot/memory/read/scoring.py`**

Remove the module-level `PROFILE_KEYS` definition (lines 42-48). Add import:

```python
from ..constants import PROFILE_KEYS
```

- [ ] **Step 10: Update `nanobot/memory/store.py`**

Remove all class-level constant definitions from `MemoryStore` (lines 59-76):
```python
# DELETE:
#     PROFILE_KEYS = (...)
#     EVENT_TYPES = {...}
#     MEMORY_TYPES = {...}
#     MEMORY_STABILITY = {...}
#     PROFILE_STATUS_ACTIVE = "active"
#     PROFILE_STATUS_CONFLICTED = "conflicted"
#     PROFILE_STATUS_STALE = "stale"
#     CONFLICT_STATUS_OPEN = CONFLICT_STATUS_OPEN
#     CONFLICT_STATUS_NEEDS_USER = CONFLICT_STATUS_NEEDS_USER
#     CONFLICT_STATUS_RESOLVED = CONFLICT_STATUS_RESOLVED
#     EPISODIC_STATUS_OPEN = "open"
#     EPISODIC_STATUS_RESOLVED = "resolved"
```

Remove the import of conflict status constants from `write.conflicts` (lines 39-44). Add import from constants:

```python
from .constants import (
    CONFLICT_STATUS_NEEDS_USER,
    CONFLICT_STATUS_OPEN,
    CONFLICT_STATUS_RESOLVED,
    PROFILE_KEYS,
)
```

Update references in store.py that use `self.PROFILE_KEYS` to use the module-level `PROFILE_KEYS`.

Also check: any external code that accesses `store.CONFLICT_STATUS_OPEN`, `store.PROFILE_KEYS`, etc. must be updated to import from `nanobot.memory.constants` instead. Grep for `store\.PROFILE_KEYS`, `store\.EVENT_TYPES`, `store\.CONFLICT_STATUS_`, `store\.EPISODIC_STATUS_`, `store\.PROFILE_STATUS_`, `store\.MEMORY_TYPES`, `store\.MEMORY_STABILITY` across the entire repo.

- [ ] **Step 11: Update any external consumers**

Grep across the entire codebase for any remaining references to the old constant locations:

```bash
grep -rn "\.PROFILE_KEYS\b" nanobot/ tests/ --include="*.py" | grep -v constants.py
grep -rn "\.EVENT_TYPES\b" nanobot/ tests/ --include="*.py" | grep -v constants.py
grep -rn "\.MEMORY_TYPES\b" nanobot/ tests/ --include="*.py" | grep -v constants.py | grep -v event.py
grep -rn "\.MEMORY_STABILITY\b" nanobot/ tests/ --include="*.py" | grep -v constants.py
grep -rn "CONFLICT_STATUS_" nanobot/ tests/ --include="*.py" | grep -v constants.py | grep -v "from.*constants"
grep -rn "EPISODIC_STATUS_" nanobot/ tests/ --include="*.py" | grep -v constants.py | grep -v "from.*constants"
grep -rn "PROFILE_STATUS_" nanobot/ tests/ --include="*.py" | grep -v constants.py | grep -v "from.*constants"
```

Fix any remaining references. Zero matches required (per change-protocol.md post-deletion checklist).

- [ ] **Step 12: Run full test suite**

Run: `make check && make test`
Expected: ALL PASS — pure refactoring, no behavioral change.

- [ ] **Step 13: Commit**

```bash
git add -u nanobot/memory/ tests/
git commit -m "refactor(memory): consolidate all domain constants into constants.py

Remove duplicated constant definitions from 10 files. All consumers
now import from nanobot.memory.constants as single source of truth.
No behavioral changes."
```

---

## Task 3: Eliminate Unnecessary Lambda Wrappers in store.py

11 of the 22 lambda callbacks in `store.py` exist only as lazy wrappers where
the wrapped object already exists at construction time. These can be replaced
with direct references.

**Files:**
- Modify: `nanobot/memory/store.py`
- Modify: Receiver classes that accept `_fn` callbacks (to accept direct refs instead)
- Test: `tests/contract/test_memory_wiring.py` + existing tests

- [ ] **Step 1: Verify the 11 eliminable lambdas**

These lambdas wrap objects that already exist when the receiving class is constructed:

| Line | Lambda | Wraps | Receiver | Direct ref possible |
|------|--------|-------|----------|-------------------|
| 132 | `lambda raw, **kw: self._coercer.coerce_event(raw, **kw)` | `_coercer.coerce_event` | `MemoryExtractor` | Pass `self._coercer.coerce_event` as bound method |
| 142 | `lambda: self.extractor` | `self.extractor` | `ProfileStore` | Pass `self.extractor` directly |
| 210 | `lambda: self._memory_config.conflict_auto_resolve_gap` | config attr | `ConflictManager` | Pass `self._memory_config` directly |
| 217 | `lambda: self._memory_config` | `self._memory_config` | `RetrievalScorer` | Pass `self._memory_config` directly |
| 236 | `lambda *a, **kw: self.retriever.retrieve(*a, **kw)` | `self.retriever.retrieve` | `EvalRunner` | Pass `self.retriever` directly |
| 239 | `lambda: self._memory_config` | `self._memory_config` | `EvalRunner` | Pass `self._memory_config` directly |
| 240 | `lambda: self.maintenance._backend_stats_for_eval()` | method call | `EvalRunner` | Pass `self.maintenance` directly |
| 246 | `lambda **kw: self.ingester.read_events(**kw)` | `self.ingester.read_events` | `MemorySnapshot` | Pass `self.ingester` directly |
| 253 | `lambda: self.profile_mgr.verify_beliefs()` | method call | `MemorySnapshot` | Pass `self.profile_mgr` directly |
| 254 | `lambda profile: self.profile_mgr.write_profile(profile)` | method call | `MemorySnapshot` | Pass `self.profile_mgr` directly |

Note: lines 246, 253, 254 are for `MemorySnapshot`. The `ingester` (line 198) and `profile_mgr` (line 138) both exist before `MemorySnapshot` is constructed (line 244). These are safe to replace.

- [ ] **Step 2: Update receiver classes to accept direct references**

For each receiver class, change the `_fn` callback parameter to accept the concrete object. Example for `MemorySnapshot`:

Before (snapshot.py constructor):
```python
def __init__(
    self,
    ...,
    read_events_fn: Callable[..., list[dict]] | None = None,
    verify_beliefs_fn: Callable[[], None] | None = None,
    write_profile_fn: Callable[[dict], None] | None = None,
):
```

After:
```python
def __init__(
    self,
    ...,
    ingester: EventIngester | None = None,  # replaces read_events_fn
    profile_mgr: ProfileStore | None = None,  # replaces verify_beliefs_fn + write_profile_fn (already exists)
):
```

Then update method bodies to call `self._ingester.read_events()` instead of `self._read_events_fn()`, etc.

Apply the same pattern to:
- `MemoryExtractor`: replace `coerce_event` callable with `coercer: EventCoercer`
- `ConflictManager`: replace `resolve_gap_fn` with `memory_config: MemoryConfig`
- `RetrievalScorer`: replace `memory_config_fn` with `memory_config: MemoryConfig`
- `EvalRunner`: replace callback params with direct object refs

**Important:** For each class, use TYPE_CHECKING imports for the new type annotations if needed to avoid circular imports. Only convert the params that correspond to the 11 non-circular lambdas identified above. Leave the 11 circular-dependency lambdas untouched.

- [ ] **Step 3: Update store.py to pass direct references**

Replace each lambda with the direct reference. Example:

Before:
```python
self.snapshot = MemorySnapshot(
    ...
    read_events_fn=lambda **kw: self.ingester.read_events(**kw),
    verify_beliefs_fn=lambda: self.profile_mgr.verify_beliefs(),
    write_profile_fn=lambda profile: self.profile_mgr.write_profile(profile),
)
```

After:
```python
self.snapshot = MemorySnapshot(
    ...
    ingester=self.ingester,
    # profile_mgr already passed above
)
```

- [ ] **Step 4: Run full test suite**

Run: `make check && make test`
Expected: ALL PASS — pure refactoring, no behavioral change.

- [ ] **Step 5: Run wiring contract tests specifically**

Run: `pytest tests/contract/test_memory_wiring.py -v`
Expected: ALL PASS

- [ ] **Step 6: Verify lambda count reduction**

```bash
grep -c "lambda" nanobot/memory/store.py
```

Expected: ~11 (down from ~22). The remaining 11 are the genuine circular dependency breakers that will be resolved in Phase 2.

- [ ] **Step 7: Commit**

```bash
git add -u nanobot/memory/ nanobot/eval/ tests/
git commit -m "refactor(memory): replace 11 unnecessary lambda wrappers with direct references

Lambda count in store.py reduced from 22 to 11. Remaining lambdas
are genuine circular dependency breakers (ProfileStore <-> ConflictManager,
ContextAssembler <-> Retriever) — addressed in Phase 2."
```

---

## Task 4: Add Cross-Component Data Contract Tests

These tests verify that what the write path produces matches what the read
path expects — the safety net for subsequent migration phases.

**Files:**
- Create: `tests/contract/test_memory_data_contracts.py`

- [ ] **Step 1: Write data contract tests**

```python
"""Cross-component data contract tests for the memory subsystem.

These tests verify that data written by one component can be read by another.
They protect against schema drift during refactoring.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.memory.constants import EVENT_TYPES, MEMORY_TYPES, PROFILE_KEYS
from nanobot.memory.embedder import HashEmbedder
from nanobot.memory.event import MemoryEvent
from nanobot.memory.store import MemoryStore


@pytest.fixture()
def store(tmp_path: Path) -> MemoryStore:
    """Create a MemoryStore with HashEmbedder for deterministic tests."""
    return MemoryStore(tmp_path, embedding_provider="hash")


class TestWriteReadEventContract:
    """Events written by ingester are retrievable by retriever."""

    def test_ingested_event_has_required_fields(self, store: MemoryStore) -> None:
        """Every event persisted by ingester contains the fields retriever expects."""
        event = MemoryEvent(
            id="test-001",
            timestamp="2026-03-30T00:00:00Z",
            type="fact",
            summary="Python is a programming language",
            memory_type="semantic",
            stability="high",
            confidence=0.9,
            entities=["Python"],
        )
        store.ingester.append_events([event.to_dict()])

        rows = store.ingester.read_events(limit=10)
        assert len(rows) >= 1
        row = next(r for r in rows if r["id"] == "test-001")

        # Fields the retriever and scorer depend on:
        assert "id" in row
        assert "type" in row
        assert "summary" in row
        assert "timestamp" in row
        assert "status" in row
        assert "metadata" in row or row.get("metadata") is None

    def test_event_type_values_match_constants(self, store: MemoryStore) -> None:
        """All event types written by ingester are in EVENT_TYPES."""
        for event_type in EVENT_TYPES:
            event = MemoryEvent(
                id=f"type-{event_type}",
                timestamp="2026-03-30T00:00:00Z",
                type=event_type,  # type: ignore[arg-type]
                summary=f"Test event of type {event_type}",
            )
            store.ingester.append_events([event.to_dict()])

        rows = store.ingester.read_events(limit=100)
        for row in rows:
            if row["id"].startswith("type-"):
                assert row["type"] in EVENT_TYPES


class TestProfileContract:
    """Profile data written by profile_mgr is readable and well-structured."""

    def test_profile_keys_match_constants(self, store: MemoryStore) -> None:
        """Profile sections match PROFILE_KEYS."""
        profile = store.profile_mgr.read_profile()
        for key in PROFILE_KEYS:
            assert key in profile, f"Profile missing section: {key}"


class TestMemoryTypeContract:
    """Memory types flow consistently from write to read path."""

    def test_all_memory_types_are_valid(self) -> None:
        """MemoryEvent accepts all MEMORY_TYPES values."""
        for mt in MEMORY_TYPES:
            event = MemoryEvent(
                summary="test",
                memory_type=mt,  # type: ignore[arg-type]
            )
            assert event.memory_type == mt
```

Create this file at `tests/contract/test_memory_data_contracts.py`.

- [ ] **Step 2: Run contract tests**

Run: `pytest tests/contract/test_memory_data_contracts.py -v`
Expected: ALL PASS

- [ ] **Step 3: Run full validation**

Run: `make check && make test`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add tests/contract/test_memory_data_contracts.py
git commit -m "test(memory): add cross-component data contract tests

Safety net for memory subsystem refactoring. Verifies that events
written by ingester contain fields expected by retriever/scorer,
profile keys match constants, and memory types are consistent."
```

---

## Task 5: Final Verification

- [ ] **Step 1: Run full pre-push checks**

Run: `make pre-push`
Expected: ALL PASS

- [ ] **Step 2: Verify no remaining duplicated constants**

```bash
# Should return 0 matches for class-level constant definitions:
grep -rn "EVENT_TYPES\s*[:=]" nanobot/memory/ --include="*.py" | grep -v constants.py | grep -v "from.*constants"
grep -rn "MEMORY_TYPES\s*[:=]" nanobot/memory/ --include="*.py" | grep -v constants.py | grep -v "from.*constants" | grep -v event.py
grep -rn "MEMORY_STABILITY\s*[:=]" nanobot/memory/ --include="*.py" | grep -v constants.py | grep -v "from.*constants"
grep -rn "PROFILE_KEYS\s*[:=]" nanobot/memory/ --include="*.py" | grep -v constants.py | grep -v "from.*constants"
grep -rn "CONFLICT_STATUS_" nanobot/memory/ --include="*.py" | grep -v constants.py | grep -v "from.*constants" | grep -v "import"
grep -rn "EPISODIC_STATUS_" nanobot/memory/ --include="*.py" | grep -v constants.py | grep -v "from.*constants" | grep -v "import"
grep -rn "PROFILE_STATUS_" nanobot/memory/ --include="*.py" | grep -v constants.py | grep -v "from.*constants" | grep -v "import"
```

Expected: All greps return 0 matches.

- [ ] **Step 3: Verify lambda count**

```bash
grep -c "lambda" nanobot/memory/store.py
```

Expected: ~11 (circular dependency breakers only).

- [ ] **Step 4: Dispatch code review**

Use the code-reviewer subagent to review all changes before merging.
