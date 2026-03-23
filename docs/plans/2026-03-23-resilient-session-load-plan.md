# Resilient Session Load Implementation Plan (v2)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `SessionManager._load()` recover partial session data from corrupt JSONL files instead of discarding the entire session.

**Architecture:** Refactor `_load()` to parse metadata and message lines individually with per-line error handling. Add consolidation guard to prevent memory corruption when `last_consolidated` defaults to 0.

**Tech Stack:** Python 3.11+, pytest, loguru, json

**Design Doc:** `docs/plans/2026-03-23-resilient-session-load-design.md`

**Branch:** `fix/resilient-session-load` (from `main`)
**Target:** `main` (Bug Fix, no behavior changes for valid files)

**Review findings addressed:** 12/12 (all from R1-R5 review round)

---

### Task 1: Create feature branch

**Files:**
- Branch only

**Step 1: Create and switch to feature branch**

```bash
cd /root/.nanobot/workspace/forks/nanobot
git checkout -b fix/resilient-session-load
```

**Step 2: Verify branch**

```bash
git branch --show-current
```
Expected: `fix/resilient-session-load`

---

### Task 2: Add `_last_consolidated_recovered` field to Session

**Files:**
- Modify: `nanobot/session/manager.py` (Session dataclass, line ~33)

**Step 1: Add the field**

In the `Session` dataclass, after `last_consolidated: int = 0`, add:

```python
    _last_consolidated_recovered: bool = False
```

**Step 2: Verify existing tests pass**

```bash
cd /root/.nanobot/workspace/forks/nanobot
python -m pytest tests/test_session_manager_history.py -v
```
Expected: All PASS (new field has default, no behavior change)

**Step 3: Commit**

```bash
git add nanobot/session/manager.py
git commit -m "refactor(session): add _last_consolidated_recovered sentinel field"
```

---

### Task 3: Add consolidation guard in memory.py

**Files:**
- Modify: `nanobot/agent/memory.py` (`maybe_consolidate_by_tokens` method)

**Step 1: Add early-return guard**

In `maybe_consolidate_by_tokens`, after the `async with lock:` block and before the budget calculation, add:

```python
        if session._last_consolidated_recovered:
            logger.warning(
                "Skipping consolidation for {}: last_consolidated was recovered from default, "
                "cannot safely determine consolidation boundary",
                session.key,
            )
            return
```

**Step 2: Verify existing tests pass**

```bash
python -m pytest tests/test_session_manager_history.py tests/test_consolidate_offset.py -v 2>/dev/null || python -m pytest tests/test_session_manager_history.py -v
```
Expected: All PASS

**Step 3: Commit**

```bash
git add nanobot/agent/memory.py
git commit -m "fix(memory): skip consolidation when last_consolidated was recovered from default"
```

---

### Task 4: Write failing tests — corrupt message lines

**Files:**
- Create: `tests/test_session_resilient_load.py`

**Step 1: Write failing tests for corrupt message line handling**

