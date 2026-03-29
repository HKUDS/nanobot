# Memory Subsystem Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `profile.py` into focused modules, extract `TokenBudgetAllocator`, add `ProfileCache` + graph memoization, and rewrite `ConsolidationOrchestrator` with `asyncio.TaskGroup`.

**Architecture:** Seven sequential tasks, each independently testable and committable. Tasks 1–3 split `profile.py`; Task 4 extracts token budget logic; Task 5 adds graph caching; Task 6 rewrites consolidation; Task 7 validates. No task breaks the build: each ships with passing tests.

**Tech Stack:** Python 3.10+, pytest, asyncio, pydantic v2, dataclasses with `slots=True`.

---

## File Map

| Action | File | Task |
|--------|------|------|
| Create | `nanobot/agent/memory/profile_io.py` | 1 |
| Modify | `nanobot/agent/memory/profile.py` → delete at end of Task 3 | 1–3 |
| Modify | `nanobot/agent/memory/conflicts.py` | 2 |
| Modify | `nanobot/agent/memory/store.py` | 1, 3, 4 |
| Create | `nanobot/agent/memory/profile_correction.py` | 3 |
| Create | `nanobot/agent/memory/token_budget.py` | 4 |
| Modify | `nanobot/agent/memory/context_assembler.py` | 4 |
| Modify | `nanobot/config/schema.py` | 4 |
| Modify | `nanobot/agent/memory/retriever.py` | 5 |
| Modify | `nanobot/agent/consolidation.py` | 6 |
| Modify | `nanobot/agent/loop.py` | 6 |
| Modify | `nanobot/agent/message_processor.py` | 6 |
| Modify | `nanobot/agent/memory/__init__.py` | 3 |
| Create | `tests/test_profile_store.py` | 1 |
| Modify | `tests/test_consolidation.py` | 6 |
| Create | `tests/test_profile_correction.py` | 3 |
| Create | `tests/test_token_budget.py` | 4 |
| Modify | `tests/test_memory_metadata_policy.py` | 4 |
| Modify | `tests/test_retriever.py` | 5 |
| Create | `tests/test_consolidation_orchestrator.py` | 6 |

---

## Task 1: ProfileCache + ProfileStore

**Goal:** Create `profile_io.py` with `ProfileCache` and `ProfileStore`. `profile.py` re-exports `ProfileStore as ProfileManager` so callers are unaffected. `read_profile()` now uses the cache.

**Context:** `ProfileManager` is in `nanobot/agent/memory/profile.py` (980 lines). The cache pattern is identical to `EventIngester`'s mtime cache. `MemoryStore` constructs it at line 123 of `store.py` as `ProfileManager(self.persistence, self.profile_file, self.mem0)`. The `store.py` reference is `self.profile_mgr`.

**Files:**
- Create: `nanobot/agent/memory/profile_io.py`
- Modify: `nanobot/agent/memory/profile.py` (add re-export alias at top)
- Modify: `nanobot/agent/memory/store.py` (change import + construction)
- Create: `tests/test_profile_store.py`

- [ ] **Step 1: Write failing tests for ProfileCache**

```python
# tests/test_profile_store.py
"""Tests for ProfileCache and ProfileStore."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nanobot.memory.profile_io import ProfileCache, ProfileStore


class TestProfileCache:
    def test_read_returns_empty_dict_when_file_missing(self, tmp_path):
        persistence = MagicMock()
        cache = ProfileCache(_path=tmp_path / "profile.json", _persistence=persistence)
        result = cache.read()
        assert result == {}
        persistence.read_json.assert_not_called()

    def test_read_loads_from_disk_on_first_call(self, tmp_path):
        profile_file = tmp_path / "profile.json"
        profile_file.write_text('{"preferences": ["tea"]}')
        persistence = MagicMock()
        persistence.read_json.return_value = {"preferences": ["tea"]}
        cache = ProfileCache(_path=profile_file, _persistence=persistence)
        result = cache.read()
        assert result == {"preferences": ["tea"]}
        persistence.read_json.assert_called_once_with(profile_file)

    def test_read_uses_cache_on_second_call(self, tmp_path):
        profile_file = tmp_path / "profile.json"
        profile_file.write_text('{"preferences": ["tea"]}')
        persistence = MagicMock()
        persistence.read_json.return_value = {"preferences": ["tea"]}
        cache = ProfileCache(_path=profile_file, _persistence=persistence)
        cache.read()
        cache.read()  # second call
        persistence.read_json.assert_called_once()  # still only one disk read

    def test_write_updates_cache_atomically(self, tmp_path):
        profile_file = tmp_path / "profile.json"
        profile_file.write_text("{}")
        persistence = MagicMock()
        persistence.read_json.return_value = {}

        def _write_json(path, data):
            path.write_text(json.dumps(data))

        persistence.write_json.side_effect = _write_json
        cache = ProfileCache(_path=profile_file, _persistence=persistence)
        data = {"preferences": ["coffee"]}
        cache.write(data)
        # next read must return the written value without hitting disk again
        persistence.read_json.reset_mock()
        result = cache.read()
        assert result == data
        persistence.read_json.assert_not_called()

    def test_invalidate_forces_reload(self, tmp_path):
        profile_file = tmp_path / "profile.json"
        profile_file.write_text('{"preferences": ["tea"]}')
        persistence = MagicMock()
        persistence.read_json.return_value = {"preferences": ["tea"]}
        cache = ProfileCache(_path=profile_file, _persistence=persistence)
        cache.read()
        cache.invalidate()
        cache.read()
        assert persistence.read_json.call_count == 2


class TestProfileStoreReadWrite:
    def _make_store(self, tmp_path):
        from unittest.mock import MagicMock

        persistence = MagicMock()
        mem0 = MagicMock()
        profile_file = tmp_path / "profile.json"
        profile_file.write_text("{}")
        persistence.read_json.return_value = None
        return ProfileStore(persistence, profile_file, mem0)

    def test_read_profile_returns_dict(self, tmp_path):
        store = self._make_store(tmp_path)
        result = store.read_profile()
        assert isinstance(result, dict)

    def test_write_profile_and_read_back(self, tmp_path):
        import json

        persistence = MagicMock()
        mem0 = MagicMock()
        profile_file = tmp_path / "profile.json"
        profile_file.write_text("{}")
        written = {}

        def _write(path, data):
            written.update(data)
            profile_file.write_text(json.dumps(data))

        def _read(path):
            text = profile_file.read_text()
            return json.loads(text)

        persistence.write_json.side_effect = _write
        persistence.read_json.side_effect = _read
        store = ProfileStore(persistence, profile_file, mem0)
        store.write_profile({"preferences": ["tea"], "stable_facts": []})
        # invalidate so next read hits disk (simulating external write)
        store._cache.invalidate()
        result = store.read_profile()
        assert result["preferences"] == ["tea"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_profile_store.py -v
```
Expected: `ImportError: cannot import name 'ProfileCache' from 'nanobot.memory.profile_io'`

- [ ] **Step 3: Create `nanobot/agent/memory/profile_io.py`**

Copy the entire content of `profile.py` into `profile_io.py`, then make two changes:

3a. Add `ProfileCache` dataclass immediately before `ProfileManager` class:

```python
# Add this import at the top (with other imports):
from dataclasses import dataclass, field

# Add ProfileCache class before ProfileManager:
@dataclass(slots=True)
class ProfileCache:
    """Mtime-aware cache for profile.json. Owned exclusively by ProfileStore."""

    _path: Path
    _persistence: MemoryPersistence

    _data: dict[str, Any] | None = field(default=None, init=False)
    _mtime: float = field(default=-1.0, init=False)

    def read(self) -> dict[str, Any]:
        """Return cached data if file unchanged, else reload from disk."""
        try:
            mtime = self._path.stat().st_mtime
        except FileNotFoundError:
            return {}
        if self._data is not None and mtime == self._mtime:
            return self._data
        self._data = self._persistence.read_json(self._path) or {}
        self._mtime = mtime
        return self._data

    def write(self, data: dict[str, Any]) -> None:
        """Write to disk and update cache atomically."""
        self._persistence.write_json(self._path, data)
        self._data = data
        try:
            self._mtime = self._path.stat().st_mtime
        except FileNotFoundError:
            self._mtime = -1.0

    def invalidate(self) -> None:
        """Force next read() to reload from disk."""
        self._data = None
        self._mtime = -1.0
```

3b. Rename `ProfileManager` to `ProfileStore` throughout `profile_io.py` (class name and docstring only — keep method names identical).

3c. In `ProfileStore.__init__`, add the cache:
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
    self.persistence = persistence
    self.profile_file = profile_file
    self.mem0 = mem0
    self._extractor: Any = extractor
    self._ingester: Any = ingester
    self._conflict_mgr: Any = conflict_mgr
    self._snapshot: Any = snapshot
    self._cache = ProfileCache(_path=profile_file, _persistence=persistence)
    self._corrector: Any = None  # wired post-construction by MemoryStore
