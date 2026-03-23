# Resilient Session Load Implementation Plan (v3)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `SessionManager._load()` recover partial session data from corrupt JSONL files instead of discarding the entire session.

**Architecture:** Refactor `_load()` to parse metadata and message lines individually with per-line error handling. Use `last_consolidated = len(messages)` fallback when `last_consolidated` is untrustworthy — no sentinel field, no cross-module changes.

**Tech Stack:** Python 3.11+, pytest, loguru, json

**Design Doc:** `docs/plans/2026-03-23-resilient-session-load-design.md`

**Branch:** `fix/resilient-session-load` (from `main`)
**Target:** `main` (Bug Fix, no behavior changes for valid files)

**Review findings addressed:** 11/11 (v2 deduplizierte Findings aus Runde 2)

**Execution policy:** Tasks 1–6 may be executed autonomously. Task 7 (push) is autonomous. Task 8 (PR) requires **explicit user approval** before execution. The user may also choose to create the PR themselves.

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

### Task 2: Write failing tests — corrupt message lines

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

    def test_load_recursion_error_line_skipped(self, tmp_session_manager: SessionManager, tmp_path: Path):
        """Deeply nested JSON triggers RecursionError — line is skipped."""
        path = tmp_session_manager._get_session_path("telegram:12345")
        deep_json = '{"a":' * 50000 + '"b"' + '}' * 50000
        lines = [
            _make_metadata_line(),
            _make_message_line("user", "before"),
            deep_json,
            _make_message_line("user", "after"),
        ]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")

        assert session is not None
        assert len(session.messages) == 2
        assert session.messages[0]["content"] == "before"
        assert session.messages[1]["content"] == "after"
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

### Task 3: Write failing tests — corrupt metadata

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
        """Invalid last_consolidated: falls back to len(messages) to prevent re-consolidation."""
        path = tmp_session_manager._get_session_path("telegram:12345")
        lines = [
            _make_metadata_line(last_consolidated="abc"),
            _make_message_line("user", "hello"),
        ]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")

        assert session is not None
        assert session.last_consolidated == 1  # len(messages) — assume all loaded are consolidated
        assert len(session.messages) == 1

    def test_load_metadata_missing_fields(self, tmp_session_manager: SessionManager, tmp_path: Path):
        """Metadata line with only _type: all fields get defaults, last_consolidated = len(messages)."""
        path = tmp_session_manager._get_session_path("telegram:12345")
        lines = [
            json.dumps({"_type": "metadata"}),
            _make_message_line("user", "hello"),
        ]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")

        assert session is not None
        assert session.metadata == {}
        assert session.last_consolidated == 1  # len(messages) — missing field is untrustworthy
        assert len(session.messages) == 1

    def test_load_corrupt_metadata_json_with_valid_messages(self, tmp_session_manager: SessionManager, tmp_path: Path):
        """Entire metadata line is invalid JSON, but message lines are valid — recovered with guard."""
        path = tmp_session_manager._get_session_path("telegram:12345")
        lines = [
            "{_type: metadata BROKEN JSON {{{",
            _make_message_line("user", "hello"),
            _make_message_line("assistant", "world"),
        ]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")

        assert session is not None
        assert len(session.messages) == 2
        assert session.last_consolidated == 2  # len(messages) — no metadata parsed, untrustworthy