```python
"""Tests for resilient session loading from corrupt JSONL files."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from nanobot.session.manager import Session, SessionManager


@pytest.fixture
def tmp_session_manager(tmp_path: Path) -> SessionManager:
    return SessionManager(workspace=tmp_path)


def _write_session_file(path: Path, lines: list[str]) -> None:
    """Helper: write raw lines to a session JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_metadata_line(**overrides) -> str:
    """Helper: build a metadata JSONL line."""
    data = {
        "_type": "metadata",
        "key": "telegram:12345",
        "created_at": "2026-03-23T10:00:00",
        "updated_at": "2026-03-23T22:00:00",
        "metadata": {},
        "last_consolidated": 5,
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def _make_message_line(role: str, content: str, **kwargs) -> str:
    """Helper: build a message JSONL line."""
    data = {"role": role, "content": content, "timestamp": "2026-03-23T12:00:00", **kwargs}
    return json.dumps(data, ensure_ascii=False)


class TestCorruptMessageLines:
    def test_load_truncated_last_line(self, tmp_session_manager: SessionManager, tmp_path: Path):
        """Truncated JSON on last line: all previous messages should load."""
        path = tmp_session_manager._get_session_path("telegram:12345")
        lines = [
            _make_metadata_line(),
            _make_message_line("user", "hello"),
            _make_message_line("assistant", "hi there"),
            '{"role": "assistant", "content": "I was writ',
        ]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")

        assert session is not None
        assert len(session.messages) == 2
        assert session.messages[0]["content"] == "hello"
        assert session.messages[1]["content"] == "hi there"

    def test_load_corrupt_middle_line(self, tmp_session_manager: SessionManager, tmp_path: Path):
        """Invalid JSON in middle: that line skipped, before and after load."""
        path = tmp_session_manager._get_session_path("telegram:12345")
        lines = [
            _make_metadata_line(),
            _make_message_line("user", "before"),
            "THIS IS NOT JSON {{{",
            _make_message_line("user", "after"),
            _make_message_line("assistant", "response"),
        ]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")

        assert session is not None
        assert len(session.messages) == 3
        assert session.messages[0]["content"] == "before"
        assert session.messages[1]["content"] == "after"
        assert session.messages[2]["content"] == "response"

    def test_load_all_lines_corrupt_returns_none(self, tmp_session_manager: SessionManager, tmp_path: Path):
        """All lines invalid: returns None (fresh session)."""
        path = tmp_session_manager._get_session_path("telegram:12345")
        lines = ["NOT JSON", "ALSO NOT {{{", "STILL BAD"]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")

        assert session is None

    def test_load_completely_empty_file_returns_none(self, tmp_session_manager: SessionManager, tmp_path: Path):
        """Empty file: returns None."""
        path = tmp_session_manager._get_session_path("telegram:12345")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

        session = tmp_session_manager._load("telegram:12345")

        assert session is None

    def test_load_non_dict_line_skipped(self, tmp_session_manager: SessionManager, tmp_path: Path):
        """Non-dict JSON value (e.g. a string) is skipped."""
        path = tmp_session_manager._get_session_path("telegram:12345")
        lines = [
            _make_metadata_line(),
            _make_message_line("user", "before"),
            '"just a string value"',
            _make_message_line("user", "after"),
        ]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")

        assert session is not None
        assert len(session.messages) == 2
        assert session.messages[0]["content"] == "before"
        assert session.messages[1]["content"] == "after"

    def test_load_oversize_line_skipped(self, tmp_session_manager: SessionManager, tmp_path: Path):
        """Lines exceeding _MAX_LINE_BYTES are skipped."""
        path = tmp_session_manager._get_session_path("telegram:12345")
        huge_line = json.dumps({"role": "user", "content": "x" * 1_100_000})
        lines = [
            _make_metadata_line(),
            _make_message_line("user", "before"),
            huge_line,
            _make_message_line("user", "after"),
        ]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")

        assert session is not None
        assert len(session.messages) == 2

    def test_load_bom_file(self, tmp_session_manager: SessionManager, tmp_path: Path):
        """File with UTF-8 BOM is parsed correctly."""
        path = tmp_session_manager._get_session_path("telegram:12345")
        content = "\ufeff" + "\n".join([
            _make_metadata_line(),
            _make_message_line("user", "hello"),
        ]) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

        session = tmp_session_manager._load("telegram:12345")

        assert session is not None
        assert len(session.messages) == 1
        assert session.messages[0]["content"] == "hello"
```

**Step 2: Run tests to verify they fail**

```bash
cd /root/.nanobot/workspace/forks/nanobot
python -m pytest tests/test_session_resilient_load.py -v
```
Expected: FAIL — `_load()` returns `None` for truncated/corrupt files (current behavior)

**Step 3: Commit test file**

```bash
git add tests/test_session_resilient_load.py
git commit -m "test: add failing tests for corrupt message line handling"
```

---

### Task 5: Write failing tests — corrupt metadata and metadata-only

**Files:**
- Modify: `tests/test_session_resilient_load.py`

**Step 1: Add tests for corrupt metadata and metadata-only sessions**

Append to `tests/test_session_resilient_load.py`:

```python
class TestCorruptMetadata:
    def test_load_metadata_only_returns_session(self, tmp_session_manager: SessionManager, tmp_path: Path):
        """Metadata-only file with empty metadata dict: returns Session (not None)."""
        path = tmp_session_manager._get_session_path("telegram:12345")
        lines = [_make_metadata_line()]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")

        assert session is not None
        assert session.messages == []
        assert session.metadata == {}
        assert session.last_consolidated == 5
        assert session._last_consolidated_recovered is False

    def test_load_corrupt_metadata_created_at(self, tmp_session_manager: SessionManager, tmp_path: Path):
        """Invalid created_at in metadata: defaults to None, messages still load."""
        path = tmp_session_manager._get_session_path("telegram:12345")
        lines = [
            _make_metadata_line(created_at="not-a-date"),
            _make_message_line("user", "hello"),
        ]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")

        assert session is not None
        assert len(session.messages) == 1
        assert session.created_at is not None  # falls back to datetime.now()

    def test_load_corrupt_metadata_last_consolidated(self, tmp_session_manager: SessionManager, tmp_path: Path):
        """Invalid last_consolidated: defaults to 0, sets recovery flag, messages still load."""
        path = tmp_session_manager._get_session_path("telegram:12345")
        lines = [
            _make_metadata_line(last_consolidated="abc"),
            _make_message_line("user", "hello"),
        ]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")

        assert session is not None
        assert session.last_consolidated == 0
        assert session._last_consolidated_recovered is True
        assert len(session.messages) == 1

    def test_load_metadata_missing_fields(self, tmp_session_manager: SessionManager, tmp_path: Path):
        """Metadata line with only _type: all fields get defaults, messages still load."""
        path = tmp_session_manager._get_session_path("telegram:12345")
        lines = [
            json.dumps({"_type": "metadata"}),
            _make_message_line("user", "hello"),
        ]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")

        assert session is not None
        assert session.metadata == {}
        assert session.last_consolidated == 0
        assert session._last_consolidated_recovered is True
        assert len(session.messages) == 1

    def test_load_metadata_missing_last_consolidated(self, tmp_session_manager: SessionManager, tmp_path: Path):
        """Metadata without last_consolidated field: defaults to 0, sets recovery flag."""
        path = tmp_session_manager._get_session_path("telegram:12345")
        lines = [
            json.dumps({
                "_type": "metadata",
                "key": "telegram:12345",
                "created_at": "2026-03-23T10:00:00",
                "updated_at": "2026-03-23T22:00:00",
                "metadata": {"foo": "bar"},
            }),
            _make_message_line("user", "hello"),
        ]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")

        assert session is not None
        assert session.last_consolidated == 0
        assert session._last_consolidated_recovered is True
        assert session.metadata == {"foo": "bar"}
```

**Step 2: Run tests**

```bash
python -m pytest tests/test_session_resilient_load.py -v
```
Expected: FAIL — metadata-only test fails (current `parsed_any` bug), corrupt metadata tests fail

**Step 3: Commit**

```bash
git add tests/test_session_resilient_load.py
git commit -m "test: add corrupt metadata and metadata-only session tests"
```

---

### Task 6: Implement resilient `_load()`

**Files:**
- Modify: `nanobot/session/manager.py` (`_load` method, lines 171-216)

**Step 1: Add `_MAX_LINE_BYTES` constant**

At module level (after imports, before the Session class), add:

```python
_MAX_LINE_BYTES = 1_000_000  # 1 MB — skip oversized lines
```

**Step 2: Replace the `_load()` method**

Replace the entire `_load()` method with:

```python
    def _load(self, key: str) -> Session | None:
        """Load a session from disk, recovering partial data from corrupt files."""
        path = self._get_session_path(key)
        if not path.exists():
            legacy_path = self._get_legacy_session_path(key)
            if legacy_path.exists():
                try:
                    shutil.move(str(legacy_path), str(path))
                    logger.info("Migrated session {} from legacy path", key)
                except Exception:
                    logger.exception("Failed to migrate session {}", key)

        if not path.exists():
            return None

        try:
            messages: list[dict[str, Any]] = []
            metadata: dict[str, Any] = {}
            created_at: datetime | None = None
            last_consolidated: int = 0
            last_consolidated_recovered = False
            recovered = False

            with open(path, encoding="utf-8-sig", errors="replace") as f:
                for line_num, raw in enumerate(f, 1):
                    stripped = raw.strip()
                    if not stripped:
                        continue

                    if len(stripped) > _MAX_LINE_BYTES:
                        logger.warning(
                            "Oversized line {} ({} bytes) in session {} — skipping",
                            line_num, len(stripped), key,
                        )
                        continue

                    try:
                        data = json.loads(stripped)
                    except json.JSONDecodeError:
                        logger.warning(
                            "Corrupt line {} in session {} at {} — skipping",
                            line_num, key, path,
                        )
                        continue

                    if not isinstance(data, dict):
                        logger.warning(
                            "Non-dict JSON on line {} in session {} — skipping",
                            line_num, key,
                        )
                        continue

                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        try:
                            created_at = (
                                datetime.fromisoformat(data["created_at"])
                                if data.get("created_at")
                                else None
                            )
                        except (ValueError, TypeError):
                            logger.warning("Invalid created_at in session {} at {}", key, path)
                        try:
                            last_consolidated = int(data.get("last_consolidated", 0))
                        except (ValueError, TypeError):
                            logger.warning(
                                "Invalid last_consolidated in session {} at {}, defaulting to 0",
                                key, path,
                            )
                            last_consolidated = 0
                            last_consolidated_recovered = True
                        recovered = True
                    else:
                        messages.append(data)
                        recovered = True

            if not recovered:
                return None

            return Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                metadata=metadata,
                last_consolidated=last_consolidated,
                _last_consolidated_recovered=last_consolidated_recovered,
            )
        except OSError as e:
            logger.warning("Failed to load session {} at {}: {}", key, path, e)
            return None
```