```

3d. Replace `read_profile` body with cache read:
```python
def read_profile(self) -> dict[str, Any]:
    data = self._cache.read()
    if isinstance(data, dict) and data:
        # normalise legacy entries — same logic as before
        for key in self.PROFILE_KEYS:
            data.setdefault(key, [])
            if not isinstance(data[key], list):
                data[key] = []
        data.setdefault("conflicts", [])
        data.setdefault("last_verified_at", None)
        data.setdefault("meta", {})
        for key in self.PROFILE_KEYS:
            section_meta = data["meta"].get(key)
            if not isinstance(section_meta, dict):
                section_meta = {}
                data["meta"][key] = section_meta
            for item in data[key]:
                if not isinstance(item, str) or not item.strip():
                    continue
                norm = self._norm_text(item)
                entry = section_meta.get(norm)
                if not isinstance(entry, dict):
                    fallback_ts = data.get("updated_at") or self._utc_now_iso()
                    section_meta[norm] = {
                        "id": self._generate_belief_id(key, norm, fallback_ts),
                        "text": item,
                        "confidence": 0.65,
                        "evidence_count": 1,
                        "status": self.PROFILE_STATUS_ACTIVE,
                        "created_at": fallback_ts,
                        "last_seen_at": fallback_ts,
                    }
                elif not entry.get("id"):
                    created = entry.get("last_seen_at") or self._utc_now_iso()
                    entry.setdefault("created_at", created)
                    entry["id"] = self._generate_belief_id(key, norm, entry["created_at"])
        return data
    if self.profile_file.exists() and data is not None and not data:
        pass  # empty file — not an error, just use defaults below
    elif self.profile_file.exists():
        from loguru import logger
        logger.warning("Failed to parse memory profile, resetting")
    return {
        "preferences": [], "stable_facts": [], "active_projects": [],
        "relationships": [], "constraints": [], "conflicts": [],
        "last_verified_at": None, "meta": {},
    }
```

3e. Replace `write_profile` body with cache write:
```python
def write_profile(self, profile: dict[str, Any]) -> None:
    self._cache.write(profile)
```

3f. Add `apply_live_user_correction` facade at the end of `ProfileStore` (this replaces the full method body during Step 3; for now keep the original body intact in `profile_io.py` and add the `_corrector` delegation separately in Task 3):

> **Note:** For Task 1, `ProfileStore` in `profile_io.py` is a FULL COPY of `ProfileManager` (all methods) with the cache added. The method bodies are unchanged. The `CorrectionOrchestrator` split happens in Task 3.

- [ ] **Step 4: Update `profile.py` to re-export from `profile_io`**

Replace the entire content of `profile.py` with:

```python
"""Backward-compat shim: re-exports ProfileStore as ProfileManager.

This file will be deleted after all imports are migrated. Do not add new
code here.
"""
from __future__ import annotations

from .profile_io import (  # noqa: F401
    PROFILE_KEYS,
    PROFILE_STATUS_ACTIVE,
    PROFILE_STATUS_CONFLICTED,
    PROFILE_STATUS_STALE,
    ProfileCache,
    ProfileStore,
    ProfileStore as ProfileManager,
)

__all__ = [
    "PROFILE_KEYS",
    "PROFILE_STATUS_ACTIVE",
    "PROFILE_STATUS_CONFLICTED",
    "PROFILE_STATUS_STALE",
    "ProfileCache",
    "ProfileManager",
    "ProfileStore",
]
```

- [ ] **Step 5: Update `store.py` to import from `profile_io`**

In `nanobot/agent/memory/store.py`:
- Change `from .profile import ProfileManager` → `from .profile_io import ProfileStore`
- Change `self.profile_mgr = ProfileManager(...)` → `self.profile_mgr = ProfileStore(...)`

- [ ] **Step 6: Run tests to verify they pass**

```bash
make lint && make typecheck
pytest tests/test_profile_store.py tests/test_agent_loop.py -v
```
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add nanobot/agent/memory/profile_io.py nanobot/agent/memory/profile.py \
        nanobot/agent/memory/store.py tests/test_profile_store.py
git commit -m "refactor: extract ProfileStore + ProfileCache from ProfileManager

ProfileCache provides mtime-aware caching: read_profile() now avoids
redundant disk reads within a process. profile.py becomes a compat shim;
store.py imports ProfileStore from profile_io directly.
"
```

---

## Task 2: Move Conflict Detection to ConflictManager

**Goal:** Move `_conflict_pair`, `_apply_profile_updates`, `_has_open_conflict` from `ProfileStore` into `ConflictManager`. `ProfileStore` calls `self._conflict_mgr.*` for these. No behavior change.

**Context:** `ConflictManager` is in `nanobot/agent/memory/conflicts.py` (line 35). It already receives `profile_mgr` in its constructor (line 51). The three methods currently live in `ProfileStore` (`profile_io.py` after Task 1). The moving methods' internal calls must be re-prefixed: all `self.*` calls inside the moved bodies become `self.profile_store.*` except `self._conflict_pair` which remains `self._conflict_pair` (it's also moving to `ConflictManager`).

**Files:**
- Modify: `nanobot/agent/memory/conflicts.py`
- Modify: `nanobot/agent/memory/profile_io.py`

- [ ] **Step 1: Write failing tests for moved methods**

Add to `tests/test_profile_store.py` a new class (or create a separate file `tests/test_conflict_detection.py`):

```python
# Append to tests/test_profile_store.py

class TestConflictDetectionInConflictManager:
    """Verify conflict-detection methods are accessible via ConflictManager."""

    def _make_conflict_mgr(self, tmp_path):
        from unittest.mock import MagicMock
        from nanobot.memory.conflicts import ConflictManager
        from nanobot.memory.profile_io import ProfileStore

        persistence = MagicMock()
        mem0 = MagicMock()
        profile_file = tmp_path / "profile.json"
        profile_file.write_text("{}")
        persistence.read_json.return_value = {}
        store = ProfileStore(persistence, profile_file, mem0)
        mem0_adapter = MagicMock()
        mgr = ConflictManager(store, mem0_adapter)
        store._conflict_mgr = mgr
        return mgr, store

    def test_conflict_pair_detects_negation(self, tmp_path):
        mgr, _ = self._make_conflict_mgr(tmp_path)
        # "I like coffee" vs "I don't like coffee" → conflict
        assert mgr._conflict_pair("I like coffee", "I don't like coffee") is True

    def test_conflict_pair_same_value_no_conflict(self, tmp_path):
        mgr, _ = self._make_conflict_mgr(tmp_path)
        assert mgr._conflict_pair("likes tea", "likes tea") is False

    def test_has_open_conflict_false_when_none(self, tmp_path):
        mgr, _ = self._make_conflict_mgr(tmp_path)
        profile = {"conflicts": [], "preferences": [], "meta": {}}
        assert mgr.has_open_conflict(profile, "preferences") is False

    def test_apply_profile_updates_adds_new_values(self, tmp_path):
        mgr, _ = self._make_conflict_mgr(tmp_path)
        profile = {
            "preferences": [], "stable_facts": [], "active_projects": [],
            "relationships": [], "constraints": [], "conflicts": [],
            "meta": {"preferences": {}, "stable_facts": {}, "active_projects": {},
                     "relationships": {}, "constraints": {}},
        }
        updates = {"preferences": ["likes hiking"]}
        added, conflicts, touched = mgr.apply_profile_updates(
            profile, updates, enable_contradiction_check=False
        )
        assert added >= 1
        assert "likes hiking" in profile["preferences"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_profile_store.py::TestConflictDetectionInConflictManager -v
```
Expected: `AttributeError: 'ConflictManager' object has no attribute '_conflict_pair'`

- [ ] **Step 3: Move methods to `ConflictManager`**

In `nanobot/agent/memory/conflicts.py`:

3a. Rename `ConflictManager.__init__` parameter `profile_mgr: ProfileManager` → `profile_store: ProfileStore` and update the stored reference: `self.profile_mgr = profile_store` (keep the attribute name `profile_mgr` for backward compat with `resolve_conflict_details` which uses `self.profile_mgr.*`).

3b. Add these three methods to `ConflictManager` (copy bodies from `profile_io.py`, replacing `self.` prefixes on profile-store methods with `self.profile_mgr.`):