```

**Step 2: Run tests**

```bash
python -m pytest tests/test_session_resilient_load.py -v
```
Expected: FAIL — current `_load()` returns None for all corrupt cases

**Step 3: Commit**

```bash
git add tests/test_session_resilient_load.py
git commit -m "test: add corrupt metadata and metadata-only session tests"
```

---

### Task 4: Implement resilient `_load()`

**Files:**
- Modify: `nanobot/session/manager.py` (`_load` method)

**Step 1: Replace the `_load()` method**

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
            last_consolidated_untrustworthy = False
            metadata_parsed = False
            recovered = False
            skipped_count = 0
            total_lines = 0

            with open(path, encoding="utf-8-sig") as f:
                for line_num, raw in enumerate(f, 1):
                    total_lines += 1
                    stripped = raw.strip()
                    if not stripped:
                        continue

                    try:
                        data = json.loads(stripped)
                    except (json.JSONDecodeError, RecursionError):
                        logger.warning(
                            "Corrupt line {} in session {} at {} — skipping",
                            line_num, key, path,
                        )
                        skipped_count += 1
                        continue

                    if not isinstance(data, dict):
                        logger.warning(
                            "Non-dict JSON on line {} in session {} — skipping",
                            line_num, key,
                        )
                        skipped_count += 1
                        continue

                    if data.get("_type") == "metadata":
                        # Parse metadata fields individually with safe defaults
                        raw_meta = data.get("metadata", {})
                        metadata = raw_meta if isinstance(raw_meta, dict) else {}
                        if not isinstance(raw_meta, dict):
                            logger.warning("Non-dict metadata in session {} at {}", key, path)

                        try:
                            created_at = (
                                datetime.fromisoformat(data["created_at"])
                                if data.get("created_at")
                                else None
                            )
                        except (ValueError, TypeError):
                            logger.warning("Invalid created_at in session {} at {}", key, path)

                        if "last_consolidated" not in data:
                            last_consolidated_untrustworthy = True
                        else:
                            try:
                                last_consolidated = int(data["last_consolidated"])
                            except (ValueError, TypeError, OverflowError):
                                logger.warning(
                                    "Invalid last_consolidated in session {} at {}, falling back to len(messages)",
                                    key, path,
                                )
                                last_consolidated_untrustworthy = True

                        metadata_parsed = True
                        recovered = True
                    else:
                        messages.append(data)
                        recovered = True

            if not recovered:
                return None

            # If last_consolidated is untrustworthy (corrupt/missing metadata),
            # assume all loaded messages are already consolidated to prevent
            # re-consolidation and duplicate MEMORY.md/HISTORY.md entries.
            if last_consolidated_untrustworthy and messages:
                last_consolidated = len(messages)
                logger.warning(
                    "Untrusted last_consolidated in session {} — assuming all {} loaded messages are consolidated",
                    key, len(messages),
                )

            if skipped_count > 0:
                logger.info(
                    "Session {} partially recovered: {}/{} lines loaded, {} skipped",
                    key, total_lines - skipped_count, total_lines, skipped_count,
                )

            return Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                metadata=metadata,
                last_consolidated=last_consolidated,
            )
        except OSError as e:
            logger.warning("Failed to load session {} at {}: {}", key, path, e)
            return None
```

**Step 2: Run ALL new tests**

```bash
python -m pytest tests/test_session_resilient_load.py -v
```
Expected: All PASS

**Step 3: Run existing session tests for regression**

```bash
python -m pytest tests/test_session_manager_history.py -v
```
Expected: All PASS

**Step 4: Commit**

```bash
git add nanobot/session/manager.py
git commit -m "fix(session): resilient load with per-line error recovery"
```

---

### Task 5: Run linting and full test suite

**Files:**
- None (verification only)

**Step 1: Lint the changed files**

```bash
cd /root/.nanobot/workspace/forks/nanobot
ruff check nanobot/session/manager.py
```
Expected: No errors

**Step 2: Format check**

```bash
ruff format --check nanobot/session/manager.py
```
Expected: No formatting issues (or auto-fix with `ruff format`)

**Step 3: Run full project test suite**

```bash
python -m pytest tests/ -v --timeout=30 2>&1 | tail -30
```
Expected: All PASS (no regressions)

**Step 4: Commit any lint fixes if needed**

```bash
git add nanobot/session/manager.py
git commit -m "style: lint/format fixes" || true
```

---

### Task 6: Verify all test scenarios manually

