# Resilient Session Load Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `SessionManager._load()` recover partial session data from corrupt JSONL files instead of discarding the entire session.

**Architecture:** Refactor `_load()` to parse metadata and message lines individually with per-line error handling. Backup corrupt files before recovery. Clean up backups on successful save.

**Tech Stack:** Python 3.11+, pytest, loguru, json, shutil

**Design Doc:** `docs/plans/2026-03-23-resilient-session-load-design.md`

**Branch:** `fix/resilient-session-load` (from `main`)
**Target:** `main` (Bug Fix, no behavior changes for valid files)

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


# --- Corrupt message lines ---


class TestCorruptMessageLines:
    def test_load_truncated_last_line(self, tmp_session_manager: SessionManager, tmp_path: Path):
        """Truncated JSON on last line: all previous messages should load."""
        path = tmp_path / "sessions" / "telegram_12345.jsonl"
        lines = [
            _make_metadata_line(),
            _make_message_line("user", "hello"),
            _make_message_line("assistant", "hi there"),
            '{"role": "assistant", "content": "I was writ',  # truncated
        ]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")

        assert session is not None
        assert len(session.messages) == 2
        assert session.messages[0]["content"] == "hello"
        assert session.messages[1]["content"] == "hi there"

    def test_load_corrupt_middle_line(self, tmp_session_manager: SessionManager, tmp_path: Path):
        """Invalid JSON in middle: that line skipped, before and after load."""
        path = tmp_path / "sessions" / "telegram_12345.jsonl"
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
        path = tmp_path / "sessions" / "telegram_12345.jsonl"
        lines = ["NOT JSON", "ALSO NOT {{{", "STILL BAD"]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")

        assert session is None

    def test_load_completely_empty_file_returns_none(self, tmp_session_manager: SessionManager, tmp_path: Path):
        """Empty file: returns None."""
        path = tmp_path / "sessions" / "telegram_12345.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

        session = tmp_session_manager._load("telegram:12345")

        assert session is None
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

### Task 3: Implement resilient message line parsing

**Files:**
- Modify: `nanobot/session/manager.py:186-216` (`_load` method)

**Step 1: Refactor `_load()` to parse message lines individually**

Replace the current `_load()` method body (lines 186-216) with resilient parsing:

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
            line_num = 0
            parsed_any = False

            with open(path, encoding="utf-8") as f:
                for line in f:
                    line_num += 1
                    stripped = line.strip()
                    if not stripped:
                        continue

                    try:
                        data = json.loads(stripped)
                    except json.JSONDecodeError:
                        logger.warning(
                            "Corrupt line {} in session {} — skipping",
                            line_num, key,
                        )
                        continue

                    try:
                        if data.get("_type") == "metadata":
                            metadata = data.get("metadata", {})
                            try:
                                created_at = datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None
                            except (ValueError, TypeError):
                                logger.warning("Invalid created_at in session {}", key)
                                created_at = None
                            try:
                                last_consolidated = int(data.get("last_consolidated", 0))
                            except (ValueError, TypeError):
                                logger.warning("Invalid last_consolidated in session {}", key)
                                last_consolidated = 0
                        else:
                            messages.append(data)
                            parsed_any = True
                    except Exception:
                        logger.warning(
                            "Unexpected error parsing line {} in session {} — skipping",
                            line_num, key,
                        )
                        continue

            if not parsed_any and not metadata:
                return None

            return Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                metadata=metadata,
                last_consolidated=last_consolidated,
            )
        except Exception as e:
            logger.warning("Failed to load session {}: {}", key, e)
            return None