```python
# In ConflictManager:

def _conflict_pair(self, old_value: str, new_value: str) -> bool:
    """Return True if old_value and new_value are semantically contradictory."""
    old_n = self._norm_text(old_value)
    new_n = self._norm_text(new_value)
    if not old_n or not new_n or old_n == new_n:
        return False
    old_has_not = " not " in f" {old_n} " or "n't" in old_n
    new_has_not = " not " in f" {new_n} " or "n't" in new_n
    if old_has_not == new_has_not:
        return False
    old_tokens = self._tokenize(old_n.replace("not", ""))
    new_tokens = self._tokenize(new_n.replace("not", ""))
    if not old_tokens or not new_tokens:
        return False
    overlap = len(old_tokens & new_tokens) / max(len(old_tokens | new_tokens), 1)
    return overlap >= 0.55

def has_open_conflict(self, profile: dict[str, Any], key: str) -> bool:
    """Return True if any open conflict exists for the given profile key."""
    # Copy the body of _has_open_conflict from ProfileManager (line 748 of profile.py).
    # The method scans profile["conflicts"] for any entry with field==key and
    # status in {"open", "needs_user"}.
    for c in profile.get("conflicts", []):
        if str(c.get("field", "")) != key:
            continue
        status = str(c.get("status", "")).lower()
        if status in {"open", "needs_user"}:
            return True
    return False

def apply_profile_updates(
    self,
    profile: dict[str, Any],
    updates: dict[str, list[str]],
    *,
    enable_contradiction_check: bool,
    source_event_ids: list[str] | None = None,
) -> tuple[int, int, int]:
    """Apply profile updates, detecting contradictions. Returns (added, conflicts, touched)."""
    # Copy the body of _apply_profile_updates from ProfileManager, replacing
    # self.PROFILE_KEYS      → self.profile_mgr.PROFILE_KEYS
    # self._to_str_list(…)   → self.profile_mgr._to_str_list(…)
    # self._meta_entry(…)    → self.profile_mgr._meta_entry(…)
    # self._touch_meta_entry(…) → self.profile_mgr._touch_meta_entry(…)
    # self._add_belief_to_profile(…) → self.profile_mgr._add_belief_to_profile(…)
    # self._update_belief_in_profile(…) → self.profile_mgr._update_belief_in_profile(…)
    # self._norm_text(…)     → self._norm_text(…)  ← already on ConflictManager
    # self._conflict_pair(…) → self._conflict_pair(…)  ← already moved
    # self.PROFILE_STATUS_ACTIVE  → self.profile_mgr.PROFILE_STATUS_ACTIVE
    # self.PROFILE_STATUS_STALE   → self.profile_mgr.PROFILE_STATUS_STALE
    # (See profile.py lines 625–747 for the full body to copy)
    ...
```

> **Important implementation note:** For `apply_profile_updates`, copy the **full method body** from `ProfileManager._apply_profile_updates` (lines 625–747 of `profile.py`). Replace every `self.X` call where `X` is a ProfileManager method/attribute with `self.profile_mgr.X`. The exceptions are: `self._norm_text`, `self._utc_now_iso`, `self._safe_float`, `self._tokenize` (shared helpers already on ConflictManager), and `self._conflict_pair` (just moved here).

3c. Add missing imports to `conflicts.py` at the top:
```python
# Add to TYPE_CHECKING block:
from .profile_io import ProfileStore
```

3d. Add `_norm_text`, `_utc_now_iso` as shared helpers on ConflictManager if not already present (they come from `.helpers`):
```python
# Already imported in conflicts.py via from .helpers import ...
# Verify the import line includes: _norm_text, _tokenize, _utc_now_iso
```

- [ ] **Step 4: Update `ProfileStore` to delegate to `ConflictManager`**

In `nanobot/agent/memory/profile_io.py`:

- Keep `_conflict_pair`, `_apply_profile_updates`, `_has_open_conflict` in the file for now (they'll be deleted in Task 3 after profile.py is removed). For Task 2, simply verify `ConflictManager` has the methods.
- In `ProfileStore._apply_profile_updates`, replace the body with a delegation:
```python
def _apply_profile_updates(
    self,
    profile: dict[str, Any],
    updates: dict[str, list[str]],
    *,
    enable_contradiction_check: bool,
    source_event_ids: list[str] | None = None,
) -> tuple[int, int, int]:
    assert self._conflict_mgr is not None, "_conflict_mgr not wired"
    return self._conflict_mgr.apply_profile_updates(
        profile, updates,
        enable_contradiction_check=enable_contradiction_check,
        source_event_ids=source_event_ids,
    )
```

- [ ] **Step 5: Run all tests**

```bash
make lint && make typecheck
pytest tests/test_profile_store.py tests/test_agent_loop.py -v
```
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add nanobot/agent/memory/conflicts.py nanobot/agent/memory/profile_io.py \
        tests/test_profile_store.py
git commit -m "refactor: move conflict-detection methods to ConflictManager

_conflict_pair, apply_profile_updates, _has_open_conflict now live on
ConflictManager. ProfileStore delegates _apply_profile_updates to
self._conflict_mgr.apply_profile_updates. No behavior change.
"
```

---

## Task 3: CorrectionOrchestrator + Delete profile.py

**Goal:** Extract `apply_live_user_correction` into `CorrectionOrchestrator` in `profile_correction.py`. `ProfileStore` exposes a facade. Delete `profile.py`. Update `__init__.py`.

**Context:** `apply_live_user_correction` (line 797 of `profile.py`, now in `profile_io.py`) uses `self._extractor`, `self._ingester`, `self._conflict_mgr`, `self._snapshot`. These become constructor injections in `CorrectionOrchestrator`. `MemoryStore` constructs `CorrectionOrchestrator` and wires it into `ProfileStore._corrector`.

**Files:**
- Create: `nanobot/agent/memory/profile_correction.py`
- Modify: `nanobot/agent/memory/profile_io.py`
- Modify: `nanobot/agent/memory/store.py`
- Modify: `nanobot/agent/memory/__init__.py`
- Delete: `nanobot/agent/memory/profile.py`
- Modify: `nanobot/agent/memory/context_assembler.py` (update import before profile.py is deleted)
- Create: `tests/test_profile_correction.py`

- [ ] **Step 1: Write failing tests for CorrectionOrchestrator**

```python
# tests/test_profile_correction.py
"""Tests for CorrectionOrchestrator."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.memory.profile_correction import CorrectionOrchestrator
from nanobot.memory.profile_io import ProfileStore


def _make_profile_store(tmp_path: Path) -> ProfileStore:
    import json
    persistence = MagicMock()
    mem0 = MagicMock()
    profile_file = tmp_path / "profile.json"
    profile_file.write_text("{}")
    persistence.read_json.return_value = None
    return ProfileStore(persistence, profile_file, mem0)


class TestCorrectionOrchestrator:
    def test_apply_returns_dict_with_expected_keys(self, tmp_path):
        store = _make_profile_store(tmp_path)
        extractor = MagicMock()
        extractor.extract_explicit_preference_corrections.return_value = []
        extractor.extract_explicit_fact_corrections.return_value = []
        corrector = CorrectionOrchestrator(
            profile_store=store,
            extractor=extractor,
            ingester=MagicMock(),
            conflict_mgr=MagicMock(),
            snapshot=MagicMock(),
        )
        result = corrector.apply_live_user_correction("some text")
        assert isinstance(result, dict)
        assert "applied" in result
        assert "conflicts" in result

    def test_apply_returns_zero_counts_when_no_corrections_extracted(self, tmp_path):
        store = _make_profile_store(tmp_path)
        extractor = MagicMock()
        extractor.extract_explicit_preference_corrections.return_value = []
        extractor.extract_explicit_fact_corrections.return_value = []
        corrector = CorrectionOrchestrator(
            profile_store=store,
            extractor=extractor,
            ingester=MagicMock(),
            conflict_mgr=MagicMock(),
            snapshot=MagicMock(),
        )
        result = corrector.apply_live_user_correction("random text with no corrections")
        assert result["applied"] == 0
        assert result["conflicts"] == 0

    def test_profile_store_facade_delegates_to_corrector(self, tmp_path):
        store = _make_profile_store(tmp_path)
        corrector = MagicMock()
        corrector.apply_live_user_correction.return_value = {"applied": 1, "conflicts": 0}
        store._corrector = corrector
        result = store.apply_live_user_correction("I prefer tea")
        corrector.apply_live_user_correction.assert_called_once_with(
            "I prefer tea", channel="", chat_id="", enable_contradiction_check=True
        )
        assert result == {"applied": 1, "conflicts": 0}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_profile_correction.py -v
```
Expected: `ImportError: cannot import name 'CorrectionOrchestrator' from 'nanobot.memory.profile_correction'`

- [ ] **Step 3: Create `profile_correction.py`**

```python
# nanobot/agent/memory/profile_correction.py
"""CorrectionOrchestrator: live user correction pipeline.

Extracted from ProfileManager (LAN-XXX). Receives all dependencies
via constructor injection — no back-references to MemoryStore.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from .conflicts import ConflictManager
    from .extractor import MemoryExtractor
    from .ingester import EventIngester
    from .profile_io import ProfileStore
    from .snapshot import MemorySnapshot


class CorrectionOrchestrator:
    """Owns the apply_live_user_correction pipeline."""

    def __init__(
        self,
        *,
        profile_store: ProfileStore,
        extractor: MemoryExtractor,
        ingester: EventIngester,
        conflict_mgr: ConflictManager,
        snapshot: MemorySnapshot,
    ) -> None:
        self._profile_store = profile_store
        self._extractor = extractor
        self._ingester = ingester
        self._conflict_mgr = conflict_mgr
        self._snapshot = snapshot

    def apply_live_user_correction(
        self,
        content: str,
        *,
        channel: str = "",
        chat_id: str = "",
        enable_contradiction_check: bool = True,
    ) -> dict[str, Any]:
        """Apply live user correction to the profile.

        This is the body of the former ProfileManager.apply_live_user_correction.
        All self.* calls are re-routed through self._profile_store.* or
        self._extractor.* as appropriate.
        """
        # Copy the full body of ProfileManager.apply_live_user_correction
        # (profile.py lines 797–980), replacing:
        #   self._extractor     → self._extractor       (unchanged)
        #   self.read_profile() → self._profile_store.read_profile()
        #   self.write_profile  → self._profile_store.write_profile
        #   self._to_str_list   → self._profile_store._to_str_list
        #   self._norm_text     → self._profile_store._norm_text
        #   self._meta_entry    → self._profile_store._meta_entry
        #   self._touch_meta_entry → self._profile_store._touch_meta_entry
        #   self._add_belief_to_profile → self._profile_store._add_belief_to_profile
        #   self._find_mem0_id_for_text → self._profile_store._find_mem0_id_for_text
        #   self._has_open_conflict → self._conflict_mgr.has_open_conflict
        #   self.PROFILE_STATUS_* → self._profile_store.PROFILE_STATUS_*
        #   self._utc_now_iso   → self._profile_store._utc_now_iso
        #   self._ingester      → self._ingester         (unchanged)
        #   self._snapshot      → self._snapshot          (unchanged)
        text = str(content or "").strip()
        if not text:
            return {"applied": 0, "conflicts": 0, "events": 0, "needs_user": 0, "question": None}

        preference_corrections = self._extractor.extract_explicit_preference_corrections(text)
        fact_corrections = self._extractor.extract_explicit_fact_corrections(text)
        if not preference_corrections and not fact_corrections:
            return {"applied": 0, "conflicts": 0, "events": 0, "needs_user": 0, "question": None}

        # Paste full body from profile.py apply_live_user_correction here,
        # with the substitutions listed above.
        # The _apply_field_corrections closure moves inline here.
        raise NotImplementedError("paste body from ProfileManager.apply_live_user_correction")
```

> **Implementation note:** Replace the `raise NotImplementedError(...)` with the complete body of `ProfileManager.apply_live_user_correction` (lines 805–980 of `profile.py` / equivalent in `profile_io.py`). Perform the substitutions listed in the comments above. The inner `_apply_field_corrections` closure (line 820) is pasted verbatim but its `self.*` calls are re-routed the same way.

- [ ] **Step 4: Update `ProfileStore` to expose the facade**

In `nanobot/agent/memory/profile_io.py`, replace `apply_live_user_correction` body with:

```python
def apply_live_user_correction(
    self,
    content: str,
    *,
    channel: str = "",
    chat_id: str = "",
    enable_contradiction_check: bool = True,
) -> dict[str, Any]:
    """Facade — delegates to CorrectionOrchestrator wired at store construction."""
    assert self._corrector is not None, "_corrector not wired by MemoryStore"
    return self._corrector.apply_live_user_correction(
        content,
        channel=channel,
        chat_id=chat_id,
        enable_contradiction_check=enable_contradiction_check,
    )
```

Also remove the now-unused `_apply_field_corrections` method from `ProfileStore` (it moved into `CorrectionOrchestrator`).

- [ ] **Step 5: Wire `CorrectionOrchestrator` in `store.py`**

In `nanobot/agent/memory/store.py`, after the `profile_mgr` construction and after all subsystems are ready, add:

```python
# Wire CorrectionOrchestrator (after conflict_mgr, ingester, extractor, snapshot exist)
from .profile_correction import CorrectionOrchestrator
self.profile_mgr._corrector = CorrectionOrchestrator(
    profile_store=self.profile_mgr,
    extractor=self.extractor,
    ingester=self.ingester,
    conflict_mgr=self.conflict_mgr,
    snapshot=self.snapshot,
)
```

Find where `MemoryStore.__init__` wires `self.profile_mgr._extractor = self.extractor` (and similar lines) — replace all those post-construction wiring lines with the single `CorrectionOrchestrator` construction above.

- [ ] **Step 6: Update `__init__.py` to export `ProfileStore`**

In `nanobot/agent/memory/__init__.py`:
- Change `from .profile import ProfileManager` → `from .profile_io import ProfileStore`
- Add `ProfileStore as ProfileManager,` alias in the import so `ProfileManager` still works
- Update `__all__` to include `"ProfileStore"` alongside `"ProfileManager"`

The import becomes:
```python
from .profile_io import ProfileStore
from .profile_io import ProfileStore as ProfileManager  # backward-compat alias
```

- [ ] **Step 7: Update `context_assembler.py` import before deleting `profile.py`**

In `nanobot/agent/memory/context_assembler.py`, find the import of `ProfileManager`:
```python
from .profile import ProfileManager
```
Change it to:
```python
from .profile_io import ProfileStore as ProfileManager
```
This must happen before `profile.py` is deleted to avoid breaking the build.

- [ ] **Step 8: Delete `profile.py`**

```bash
git rm nanobot/agent/memory/profile.py
```

Verify no remaining import of `profile.py` (should be zero after the shim was updated in Step 6):
```bash
grep -r "from .profile import\|from nanobot.memory.profile import" nanobot/ tests/
```
Expected: no output (all imports now come from `profile_io`).

- [ ] **Step 9: Run all tests**

```bash
make lint && make typecheck
pytest tests/test_profile_correction.py tests/test_profile_store.py tests/test_agent_loop.py -v
```
Expected: All pass.

- [ ] **Step 10: Commit**

```bash
git add nanobot/agent/memory/profile_correction.py \
        nanobot/agent/memory/profile_io.py \
        nanobot/agent/memory/store.py \
        nanobot/agent/memory/__init__.py \
        nanobot/agent/memory/context_assembler.py \
        tests/test_profile_correction.py
git commit -m "refactor: extract CorrectionOrchestrator; delete profile.py

apply_live_user_correction moves to CorrectionOrchestrator in
profile_correction.py. ProfileStore exposes a thin facade. profile.py
is deleted; all callers import from profile_io directly.
"
```

---

## Task 4: TokenBudgetAllocator and Config

**Goal:** Extract `_SECTION_PRIORITY_WEIGHTS` + `_allocate_section_budgets` into `TokenBudgetAllocator` in `token_budget.py`. Add `MemorySectionWeights` + `memory_section_weights` to config schema. Wire into `ContextAssembler` and `MemoryStore`.

**Context:** `_allocate_section_budgets` is a `@classmethod` on `ContextAssembler` (line 552 of `context_assembler.py`). It takes `(total_budget, intent, section_sizes)` and does a two-pass capped allocation. The new `TokenBudgetAllocator.allocate()` intentionally simplifies this to pure proportional allocation (no section-size cap — the simplification is documented in the spec). `tests/test_memory_metadata_policy.py` calls `_allocate_section_budgets` directly (lines 584, 609, 627) and must be rewritten.

**Files:**
- Create: `nanobot/agent/memory/token_budget.py`
- Modify: `nanobot/agent/memory/context_assembler.py`
- Modify: `nanobot/agent/memory/store.py`
- Modify: `nanobot/config/schema.py`
- Create: `tests/test_token_budget.py`
- Modify: `tests/test_memory_metadata_policy.py`

- [ ] **Step 1: Write failing tests for TokenBudgetAllocator**

```python
# tests/test_token_budget.py
"""Tests for TokenBudgetAllocator and SectionBudget."""
from __future__ import annotations

import pytest

from nanobot.memory.token_budget import (
    DEFAULT_SECTION_WEIGHTS,
    SectionBudget,
    TokenBudgetAllocator,
)


class TestTokenBudgetAllocator:
    def test_allocate_returns_section_budget_instance(self):
        allocator = TokenBudgetAllocator(DEFAULT_SECTION_WEIGHTS)
        result = allocator.allocate(900, "fact_lookup")
        assert isinstance(result, SectionBudget)

    def test_allocate_total_does_not_exceed_budget(self):
        allocator = TokenBudgetAllocator(DEFAULT_SECTION_WEIGHTS)
        result = allocator.allocate(900, "fact_lookup")
        total = (
            result.long_term + result.profile + result.semantic
            + result.episodic + result.reflection + result.graph + result.unresolved
        )
        assert total <= 900

    def test_allocate_all_sections_non_negative(self):
        allocator = TokenBudgetAllocator(DEFAULT_SECTION_WEIGHTS)
        for intent in DEFAULT_SECTION_WEIGHTS:
            result = allocator.allocate(500, intent)
            for field in ("long_term", "profile", "semantic", "episodic",
                          "reflection", "graph", "unresolved"):
                assert getattr(result, field) >= 0, f"{field} negative for intent={intent}"

    def test_unknown_intent_falls_back_to_fact_lookup(self):
        allocator = TokenBudgetAllocator(DEFAULT_SECTION_WEIGHTS)
        result_unknown = allocator.allocate(900, "nonexistent_intent")
        result_fact = allocator.allocate(900, "fact_lookup")
        assert result_unknown == result_fact

    def test_config_override_replaces_intent_weights(self):
        custom_weights = {
            **DEFAULT_SECTION_WEIGHTS,
            "fact_lookup": {
                "long_term": 1.0, "profile": 0.0, "semantic": 0.0,
                "episodic": 0.0, "reflection": 0.0, "graph": 0.0, "unresolved": 0.0,
            },
        }
        allocator = TokenBudgetAllocator(custom_weights)
        result = allocator.allocate(900, "fact_lookup")
        assert result.long_term > 0
        assert result.profile == 0

    def test_section_budget_is_frozen_dataclass(self):
        budget = SectionBudget(
            long_term=100, profile=50, semantic=80,
            episodic=20, reflection=0, graph=60, unresolved=10,
        )
        with pytest.raises((AttributeError, TypeError)):
            budget.long_term = 999  # type: ignore[misc]

    def test_allocate_proportional_higher_weight_gets_more_tokens(self):
        # fact_lookup weights: long_term=0.28 > profile=0.23
        allocator = TokenBudgetAllocator(DEFAULT_SECTION_WEIGHTS)
        result = allocator.allocate(1000, "fact_lookup")
        assert result.long_term >= result.profile
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_token_budget.py -v
```
Expected: `ImportError: cannot import name 'TokenBudgetAllocator' from 'nanobot.memory.token_budget'`

- [ ] **Step 3: Create `token_budget.py`**

```python
# nanobot/agent/memory/token_budget.py
"""TokenBudgetAllocator: pure proportional token budget allocation.

Extracted from ContextAssembler._allocate_section_budgets (LAN-XXX).
No I/O, no subsystem dependencies — pure logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Default weights mirror _SECTION_PRIORITY_WEIGHTS from context_assembler.py.
# Keys are intent strings from RetrievalPlanner.infer_retrieval_intent().
DEFAULT_SECTION_WEIGHTS: dict[str, dict[str, float]] = {
    "fact_lookup": {
        "long_term": 0.28, "profile": 0.23, "semantic": 0.20,
        "episodic": 0.05, "reflection": 0.00, "graph": 0.19, "unresolved": 0.05,
    },
    "debug_history": {
        "long_term": 0.15, "profile": 0.10, "semantic": 0.10,
        "episodic": 0.35, "reflection": 0.05, "graph": 0.15, "unresolved": 0.10,
    },
    "planning": {
        "long_term": 0.15, "profile": 0.15, "semantic": 0.20,
        "episodic": 0.20, "reflection": 0.05, "graph": 0.15, "unresolved": 0.10,
    },
    "reflection": {
        "long_term": 0.15, "profile": 0.10, "semantic": 0.15,
        "episodic": 0.10, "reflection": 0.25, "graph": 0.15, "unresolved": 0.10,
    },
    "constraints_lookup": {
        "long_term": 0.19, "profile": 0.28, "semantic": 0.24,
        "episodic": 0.05, "reflection": 0.00, "graph": 0.19, "unresolved": 0.05,
    },
    "rollout_status": {
        "long_term": 0.25, "profile": 0.15, "semantic": 0.30,
        "episodic": 0.00, "reflection": 0.00, "graph": 0.20, "unresolved": 0.10,
    },
    "conflict_review": {
        "long_term": 0.15, "profile": 0.20, "semantic": 0.20,
        "episodic": 0.15, "reflection": 0.00, "graph": 0.20, "unresolved": 0.10,
    },
}

_SECTION_NAMES = ("long_term", "profile", "semantic", "episodic",
                  "reflection", "graph", "unresolved")


@dataclass(frozen=True, slots=True)
class SectionBudget:
    """Per-section token allocations for a single retrieval call."""

    long_term: int
    profile: int
    semantic: int
    episodic: int
    reflection: int
    graph: int
    unresolved: int


class TokenBudgetAllocator:
    """Allocates a total token budget proportionally across memory sections.

    Weights are normalised to sum to 1.0 at allocation time, so only
    relative ratios matter. Unknown intents fall back to 'fact_lookup'.
    All allocations are clamped to >= 0.
    """

    def __init__(self, weights: dict[str, dict[str, float]]) -> None:
        self._weights = weights

    def allocate(self, total_tokens: int, intent: str) -> SectionBudget:
        """Return a SectionBudget distributing total_tokens by intent weights."""
        weight_map = self._weights.get(intent, self._weights.get("fact_lookup", {}))
        total_weight = sum(w for w in weight_map.values() if w > 0)
        if total_weight == 0:
            return SectionBudget(**{s: 0 for s in _SECTION_NAMES})  # type: ignore[arg-type]
        allocations: dict[str, int] = {}
        for section in _SECTION_NAMES:
            w = weight_map.get(section, 0.0)
            allocations[section] = max(0, int(total_tokens * w / total_weight)) if w > 0 else 0
        return SectionBudget(**allocations)  # type: ignore[arg-type]
```

- [ ] **Step 4: Run token_budget tests**

```bash
pytest tests/test_token_budget.py -v
```
Expected: All pass.

- [ ] **Step 5: Add `MemorySectionWeights` to `config/schema.py`**

In `nanobot/config/schema.py`, add before `class AgentDefaults`:

```python
class MemorySectionWeights(Base):
    """Per-section token budget weights for one retrieval intent.

    Values are normalised to sum to 1.0 at allocation time — only relative
    ratios matter. An empty dict means 'use DEFAULT_SECTION_WEIGHTS'.
    """
    long_term: float = Field(default=0.0, ge=0.0)
    profile: float = Field(default=0.0, ge=0.0)
    semantic: float = Field(default=0.0, ge=0.0)
    episodic: float = Field(default=0.0, ge=0.0)
    reflection: float = Field(default=0.0, ge=0.0)
    graph: float = Field(default=0.0, ge=0.0)
    unresolved: float = Field(default=0.0, ge=0.0)
```

In `AgentDefaults` (line ~160), add:
```python
memory_section_weights: dict[str, MemorySectionWeights] = Field(default_factory=dict)
```

In `AgentConfig` (line ~220), add the same field with the same default:
```python
memory_section_weights: dict[str, MemorySectionWeights] = Field(default_factory=dict)
```

Also update `AgentConfig.from_defaults` to copy the new field (find the copy block and add `memory_section_weights=defaults.memory_section_weights`).

- [ ] **Step 6: Wire `TokenBudgetAllocator` into `MemoryStore` and `ContextAssembler`**

In `nanobot/agent/memory/store.py`:

6a. Add import:
```python
from .token_budget import DEFAULT_SECTION_WEIGHTS, TokenBudgetAllocator
```

6b. In `MemoryStore.__init__`, before constructing `ContextAssembler`, build the allocator:
```python
# Merge config overrides on top of defaults
_weights = {**DEFAULT_SECTION_WEIGHTS}
for _intent, _override in (config.memory_section_weights if config else {}).items():
    _weights[_intent] = _override.model_dump()
self._budget_allocator = TokenBudgetAllocator(_weights)
```

6c. Pass `budget_allocator` to both `ContextAssembler` construction sites:
- In `__init__` (line ~129): `ContextAssembler(profile_mgr=..., ..., budget_allocator=self._budget_allocator)`
- In `_ensure_assembler()` (line ~320): same

> **Note:** `MemoryStore.__init__` currently receives a `workspace` path only, not a `config` object. Check how config values are passed — if `config` is not available at construction time, default to `{}` for the weights and document the limitation. Look at how `memory_window` is accessed: it is passed at consolidation call-time from `AgentLoop.config.memory_window`. For this task, use `DEFAULT_SECTION_WEIGHTS` always (no config override wiring is needed if config is not injected here). Mark with a TODO comment:
> `# TODO: pass config.memory_section_weights when MemoryStore receives config`

- [ ] **Step 7: Update `ContextAssembler.__init__` to accept `budget_allocator`**

In `nanobot/agent/memory/context_assembler.py`:

7a. Add parameter to `__init__` (after the keyword-only params):
```python
budget_allocator: TokenBudgetAllocator | None = None,
```
And store it:
```python
self._budget = budget_allocator
```

7b. In `build()`, replace the call to `self._allocate_section_budgets(budget, intent, section_sizes)` (line ~269) with:
```python
if self._budget is not None:
    _alloc = self._budget.allocate(budget, intent)
    section_budgets = {
        "long_term": _alloc.long_term, "profile": _alloc.profile,
        "semantic": _alloc.semantic, "episodic": _alloc.episodic,
        "reflection": _alloc.reflection, "graph": _alloc.graph,
        "unresolved": _alloc.unresolved,
    }
else:
    section_budgets = self._allocate_section_budgets(budget, intent, section_sizes)
```
This preserves backward compat for tests that construct `ContextAssembler` without a `budget_allocator`.

7c. Add import:
```python
from .token_budget import TokenBudgetAllocator
```

- [ ] **Step 8: Migrate tests in `test_memory_metadata_policy.py`**

Find lines 584, 609, 627 which call `ContextAssembler._allocate_section_budgets(budget, intent, sizes)`. Replace each call with `TokenBudgetAllocator(DEFAULT_SECTION_WEIGHTS).allocate(budget, intent)` and update assertions from dict-key style (`alloc["long_term"]`) to attribute style (`alloc.long_term`). Tests that verified the two-pass cap behaviour (`test_allocate_section_budgets_caps_at_actual_size`, `test_allocate_section_budgets_redistributes_surplus`) must be rewritten to test proportional allocation instead:

```python
# Replace cap test with proportional test
def test_allocate_proportional_respects_zero_weight(self):
    from nanobot.memory.token_budget import DEFAULT_SECTION_WEIGHTS, TokenBudgetAllocator
    allocator = TokenBudgetAllocator(DEFAULT_SECTION_WEIGHTS)
    result = allocator.allocate(900, "fact_lookup")
    # reflection weight is 0.0 for fact_lookup
    assert result.reflection == 0
```

- [ ] **Step 9: Run all affected tests**

```bash
make lint && make typecheck
pytest tests/test_token_budget.py tests/test_memory_metadata_policy.py tests/test_agent_loop.py -v
```
Expected: All pass.

- [ ] **Step 10: Commit**

```bash
git add nanobot/agent/memory/token_budget.py \
        nanobot/agent/memory/context_assembler.py \
        nanobot/agent/memory/store.py \
        nanobot/config/schema.py \
        tests/test_token_budget.py \
        tests/test_memory_metadata_policy.py
git commit -m "feat: extract TokenBudgetAllocator; add MemorySectionWeights config

TokenBudgetAllocator replaces ContextAssembler._allocate_section_budgets.
Uses simple proportional allocation (no two-pass cap). Section weights
are configurable via memory_section_weights in agent config.
"
```

---

## Task 5: Graph Entity Memoization

**Goal:** Add `_graph_cache` to `MemoryRetriever` so `_collect_graph_entity_names` does not repeat the graph traversal for the same entity set within one `retrieve()` call.

**Context:** `_collect_graph_entity_names(self, query: str, events: list[dict])` is at line 957 of `retriever.py`. It computes `query_entities = {e.lower() for e in self._extractor._extract_entities(query)}`, then calls `self._graph.get_related_entity_names_sync(query_entities, depth=2)`. The cache key is `frozenset(query_entities)`. The cache is reset at the top of every `retrieve()` call and also initialized in `__init__`.

**Files:**
- Modify: `nanobot/agent/memory/retriever.py`
- Modify: `tests/test_retriever.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_retriever.py` (find existing test class or add a new one):

```python
class TestGraphEntityCache:
    """Graph entity name cache is reset per retrieve() call."""

    def _make_retriever_with_graph(self):
        from unittest.mock import MagicMock, patch
        from nanobot.memory.retriever import MemoryRetriever

        mem0 = MagicMock()
        graph = MagicMock()
        graph.enabled = True
        graph.get_related_entity_names_sync.return_value = {"alice", "bob"}
        planner = MagicMock()
        reranker = MagicMock()
        reranker.rerank.side_effect = lambda items, **kw: items
        profile_mgr = MagicMock()
        profile_mgr.read_profile.return_value = {}
        extractor = MagicMock()
        extractor._extract_entities.return_value = ["coffee"]

        retriever = MemoryRetriever(
            mem0=mem0,
            graph=graph,
            planner=planner,
            reranker=reranker,
            profile_mgr=profile_mgr,
            rollout={"enabled": True},
            read_events_fn=lambda **kw: [],
            extractor=extractor,
        )
        return retriever

    def test_graph_cache_initialized_in_init(self):
        r = self._make_retriever_with_graph()
        assert hasattr(r, "_graph_cache")
        assert r._graph_cache == {}

    def test_same_entities_use_cache_within_retrieve(self):
        r = self._make_retriever_with_graph()
        # Directly call _collect_graph_entity_names twice with same query
        r._graph_cache = {}  # ensure clean state
        r._collect_graph_entity_names("coffee query", [])
        r._collect_graph_entity_names("coffee query", [])
        # get_related_entity_names_sync should be called only once
        assert r._graph.get_related_entity_names_sync.call_count == 1

    def test_cache_reset_triggers_fresh_traversal(self):
        r = self._make_retriever_with_graph()
        # First call populates the cache
        r._collect_graph_entity_names("coffee query", [])
        assert len(r._graph_cache) > 0, "cache should be populated after first call"
        # Simulate retrieve() resetting the cache at the start of a new request
        r._graph_cache = {}
        # Second call after reset should trigger a fresh graph traversal
        r._collect_graph_entity_names("coffee query", [])
        # get_related_entity_names_sync called twice: once before reset, once after
        assert r._graph.get_related_entity_names_sync.call_count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_retriever.py::TestGraphEntityCache -v
```
Expected: `AttributeError: 'MemoryRetriever' object has no attribute '_graph_cache'`

- [ ] **Step 3: Add `_graph_cache` to `MemoryRetriever`**

In `nanobot/agent/memory/retriever.py`:

3a. In `__init__` (after the existing assignments, line ~101):
```python
self._graph_cache: dict[frozenset[str], set[str]] = {}
```

3b. At the top of `retrieve()` (line 119), add as the first line:
```python
self._graph_cache = {}  # reset per-request
```

3c. In `_collect_graph_entity_names` (line 957), after `query_entities` is computed (line ~970) and before the triple-scan loop, add the cache check:
```python
if not query_entities:
    return set()

cache_key = frozenset(query_entities)
if cache_key in self._graph_cache:
    return self._graph_cache[cache_key]
```
And after computing the full result (`graph_entity_names | graph_related`), store it:
```python
result = graph_entity_names | graph_related
self._graph_cache[cache_key] = result
return result
```
(Replace the existing `return graph_entity_names` with the above.)

- [ ] **Step 4: Run tests**

```bash
make lint && make typecheck
pytest tests/test_retriever.py -v
```
Expected: All pass (including new cache tests).

- [ ] **Step 5: Commit**

```bash
git add nanobot/agent/memory/retriever.py tests/test_retriever.py
git commit -m "perf: add per-request graph entity cache in MemoryRetriever

_collect_graph_entity_names now caches results by frozenset(query_entities)
within a single retrieve() call. Cache is reset at each retrieve() entry.
Eliminates redundant graph traversals in multi-section builds.
"
```

---

## Task 6: ConsolidationOrchestrator Rewrite

**Goal:** Replace `WeakValueDictionary` + manual lock management with `asyncio.TaskGroup`. Add `submit()` + `consolidate_and_wait()`. Inject `archive_fn` to decouple from `MemoryPersistence`. Simplify `MessageProcessor` and `AgentLoop`.

**Context:** Current `ConsolidationOrchestrator` is 108 lines in `consolidation.py`. It has `get_lock`, `prune_lock`, `consolidate`, `fallback_archive_snapshot`. All four are removed/replaced. `tests/test_consolidation.py` has three test classes that test the old API — all three must be rewritten. `MessageProcessor._handle_slash_new` (line 545) calls `get_lock/prune_lock` directly and must be cleaned up.

**Files:**
- Modify: `nanobot/agent/consolidation.py` (full rewrite)
- Modify: `nanobot/agent/loop.py`
- Modify: `nanobot/agent/message_processor.py`
- Modify: `tests/test_consolidation.py` (full rewrite)
- Create: `tests/test_consolidation_orchestrator.py`

- [ ] **Step 1: Write new tests for `ConsolidationOrchestrator`**

```python
# tests/test_consolidation_orchestrator.py
"""Tests for the rewritten ConsolidationOrchestrator."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from nanobot.agent.consolidation import ConsolidationOrchestrator


def _make_orchestrator(archive_fn=None, memory_window=50, enable_contradiction_check=True):
    memory = MagicMock()
    memory.consolidate = AsyncMock(return_value=True)
    if archive_fn is None:
        archive_fn = MagicMock()
    return (
        ConsolidationOrchestrator(
            memory=memory,
            archive_fn=archive_fn,
            max_concurrent=3,
            memory_window=memory_window,
            enable_contradiction_check=enable_contradiction_check,
        ),
        memory,
        archive_fn,
    )


class TestContextManager:
    async def test_must_be_used_as_context_manager(self):
        orch, _, _ = _make_orchestrator()
        with pytest.raises(AssertionError, match="async context manager"):
            orch.submit("key", MagicMock(), MagicMock(), "model")

    async def test_enter_exit_without_tasks(self):
        orch, _, _ = _make_orchestrator()
        async with orch:
            pass  # no tasks — should exit cleanly


class TestSubmit:
    async def test_submit_calls_consolidate(self):
        orch, memory, _ = _make_orchestrator()
        session = MagicMock()
        session.messages = []
        provider = MagicMock()
        async with orch:
            orch.submit("session-1", session, provider, "gpt-4")
        memory.consolidate.assert_called_once()

    async def test_submit_deduplicates_same_session(self):
        orch, memory, _ = _make_orchestrator()
        session = MagicMock()
        session.messages = []
        provider = MagicMock()
        async with orch:
            orch.submit("session-1", session, provider, "gpt-4")
            orch.submit("session-1", session, provider, "gpt-4")  # duplicate
        # Only one consolidation despite two submit calls
        assert memory.consolidate.call_count == 1

    async def test_submit_different_sessions_both_run(self):
        orch, memory, _ = _make_orchestrator()
        session = MagicMock()
        session.messages = []
        provider = MagicMock()
        async with orch:
            orch.submit("session-1", session, provider, "gpt-4")
            orch.submit("session-2", session, provider, "gpt-4")
        assert memory.consolidate.call_count == 2

    async def test_archive_fn_called_when_consolidate_raises(self):
        archive = MagicMock()
        orch, memory, _ = _make_orchestrator(archive_fn=archive)
        memory.consolidate = AsyncMock(side_effect=RuntimeError("fail"))
        session = MagicMock()
        session.messages = [{"role": "user", "content": "hello"}]
        provider = MagicMock()
        async with orch:
            orch.submit("session-1", session, provider, "gpt-4")
        archive.assert_called_once()
        called_messages = archive.call_args[0][0]
        assert isinstance(called_messages, list)


class TestConsolidateAndWait:
    async def test_consolidate_and_wait_returns_true_on_success(self):
        orch, memory, _ = _make_orchestrator()
        session = MagicMock()
        session.messages = []
        provider = MagicMock()
        async with orch:
            result = await orch.consolidate_and_wait("s1", session, provider, "gpt-4")
        assert result is True

    async def test_consolidate_and_wait_passes_archive_all(self):
        orch, memory, _ = _make_orchestrator()
        session = MagicMock()
        session.messages = []
        provider = MagicMock()
        async with orch:
            await orch.consolidate_and_wait(
                "s1", session, provider, "gpt-4", archive_all=True
            )
        _call = memory.consolidate.call_args
        assert _call.kwargs.get("archive_all") is True

    async def test_consolidate_and_wait_passes_constructor_injected_values(self):
        orch, memory, _ = _make_orchestrator(memory_window=42, enable_contradiction_check=False)
        session = MagicMock()
        session.messages = []
        provider = MagicMock()
        async with orch:
            await orch.consolidate_and_wait("s1", session, provider, "gpt-4")
        _call = memory.consolidate.call_args
        assert _call.kwargs["memory_window"] == 42
        assert _call.kwargs["enable_contradiction_check"] is False
```

- [ ] **Step 2: Rewrite `tests/test_consolidation.py`**

Replace the entire content of `tests/test_consolidation.py`:

```python
"""Tests for ConsolidationOrchestrator (rewritten for TaskGroup API).

The old API (get_lock, prune_lock, consolidate, fallback_archive_snapshot)
was removed in the TaskGroup rewrite. These tests cover the new API.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.consolidation import ConsolidationOrchestrator


def _orch(archive_fn=None):
    memory = MagicMock()
    memory.consolidate = AsyncMock(return_value=True)
    return ConsolidationOrchestrator(
        memory=memory,
        archive_fn=archive_fn or MagicMock(),
        max_concurrent=2,
        memory_window=50,
        enable_contradiction_check=True,
    ), memory


class TestInProgressDeduplication:
    async def test_second_submit_for_same_session_is_noop(self):
        orch, memory = _orch()
        session = MagicMock()
        session.messages = []
        async with orch:
            orch.submit("s", session, MagicMock(), "m")
            orch.submit("s", session, MagicMock(), "m")
        assert memory.consolidate.call_count == 1


class TestSubmitAndConsolidateAndWait:
    async def test_submit_runs_in_background(self):
        orch, memory = _orch()
        session = MagicMock()
        session.messages = []
        async with orch:
            orch.submit("s", session, MagicMock(), "m")
        memory.consolidate.assert_called_once()

    async def test_consolidate_and_wait_is_awaitable(self):
        orch, memory = _orch()
        session = MagicMock()
        session.messages = []
        async with orch:
            result = await orch.consolidate_and_wait("s", session, MagicMock(), "m")
        assert result is True


class TestArchiveFnOnFailure:
    async def test_archive_fn_called_on_consolidate_failure(self):
        archive = MagicMock()
        orch, memory = _orch(archive_fn=archive)
        memory.consolidate = AsyncMock(side_effect=RuntimeError("boom"))
        session = MagicMock()
        session.messages = [{"role": "user", "content": "hi"}]
        async with orch:
            orch.submit("s", session, MagicMock(), "m")
        archive.assert_called_once()
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/test_consolidation.py tests/test_consolidation_orchestrator.py -v
```
Expected: Tests fail because the new API doesn't exist yet.

- [ ] **Step 4: Rewrite `consolidation.py`**

Replace the entire content of `nanobot/agent/consolidation.py`:

```python
"""Memory consolidation orchestration (rewritten with asyncio.TaskGroup).

``ConsolidationOrchestrator`` manages the lifecycle of memory consolidation:

- **Lifecycle** — async context-manager; ``run()`` enters it; ``stop()`` signals exit.
- **Background** — ``submit()`` schedules fire-and-forget tasks via ``asyncio.TaskGroup``.
- **Blocking** — ``consolidate_and_wait()`` runs consolidation inline (used by /new).
- **Archival** — ``archive_fn`` closure called on failure; decoupled from MemoryPersistence.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

if TYPE_CHECKING:
    from nanobot.memory.store import MemoryStore
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import Session


class ConsolidationOrchestrator:
    """Manages memory consolidation with structured concurrency."""

    def __init__(
        self,
        *,
        memory: MemoryStore,
        archive_fn: Callable[[list[dict[str, Any]]], None],
        max_concurrent: int = 3,
        memory_window: int = 50,
        enable_contradiction_check: bool = True,
    ) -> None:
        self._memory = memory
        self._archive_fn = archive_fn
        self._max_concurrent = max_concurrent
        self._memory_window = memory_window
        self._enable_contradiction_check = enable_contradiction_check
        self._locks: dict[str, asyncio.Lock] = {}
        self._in_progress: set[str] = set()
        self._sem: asyncio.Semaphore | None = None
        self._tg: asyncio.TaskGroup | None = None

    async def __aenter__(self) -> ConsolidationOrchestrator:
        self._sem = asyncio.Semaphore(self._max_concurrent)
        self._tg = asyncio.TaskGroup()
        await self._tg.__aenter__()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._tg is not None:
            await self._tg.__aexit__(*exc_info)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit(
        self,
        session_key: str,
        session: Session,
        provider: LLMProvider,
        model: str,
    ) -> None:
        """Schedule a background consolidation task. Returns immediately.

        Silently skips if a consolidation for this session is already
        in progress (preserves the deduplication from _consolidating guard).
        """
        assert self._tg is not None, "must be used as async context manager"
        if session_key in self._in_progress:
            return
        self._in_progress.add(session_key)
        self._tg.create_task(self._run(session_key, session, provider, model))

    async def consolidate_and_wait(
        self,
        session_key: str,
        session: Session,
        provider: LLMProvider,
        model: str,
        *,
        archive_all: bool = False,
    ) -> bool:
        """Run consolidation inline (awaitable). Returns True on success.

        Used by _consolidate_memory for the archive_all=True path (/new command).
        """
        lock = self._locks.setdefault(session_key, asyncio.Lock())
        try:
            async with lock:
                return await self._memory.consolidate(
                    session,
                    provider,
                    model,
                    memory_window=self._memory_window,
                    enable_contradiction_check=self._enable_contradiction_check,
                    archive_all=archive_all,
                )
        finally:
            entry = self._locks.get(session_key)
            if entry is not None and not entry.locked():
                self._locks.pop(session_key, None)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _run(
        self,
        session_key: str,
        session: Session,
        provider: LLMProvider,
        model: str,
    ) -> None:
        assert self._sem is not None
        try:
            async with self._sem:
                lock = self._locks.setdefault(session_key, asyncio.Lock())
                async with lock:
                    try:
                        await self._memory.consolidate(
                            session,
                            provider,
                            model,
                            memory_window=self._memory_window,
                            enable_contradiction_check=self._enable_contradiction_check,
                        )
                    except Exception:  # crash-barrier: consolidation failure
                        logger.exception("Consolidation failed for {}; archiving", session_key)
                        self._archive_fn(list(session.messages))
                        raise
        finally:
            self._in_progress.discard(session_key)
            entry = self._locks.get(session_key)
            if entry is not None and not entry.locked():
                self._locks.pop(session_key, None)
```

- [ ] **Step 5: Run consolidation tests**

```bash
make lint && make typecheck
pytest tests/test_consolidation.py tests/test_consolidation_orchestrator.py -v
```
Expected: All pass.

- [ ] **Step 6: Update `AgentLoop._wire_memory()` in `loop.py`**

In `nanobot/agent/loop.py`, find `_wire_memory()` (line ~407):

6a. Remove the three state fields:
```python
# Remove these lines:
self._consolidating: set[str] = set()
self._consolidation_tasks: set[asyncio.Task[None]] = set()
self._consolidation_sem = asyncio.Semaphore(3)
```

6b. Build the `archive_fn` closure before constructing the orchestrator:
```python
from datetime import datetime, timezone

def _archive(messages: list[dict[str, Any]]) -> None:
    lines: list[str] = []
    for m in messages:
        content = m.get("content")
        if not content:
            continue
        tools = (
            f" [tools: {', '.join(m['tools_used'])}]" if m.get("tools_used") else ""
        )
        timestamp = str(m.get("timestamp", "?"))[:16]
        role = str(m.get("role", "unknown")).upper()
        lines.append(f"[{timestamp}] {role}{tools}: {content}")
    if lines:
        header = (
            f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}] "
            f"Fallback archive ({len(lines)} messages)"
        )
        self.context.memory.persistence.append_text(
            self.context.memory.history_file,
            header + "\n" + "\n".join(lines) + "\n\n",
        )