**Step 3: Run ALL new tests**

```bash
python -m pytest tests/test_session_resilient_load.py -v
```
Expected: All PASS

**Step 4: Run existing session tests for regression**

```bash
python -m pytest tests/test_session_manager_history.py -v
```
Expected: All PASS

**Step 5: Commit**

```bash
git add nanobot/session/manager.py
git commit -m "fix(session): resilient load with per-line error recovery"
```

---

### Task 7: Run linting and full test suite

**Files:**
- None (verification only)

**Step 1: Lint the changed files**

```bash
cd /root/.nanobot/workspace/forks/nanobot
ruff check nanobot/session/manager.py nanobot/agent/memory.py
```
Expected: No errors

**Step 2: Format check**

```bash
ruff format --check nanobot/session/manager.py nanobot/agent/memory.py
```
Expected: No formatting issues (or auto-fix with `ruff format`)

**Step 3: Run full project test suite**

```bash
python -m pytest tests/ -v --timeout=30 2>&1 | tail -30
```
Expected: All PASS (no regressions)

**Step 4: Commit any lint fixes if needed**

```bash
git add nanobot/session/manager.py nanobot/agent/memory.py
git commit -m "style: lint/format fixes" || true
```

---

### Task 8: Push and create PR

**Step 1: Push feature branch to origin**

```bash
git push -u origin fix/resilient-session-load
```

**Step 2: Create PR via gh CLI**

```bash
gh pr create --repo HKUDS/nanobot \
  --title "fix(session): resilient load with per-line error recovery" \
  --body '## Summary

`SessionManager._load()` currently returns `None` on any exception during JSONL parsing, causing complete session loss from a single corrupt line (e.g. truncated write during process restart).

This PR makes session loading resilient:

- **Per-line parsing**: Each JSONL line is parsed independently. A corrupt line is logged and skipped instead of failing the entire load.
- **Robust metadata**: Each metadata field (`created_at`, `last_consolidated`, `metadata`) is parsed individually with safe defaults on failure.
- **Consolidation guard**: When `last_consolidated` defaults to `0` due to parse failure, a sentinel flag prevents re-consolidation of already-processed messages (which would corrupt MEMORY.md/HISTORY.md with duplicates).
- **Encoding resilience**: Uses `utf-8-sig` encoding (BOM-tolerant) and `errors="replace"` to isolate byte-level corruption to individual lines.
- **Defensive guards**: Non-dict JSON values and oversized lines (>1MB) are skipped.

## Root cause

Process restart during `save()` (which uses `open("w")`) truncates the file before writing completes. A subsequent `_load()` fails on the truncated JSON, returning `None`.

**Follow-up:** Atomic save (write-to-tmp + `os.replace`) will be addressed in a separate PR to fix the root cause.

## Test plan

- [x] Truncated last line → all previous messages recovered
- [x] Corrupt middle line → line skipped, before/after messages recovered
- [x] All lines corrupt → returns None (fresh session)
- [x] Empty file → returns None
- [x] Metadata-only file (empty metadata dict) → returns Session (not None)
- [x] Invalid created_at/last_consolidated → safe defaults
- [x] Missing metadata fields → safe defaults + recovery flag
- [x] UTF-8 BOM file → parsed correctly
- [x] Non-dict JSON line → skipped
- [x] Oversized line (>1MB) → skipped
- [x] Existing session tests pass (no regression)' \
  --base main \
  --head data219:fix/resilient-session-load
```