```

**Step 2: Run tests to verify they pass**

```bash
python -m pytest tests/test_session_resilient_load.py -v
```
Expected: All PASS

**Step 3: Run existing session tests to verify no regression**

```bash
python -m pytest tests/test_session_manager_history.py -v
```
Expected: All PASS (existing tests unchanged for valid files)

**Step 4: Commit**

```bash
git add nanobot/session/manager.py
git commit -m "fix(session): resilient load with per-line error recovery"
```

---

### Task 4: Write failing tests — corrupt metadata

**Files:**
- Modify: `tests/test_session_resilient_load.py`

**Step 1: Add tests for corrupt metadata fields**

Append to `tests/test_session_resilient_load.py`:

```python
class TestCorruptMetadata:
    def test_load_corrupt_metadata_created_at(self, tmp_session_manager: SessionManager, tmp_path: Path):
        """Invalid created_at in metadata: defaults to None, messages still load."""
        path = tmp_path / "sessions" / "telegram_12345.jsonl"
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
        """Invalid last_consolidated: defaults to 0, messages still load."""
        path = tmp_path / "sessions" / "telegram_12345.jsonl"
        lines = [
            _make_metadata_line(last_consolidated="abc"),
            _make_message_line("user", "hello"),
        ]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")

        assert session is not None
        assert session.last_consolidated == 0
        assert len(session.messages) == 1

    def test_load_metadata_missing_fields(self, tmp_session_manager: SessionManager, tmp_path: Path):
        """Metadata line with only _type: all fields get defaults, messages still load."""
        path = tmp_path / "sessions" / "telegram_12345.jsonl"
        lines = [
            json.dumps({"_type": "metadata"}),
            _make_message_line("user", "hello"),
        ]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")

        assert session is not None
        assert session.metadata == {}
        assert session.last_consolidated == 0
        assert len(session.messages) == 1

    def test_load_metadata_missing_last_consolidated(self, tmp_session_manager: SessionManager, tmp_path: Path):
        """Metadata without last_consolidated field: defaults to 0."""
        path = tmp_path / "sessions" / "telegram_12345.jsonl"
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
        assert session.metadata == {"foo": "bar"}
```

**Step 2: Run tests**

```bash
python -m pytest tests/test_session_resilient_load.py -v
```
Expected: All PASS (metadata resilience is already implemented in Task 3)

**Step 3: Commit**

```bash
git add tests/test_session_resilient_load.py
git commit -m "test: add corrupt metadata field tests"
```

---

### Task 5: Write failing tests — backup and cleanup

**Files:**
- Modify: `tests/test_session_resilient_load.py`

**Step 1: Add tests for corrupt backup creation and save cleanup**

Append to `tests/test_session_resilient_load.py`:

```python
class TestCorruptBackup:
    def test_load_backup_created_on_corrupt(self, tmp_session_manager: SessionManager, tmp_path: Path):
        """Corrupt file triggers backup creation as .jsonl.corrupt."""
        path = tmp_path / "sessions" / "telegram_12345.jsonl"
        lines = [
            _make_metadata_line(),
            _make_message_line("user", "hello"),
            "NOT VALID JSON {{{",
        ]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")

        assert session is not None
        assert (path.parent / "telegram_12345.jsonl.corrupt").exists()

    def test_load_backup_idempotent(self, tmp_session_manager: SessionManager, tmp_path: Path):
        """Second load with corrupt file does not overwrite existing backup."""
        path = tmp_path / "sessions" / "telegram_12345.jsonl"
        corrupt_path = path.parent / "telegram_12345.jsonl.corrupt"
        lines = [
            _make_metadata_line(),
            _make_message_line("user", "original content"),
            "NOT VALID JSON {{{",
        ]
        _write_session_file(path, lines)

        # First load — creates backup
        session1 = tmp_session_manager._load("telegram:12345")
        assert session1 is not None
        backup_content_1 = corrupt_path.read_text(encoding="utf-8")

        # Mutate the session file slightly
        lines.append(_make_message_line("user", "new content"))
        _write_session_file(path, lines)

        # Second load — should NOT overwrite backup
        session2 = tmp_session_manager._load("telegram:12345")
        assert session2 is not None
        backup_content_2 = corrupt_path.read_text(encoding="utf-8")

        assert backup_content_1 == backup_content_2  # unchanged

    def test_save_cleans_up_corrupt_backup(self, tmp_session_manager: SessionManager, tmp_path: Path):
        """After save(), the .corrupt backup is removed."""
        path = tmp_path / "sessions" / "telegram_12345.jsonl"
        corrupt_path = path.parent / "telegram_12345.jsonl.corrupt"
        lines = [
            _make_metadata_line(),
            _make_message_line("user", "hello"),
            "NOT VALID JSON {{{",
        ]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")
        assert session is not None
        assert corrupt_path.exists()

        tmp_session_manager.save(session)

        assert not corrupt_path.exists()

    def test_save_no_error_without_corrupt_backup(self, tmp_session_manager: SessionManager, tmp_path: Path):
        """save() works normally when no .corrupt backup exists."""
        path = tmp_path / "sessions" / "telegram_12345.jsonl"
        corrupt_path = path.parent / "telegram_12345.jsonl.corrupt"
        lines = [
            _make_metadata_line(),
            _make_message_line("user", "hello"),
        ]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")
        assert session is not None
        assert not corrupt_path.exists()

        # Should not raise
        tmp_session_manager.save(session)
        assert not corrupt_path.exists()