```

6c. Replace the orchestrator construction:
```python
# Old:
self._consolidator = ConsolidationOrchestrator(self.context.memory)
# New:
self._consolidator = ConsolidationOrchestrator(
    memory=self.context.memory,
    archive_fn=_archive,
    max_concurrent=3,
    memory_window=self.config.memory_window,
    enable_contradiction_check=self.config.memory_enable_contradiction_check,
)
```

6d. Update `AgentLoop._consolidate_memory()` (line ~945):
```python
async def _consolidate_memory(self, session: Session, archive_all: bool = False) -> bool:
    """Delegate to ConsolidationOrchestrator."""
    if archive_all:
        return await self._consolidator.consolidate_and_wait(
            session.key,
            session,
            self.provider,
            self.model,
            archive_all=True,
        )
    self._consolidator.submit(session.key, session, self.provider, self.model)
    return True
```

6e. Update `AgentLoop.run()` to use the orchestrator as a context manager. Find the `run()` method body and wrap the main while loop:
```python
async def run(self) -> None:
    self._running = True
    self._stop_event = asyncio.Event()
    await self._connect_mcp()
    self._ensure_coordinator()
    await self.context.memory.maintenance.ensure_health()
    logger.info("Agent loop started")
    async with self._consolidator:
        while self._running:
            # ... existing while loop body unchanged ...