**Files:**
- None (verification only)

**Step 1: Run new tests with verbose output**

```bash
python -m pytest tests/test_session_resilient_load.py -v --tb=short
```
Expected: 12 tests, all PASS

**Step 2: Verify specific edge cases**

```bash
# Verify corrupt metadata + messages scenario
python -m pytest tests/test_session_resilient_load.py::TestCorruptMetadata::test_load_corrupt_metadata_json_with_valid_messages -v

# Verify missing fields scenario
python -m pytest tests/test_session_resilient_load.py::TestCorruptMetadata::test_load_metadata_missing_fields -v

# Verify RecursionError handling
python -m pytest tests/test_session_resilient_load.py::TestCorruptMessageLines::test_load_recursion_error_line_skipped -v
```
Expected: All PASS

**Step 3: Verify no regressions in existing session tests**

```bash
python -m pytest tests/test_session_manager_history.py tests/test_consolidate_offset.py -v 2>/dev/null || python -m pytest tests/test_session_manager_history.py -v
```
Expected: All PASS

---

### Task 7: Push to fork ⛔ GATE (autonomous)

**Step 1: Push feature branch to origin (fork)**

```bash
git push -u origin fix/resilient-session-load
```

No approval needed — push to fork is autonomous.

---

### Task 8: Create PR ⛔ GATE (requires explicit user approval)

> **Execution policy:** Task 8 requires **explicit user approval** before execution. The user may also choose to create the PR themselves.

**Step 0: Wait for user approval**

Before proceeding, present the completion summary from Tasks 1–7 and ask for approval to create the PR.

**Step 1: Create PR via gh CLI**

```bash
gh pr create --repo HKUDS/nanobot \
  --title "fix(session): resilient load with per-line error recovery" \
  --body '## Summary

`SessionManager._load()` currently returns `None` on any exception during JSONL parsing, causing complete session loss from a single corrupt line (e.g. truncated write during process restart).

This PR makes session loading resilient:

- **Per-line parsing**: Each JSONL line is parsed independently. A corrupt line is logged and skipped instead of failing the entire load.
- **Robust metadata**: Each metadata field (`created_at`, `last_consolidated`, `metadata`) is parsed individually with safe defaults on failure.
- **Consolidation safety**: When `last_consolidated` is corrupt or missing, it defaults to `len(messages)` (assume all loaded messages are already consolidated), preventing re-consolidation and duplicate MEMORY.md/HISTORY.md entries.
- **Encoding resilience**: Uses `utf-8-sig` encoding (BOM-tolerant).
- **Defensive guards**: Non-dict JSON values are skipped. `RecursionError` and `OverflowError` are caught.
- **Recovery logging**: Summary log after partial recovery (lines loaded vs skipped).

## Root cause

Process restart during `save()` (which uses `open("w")`) truncates the file before writing completes. A subsequent `_load()` fails on the truncated JSON, returning `None`.

**Follow-up:** Atomic save (write-to-tmp + `os.replace`) will be addressed in a separate PR to fix the root cause.

## Test plan

- [x] Truncated last line → all previous messages recovered
- [x] Corrupt middle line → line skipped, before/after messages recovered
- [x] All lines corrupt → returns None (fresh session)
- [x] Empty file → returns None
- [x] Non-dict JSON line → skipped
- [x] UTF-8 BOM file → parsed correctly
- [x] RecursionError on deeply nested JSON → skipped
- [x] Metadata-only file (empty metadata dict) → returns Session (not None)
- [x] Invalid created_at → safe defaults
- [x] Invalid last_consolidated → fallback to len(messages)
- [x] Missing metadata fields → safe defaults + len(messages) fallback
- [x] Corrupt metadata JSON + valid messages → recovered with len(messages) fallback
- [x] Existing session tests pass (no regression)' \
  --base main \
  --head data219:fix/resilient-session-load
```