```

**Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_session_resilient_load.py::TestCorruptBackup -v
```
Expected: FAIL — backup logic not yet implemented

**Step 3: Commit test file**

```bash
git add tests/test_session_resilient_load.py
git commit -m "test: add failing tests for corrupt file backup and cleanup"
```

---

### Task 6: Implement backup and cleanup logic

**Files:**
- Modify: `nanobot/session/manager.py` (`_load` and `save` methods)

**Step 1: Add backup creation to `_load()`**

In the `_load()` method, add backup logic right before the `try` block that reads the file. Insert after `if not path.exists(): return None` and before the outer `try`:

```python
        corrupt_backup = path.with_suffix(".jsonl.corrupt")
        if not corrupt_backup.exists():
            shutil.copy2(path, corrupt_backup)
            logger.info("Backed up potentially corrupt session {} to {}", key, corrupt_backup.name)
```

**Step 2: Add cleanup to `save()`**

In the `save()` method, add cleanup logic at the end, after `self._cache[session.key] = session`:

```python
        corrupt_backup = path.with_suffix(".jsonl.corrupt")
        if corrupt_backup.exists():
            corrupt_backup.unlink()
```

**Step 3: Run all backup tests**

```bash
python -m pytest tests/test_session_resilient_load.py::TestCorruptBackup -v
```
Expected: All PASS

**Step 4: Run full test suite**

```bash
python -m pytest tests/test_session_resilient_load.py tests/test_session_manager_history.py -v
```
Expected: All PASS

**Step 5: Commit**

```bash
git add nanobot/session/manager.py
git commit -m "fix(session): backup corrupt files and cleanup on save"
```

---

### Task 7: Run linting and full test suite

**Files:**
- None (verification only)

**Step 1: Lint the changed file**

```bash
ruff check nanobot/session/manager.py
```
Expected: No errors

**Step 2: Format check**

```bash
ruff format --check nanobot/session/manager.py
```
Expected: No formatting issues (or auto-fix with `ruff format nanobot/session/manager.py`)

**Step 3: Run full project test suite**

```bash
python -m pytest tests/ -v --timeout=30
```
Expected: All PASS (no regressions)

**Step 4: Commit any lint fixes if needed**

```bash
git add -A
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
  --body "## Summary

\`SessionManager._load()\` currently returns \`None\` on any exception during JSONL parsing, causing complete session loss from a single corrupt line (e.g. truncated write during process restart).

This PR makes session loading resilient:

- **Per-line parsing**: Each JSONL line is parsed independently. A corrupt line is logged and skipped instead of failing the entire load.
- **Robust metadata**: Each metadata field (created_at, last_consolidated, metadata) is parsed individually with safe defaults on failure.
- **Corrupt file backup**: Before recovery, the corrupt file is backed up as \`.jsonl.corrupt\`. Backup creation is idempotent.
- **Cleanup on save**: After a successful \`save()\`, the \`.corrupt\` backup is automatically removed.

## Test plan

- [x] Truncated last line → all previous messages recovered
- [x] Corrupt middle line → line skipped, before/after messages recovered
- [x] All lines corrupt → returns None (fresh session)
- [x] Empty file → returns None
- [x] Invalid created_at/last_consolidated → safe defaults
- [x] Missing metadata fields → safe defaults
- [x] Corrupt file → .jsonl.corrupt backup created
- [x] Backup idempotent (no overwrite on second load)
- [x] save() cleans up .corrupt backup
- [x] Existing session tests pass (no regression)

Fixes context-loss scenario where process restart during \`save()\` (which uses \`open('w')\`) truncates the file before writing completes." \
  --base main \
  --head data219:fix/resilient-session-load
```