```

- [ ] **Step 7: Update `MessageProcessor` in `message_processor.py`**

7a. In `MessageProcessor.__init__` (lines 93–95), remove:
```python
# Remove:
self._consolidating: set[str] = set()
self._consolidation_tasks: set[asyncio.Task[None]] = set()
self._consolidation_sem = asyncio.Semaphore(3)
```

7b. Update `MessageProcessor._consolidate_memory()` (line ~709):
```python
async def _consolidate_memory(self, session: Session, archive_all: bool = False) -> bool:
    """Delegate to ConsolidationOrchestrator."""
    if archive_all:
        return await self._consolidator.consolidate_and_wait(
            session.key, session, self.provider, self.model, archive_all=True
        )
    self._consolidator.submit(session.key, session, self.provider, self.model)
    return True
```

7c. Update `MessageProcessor._handle_slash_new()` (line ~545) — remove the three direct calls:
```python
# Remove these lines:
lock = self._consolidator.get_lock(session.key)   # line 547
self._consolidating.add(session.key)               # line 548
# and:
self._consolidating.discard(session.key)           # line 570
self._consolidator.prune_lock(session.key, lock)   # line 571
# and the "async with lock:" block wrapper — keep only the inner content
```
The method body becomes simply calling `await self._consolidate_memory(temp, archive_all=True)` with the error handling.

7d. Remove the `_run_consolidation_task` method (it is replaced by `ConsolidationOrchestrator._run`). If any reference to `_run_consolidation_task` exists in tests, update those.

- [ ] **Step 8: Run full test suite**

```bash
make lint && make typecheck
pytest -x -v
```
Expected: All pass (including `test_agent_loop.py`).

- [ ] **Step 9: Commit**

```bash
git add nanobot/agent/consolidation.py \
        nanobot/agent/loop.py \
        nanobot/agent/message_processor.py \
        tests/test_consolidation.py \
        tests/test_consolidation_orchestrator.py
git commit -m "refactor: rewrite ConsolidationOrchestrator with asyncio.TaskGroup

Replaces WeakValueDictionary + prune_lock with TaskGroup + _in_progress set.
archive_fn closure injected at construction; decoupled from MemoryPersistence.
AgentLoop.run() enters orchestrator as context manager for clean drain on stop.
MessageProcessor._handle_slash_new stripped of direct lock management.
"
```

---

## Task 7: Final Validation

**Goal:** Ensure the full suite passes, `profile.py` is gone, `token_budget.py` has no memory subsystem imports, and architecture docs are updated.

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/adr/ADR-002-agent-loop-ownership.md` (if it references memory subsystem)

- [ ] **Step 1: Run the full validation suite**

```bash
make check
```
Expected: lint + typecheck + import-check + prompt-check + tests all pass.

- [ ] **Step 2: Verify `profile.py` is deleted**

```bash
ls nanobot/agent/memory/profile.py 2>&1 || echo "DELETED OK"
```
Expected: `DELETED OK`

- [ ] **Step 3: Verify `token_budget.py` has no memory subsystem imports**

```bash
python -c "
import ast, sys
tree = ast.parse(open('nanobot/agent/memory/token_budget.py').read())
imports = [ast.dump(n) for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
bad = [i for i in imports if 'agent' in i or 'memory' in i or 'config' in i]
if bad:
    print('FAIL:', bad)
    sys.exit(1)
print('OK: no agent/memory/config imports')
"
```
Expected: `OK: no agent/memory/config imports`

- [ ] **Step 4: Update `docs/architecture.md`**

Add a section "Memory Subsystem Module Boundaries (Post-Completion)" listing:
- `profile_io.py` owns profile CRUD and caching; never imports from `channels/`, `bus/`, `session/`, or `agent/loop`
- `profile_correction.py` owns live correction; never imports from `channels/` or `bus/`
- `token_budget.py` is pure logic; never imports from any `agent/memory/` module
- `consolidation.py` owns structured concurrency for consolidation; never imports from `channels/` or `agent/loop`
- `ProfileCache` is internal to `ProfileStore`; not exported from `nanobot/agent/memory/__init__.py`

- [ ] **Step 5: Final commit**

```bash
git add docs/architecture.md
git commit -m "docs: update architecture.md with memory subsystem module boundaries"
```

---

## Quick Reference: Key File Locations

| Symbol | File | Line |
|--------|------|------|
| `ProfileManager.__init__` | `profile.py` → `profile_io.py` | ~65 |
| `ProfileManager.apply_live_user_correction` | `profile.py` → `profile_io.py` | ~797 |
| `ProfileManager._apply_profile_updates` | `profile.py` → `profile_io.py` | ~625 |
| `ConflictManager.__init__` | `conflicts.py` | ~49 |
| `ConflictManager.resolve_conflict_details` | `conflicts.py` | ~299 |
| `ContextAssembler._allocate_section_budgets` | `context_assembler.py` | ~552 |
| `ContextAssembler.__init__` | `context_assembler.py` | ~128 |
| `MemoryRetriever._collect_graph_entity_names` | `retriever.py` | ~957 |
| `MemoryStore.__init__` | `store.py` | ~84 |
| `MemoryStore._ensure_assembler` | `store.py` | ~302 |
| `ConsolidationOrchestrator.fallback_archive_snapshot` | `consolidation.py` | ~82 (old) |
| `AgentLoop._wire_memory` | `loop.py` | ~407 |
| `AgentLoop._consolidate_memory` | `loop.py` | ~945 |
| `AgentLoop.run` | `loop.py` | ~649 |
| `MessageProcessor.__init__` | `message_processor.py` | ~88 |
| `MessageProcessor._handle_slash_new` | `message_processor.py` | ~545 |
| `MessageProcessor._consolidate_memory` | `message_processor.py` | ~709 |
| `AgentDefaults` | `config/schema.py` | ~160 |
