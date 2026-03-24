# Resilient Session Load Implementation Plan (v7)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `SessionManager._load()` recover partial session data from corrupt JSONL files instead of discarding the entire session.

**Architecture:** Refactor `_load()` to parse metadata and message lines individually with per-line error handling. Use `last_consolidated = len(messages)` fallback when `last_consolidated` is untrustworthy, metadata line is missing, or a corrupt line was skipped *before* the consolidation boundary (position-aware index-shift protection) — no sentinel field, no cross-module changes. Clamp negative `last_consolidated` to `0` (upper-bound clamp removed — dead code, all consumers handle oversized values correctly via Python slice semantics).

**Tech Stack:** Python 3.11+, pytest, loguru, json

**Design Doc:** `docs/plans/2026-03-23-resilient-session-load-design.md`

**Branch:** `fix/resilient-session-load` (from `main`)
**Target:** `main` (Bug Fix, no behavior changes for valid files)

**Review findings addressed:** 14/14 (v6 deduplizierte Findings aus Runde 6) + 7/7 (v5 Runde 5) + 12/12 (v4 Runde 4) = 33 total

**Execution policy:** Tasks 1–4 may be executed autonomously. Task 5 (push) is autonomous. Task 6 (PR) requires **explicit user approval** before execution. The user may also choose to create the PR themselves.

---

### Task 1: Create feature branch + baseline verification

**Files:**
- Branch only

**Step 1: Create and switch to feature branch**

```bash
cd /root/.nanobot/workspace/forks/nanobot
git checkout main
git pull upstream main
git checkout -b fix/resilient-session-load
```

**Step 2: Verify branch**

```bash
git branch --show-current
```
Expected: `fix/resilient-session-load`

**Step 3: Baseline test run — verify existing tests pass before any changes**

```bash
python -m pytest tests/test_session_manager_history.py -v
```
Expected: All PASS (establishes baseline for regression detection)

---

### Task 2: Write all failing tests

**Files:**
- Create: `tests/test_session_resilient_load.py`

**Step 1: Write all 20 tests for corrupt message lines, corrupt metadata, bounds, index-shift, and roundtrip**

Create `tests/test_session_resilient_load.py`:

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


def _write_session_file_bytes(path: Path, data: bytes) -> None:
    """Helper: write raw bytes to a session JSONL file (for encoding tests)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _make_metadata_line(**overrides) -> str:
    """Helper: build a metadata JSONL line."""
    data = {
        "_type": "metadata",
        "key": "telegram:12345",
        "created_at": "2026-03-23T10:00:00",
        "updated_at": "2026-03-23T22:00:00",
        "metadata": {},
        "last_consolidated": 0,
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def _make_message_line(role: str, content: str, **kwargs) -> str:
    """Helper: build a message JSONL line."""
    data = {"role": role, "content": content, "timestamp": "2026-03-23T12:00:00", **kwargs}
    return json.dumps(data, ensure_ascii=False)


class TestCorruptMessageLines:
    def test_load_truncated_last_line(self, tmp_session_manager: SessionManager):
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
        # skipped_count > 0 but skip is AFTER boundary (lc=0) → no fallback
        assert session.last_consolidated == 0

    def test_load_corrupt_middle_line(self, tmp_session_manager: SessionManager):
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
        # skip at msg_index=1, lc=0 → not before boundary → no fallback
        assert session.last_consolidated == 0

    def test_load_all_lines_corrupt_returns_none(self, tmp_session_manager: SessionManager):
        """All lines invalid: returns None (fresh session)."""
        path = tmp_session_manager._get_session_path("telegram:12345")
        lines = ["NOT JSON", "ALSO NOT {{{", "STILL BAD"]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")

        assert session is None

    def test_load_completely_empty_file_returns_none(self, tmp_session_manager: SessionManager):
        """Empty file: returns None."""
        path = tmp_session_manager._get_session_path("telegram:12345")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

        session = tmp_session_manager._load("telegram:12345")

        assert session is None

    def test_load_non_dict_line_skipped(self, tmp_session_manager: SessionManager):
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
        # non-dict at msg_index=1, lc=0 → not before boundary → no fallback
        assert session.last_consolidated == 0

    def test_load_bom_file(self, tmp_session_manager: SessionManager):
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

    def test_load_recursion_error_line_skipped(self, tmp_session_manager: SessionManager):
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

    def test_load_unicode_decode_error_returns_none(self, tmp_session_manager: SessionManager):
        """Truncation mid-multi-byte UTF-8 → UnicodeDecodeError caught → None."""
        path = tmp_session_manager._get_session_path("telegram:12345")
        # Write bytes: valid metadata line + truncated line mid-é (0xc3 without 0xa9)
        data = (
            _make_metadata_line().encode("utf-8")
            + b"\n"
            + b'{"role":"user","content":"caf\xc3'
        )
        _write_session_file_bytes(path, data)

        session = tmp_session_manager._load("telegram:12345")

        assert session is None


class TestCorruptMetadata:
    def test_load_metadata_only_returns_session(self, tmp_session_manager: SessionManager):
        """Metadata-only file with empty metadata dict: returns Session (not None)."""
        path = tmp_session_manager._get_session_path("telegram:12345")
        lines = [_make_metadata_line()]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")

        assert session is not None
        assert session.messages == []
        assert session.metadata == {}
        assert session.last_consolidated == 0

    def test_load_corrupt_metadata_created_at(self, tmp_session_manager: SessionManager):
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

    def test_load_corrupt_metadata_last_consolidated(self, tmp_session_manager: SessionManager):
        """Invalid last_consolidated: falls back to len(messages) to prevent re-consolidation."""
        path = tmp_session_manager._get_session_path("telegram:12345")
        lines = [
            _make_metadata_line(last_consolidated="abc"),
            _make_message_line("user", "hello"),
        ]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")

        assert session is not None
        assert session.last_consolidated == 1  # len(messages)
        assert len(session.messages) == 1

    def test_load_metadata_missing_fields(self, tmp_session_manager: SessionManager):
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
        assert session.last_consolidated == 1  # len(messages)
        assert len(session.messages) == 1

    def test_load_corrupt_metadata_json_with_valid_messages(self, tmp_session_manager: SessionManager):
        """Entire metadata line is invalid JSON, but message lines are valid — recovered."""
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
        assert session.last_consolidated == 2  # len(messages) — no metadata parsed

    def test_load_non_dict_metadata_defaults_to_empty(self, tmp_session_manager: SessionManager):
        """Non-dict metadata field: defaults to empty dict, messages still load."""
        path = tmp_session_manager._get_session_path("telegram:12345")
        raw_metadata = (
            '{"_type":"metadata","key":"telegram:12345",'
            '"created_at":"2026-03-23T10:00:00","updated_at":"2026-03-23T22:00:00",'
            '"metadata":"not a dict","last_consolidated":0}'
        )
        lines = [raw_metadata, _make_message_line("user", "hello")]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")

        assert session is not None
        assert session.metadata == {}
        assert len(session.messages) == 1


class TestLastConsolidatedBounds:
    def test_load_negative_last_consolidated_clamped(self, tmp_session_manager: SessionManager):
        """Negative last_consolidated is clamped to 0."""
        path = tmp_session_manager._get_session_path("telegram:12345")
        lines = [
            _make_metadata_line(last_consolidated=-1),
            _make_message_line("user", "hello"),
        ]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")

        assert session is not None
        assert session.last_consolidated == 0
        assert len(session.messages) == 1

    def test_load_overflow_last_consolidated_clamped(self, tmp_session_manager: SessionManager):
        """JSON float 1e999 triggers OverflowError on int() → fallback to len(messages)."""
        path = tmp_session_manager._get_session_path("telegram:12345")
        # 1e999 → json.loads → float('inf') → int(float('inf')) → OverflowError
        raw_metadata = (
            '{"_type":"metadata","key":"telegram:12345",'
            '"created_at":"2026-03-23T10:00:00","updated_at":"2026-03-23T22:00:00",'
            '"metadata":{},"last_consolidated":1e999}'
        )
        lines = [raw_metadata, _make_message_line("user", "hello")]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")

        assert session is not None
        assert session.last_consolidated == 1  # len(messages)
        assert len(session.messages) == 1


class TestIndexShiftProtection:
    def test_load_skipped_line_before_consolidation_boundary(self, tmp_session_manager: SessionManager):
        """Corrupt line before last_consolidated boundary triggers index-shift protection."""
        path = tmp_session_manager._get_session_path("telegram:12345")
        lines = [
            _make_metadata_line(last_consolidated=3),
            _make_message_line("user", "msg0"),  # index 0
            "CORRUPT LINE {{{",                  # index 1 — skipped, BEFORE boundary (lc=3)
            _make_message_line("user", "msg2"),  # index 2 (shifted)
            _make_message_line("user", "msg3"),  # index 3 (shifted)
            _make_message_line("user", "msg4"),  # index 4 (shifted)
        ]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")

        assert session is not None
        assert len(session.messages) == 4  # 5 minus 1 corrupt
        # skipped_before_boundary=True → fallback: last_consolidated = len(messages) = 4
        assert session.last_consolidated == 4

    def test_load_skipped_line_after_consolidation_boundary(self, tmp_session_manager: SessionManager):
        """Corrupt line after boundary: last_consolidated stays unchanged."""
        path = tmp_session_manager._get_session_path("telegram:12345")
        lines = [
            _make_metadata_line(last_consolidated=2),
            _make_message_line("user", "msg0"),  # index 0 — consolidated
            _make_message_line("user", "msg1"),  # index 1 — consolidated
            _make_message_line("user", "msg2"),  # index 2 — unconsolidated
            "CORRUPT LINE {{{",                  # index 3 — skipped, AFTER boundary (lc=2)
        ]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")

        assert session is not None
        assert len(session.messages) == 3  # 4 minus 1 corrupt
        # skipped_before_boundary=False → NO fallback → last_consolidated stays at 2
        assert session.last_consolidated == 2


class TestMessagesOnlyNoMetadata:
    def test_load_messages_only_no_metadata(self, tmp_session_manager: SessionManager):
        """File with only message lines (no metadata): recovered with len(messages) fallback."""
        path = tmp_session_manager._get_session_path("telegram:12345")
        lines = [
            _make_message_line("user", "hello"),
            _make_message_line("assistant", "world"),
        ]
        _write_session_file(path, lines)

        session = tmp_session_manager._load("telegram:12345")

        assert session is not None
        assert len(session.messages) == 2
        # metadata_parsed=False → fallback: last_consolidated = len(messages) = 2
        assert session.last_consolidated == 2


class TestValidFileRoundtrip:
    def test_load_valid_file_roundtrip(self, tmp_session_manager: SessionManager):
        """Valid file saved by save() loads back via fresh SessionManager with key, messages,
        metadata, last_consolidated, and created_at intact."""
        fixed_time = datetime(2026, 1, 15, 12, 0, 0)
        session = Session(key="telegram:12345", metadata={"lang": "en"}, created_at=fixed_time)
        for i in range(10):
            session.add_message("user", f"msg{i}")
        session.last_consolidated = 7
        tmp_session_manager.save(session)

        # Fresh SessionManager with empty cache — forces _load() from disk
        fresh_manager = SessionManager(workspace=tmp_session_manager.workspace)
        loaded = fresh_manager._load("telegram:12345")

        assert loaded is not None
        assert loaded.key == "telegram:12345"
        assert len(loaded.messages) == 10
        assert loaded.messages[0]["content"] == "msg0"
        assert loaded.messages[9]["content"] == "msg9"
        assert loaded.metadata == {"lang": "en"}
        assert loaded.last_consolidated == 7
        assert loaded.created_at == fixed_time
```

**Step 2: Run tests to verify expected status**

```bash
cd /root/.nanobot/workspace/forks/nanobot
python -m pytest tests/test_session_resilient_load.py -v
```
Expected: Most FAIL (current `_load()` returns `None` for corrupt files). Note: `test_load_all_lines_corrupt_returns_none` and `test_load_unicode_decode_error_returns_none` may PASS against current code.

**Step 3: Commit test file**

```bash
git add tests/test_session_resilient_load.py
git commit -m "test: add 20 failing tests for resilient session loading"
```

---

### Task 3: Implement resilient `_load()`

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

            # Position-aware index-shift tracking:
            # If a corrupt line is skipped BEFORE the known consolidation boundary,
            # subsequent messages shift to lower indices, making the boundary unreliable.
            msg_index = 0
            skipped_before_boundary = False

            with open(path, encoding="utf-8-sig") as f:
                for line_num, raw in enumerate(f, 1):
                    stripped = raw.strip()
                    if not stripped:
                        continue
                    total_lines += 1

                    try:
                        data = json.loads(stripped)
                    except (json.JSONDecodeError, RecursionError):
                        logger.warning(
                            "Corrupt line {} in session {} at {} — skipping",
                            line_num, key, path,
                        )
                        skipped_count += 1
                        # Check if this skip is before the consolidation boundary
                        if metadata_parsed and msg_index < last_consolidated:
                            skipped_before_boundary = True
                        continue

                    if not isinstance(data, dict):
                        logger.warning(
                            "Non-dict JSON on line {} in session {} at {} — skipping",
                            line_num, key, path,
                        )
                        skipped_count += 1
                        if metadata_parsed and msg_index < last_consolidated:
                            skipped_before_boundary = True
                        continue

                    if data.get("_type") == "metadata":
                        # Parse metadata fields individually with safe defaults
                        raw_meta = data.get("metadata", {})
                        if not isinstance(raw_meta, dict):
                            logger.warning("Non-dict metadata in session {} at {}", key, path)
                            raw_meta = {}
                        metadata = raw_meta

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
                        msg_index += 1
                        recovered = True

            if not recovered:
                return None

            # Consolidation safety: when last_consolidated is untrustworthy,
            # metadata line missing, or a corrupt line was skipped before the
            # consolidation boundary (index-shift protection), assume all loaded
            # messages are already consolidated.
            if (last_consolidated_untrustworthy or not metadata_parsed or skipped_before_boundary) and messages:
                last_consolidated = len(messages)
                logger.warning(
                    "Consolidation boundary uncertain in session {} (skipped={}, "
                    "untrusted={}, no_metadata={}) — assuming all {} loaded messages "
                    "are consolidated",
                    key, skipped_count, last_consolidated_untrustworthy,
                    not metadata_parsed, len(messages),
                )

            # Lower-bound clamping for negative values.
            # Upper-bound clamp intentionally omitted: all consumers (get_history(),
            # pick_consolidation_boundary, retain_recent_legal_suffix) handle
            # last_consolidated > len(messages) correctly via Python slice semantics.
            if last_consolidated < 0:
                logger.warning(
                    "Negative last_consolidated ({}) in session {} — clamping to 0",
                    last_consolidated, key,
                )
                last_consolidated = 0

            if skipped_count > 0:
                logger.info(
                    "Session {} partially recovered: {}/{} lines loaded, {} skipped",
                    key, len(messages) + (1 if metadata_parsed else 0), total_lines, skipped_count,
                )

            return Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                metadata=metadata,
                last_consolidated=last_consolidated,
            )
        except (OSError, UnicodeDecodeError) as e:
            # Outer catch: I/O failures and encoding errors that prevent
            # reading the file at all. All parse errors are handled per-line above.
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

### Task 4: Verify & validate (lint + full test suite + edge cases)

**Files:**
- None (verification only)

**Step 1: Lint the changed files**

```bash
cd /root/.nanobot/workspace/forks/nanobot
ruff check nanobot/session/manager.py tests/test_session_resilient_load.py
```
Expected: No errors

**Step 2: Format check**

```bash
ruff format --check nanobot/session/manager.py tests/test_session_resilient_load.py
```
Expected: No formatting issues (or auto-fix with `ruff format`)

**Step 3: Run full project test suite**

```bash
python -m pytest tests/ -v 2>&1 | tail -30
```
Expected: All PASS (no regressions)

**Step 4: Run new tests with verbose output**

```bash
python -m pytest tests/test_session_resilient_load.py -v --tb=short
```
Expected: 20 tests, all PASS

**Step 5: Verify specific edge cases**

```bash
python -m pytest tests/test_session_resilient_load.py::TestIndexShiftProtection -v
python -m pytest tests/test_session_resilient_load.py::TestValidFileRoundtrip -v
python -m pytest tests/test_session_resilient_load.py::TestCorruptMetadata::test_load_non_dict_metadata_defaults_to_empty -v
python -m pytest tests/test_session_resilient_load.py::TestMessagesOnlyNoMetadata -v
```
Expected: All PASS

**Step 6: Verify no regressions in existing session tests**

```bash
python -m pytest tests/test_session_manager_history.py -v
```
Expected: All PASS

**Step 7: Commit any lint fixes if needed**

```bash
git add nanobot/session/manager.py tests/test_session_resilient_load.py
git commit -m "style: lint/format fixes" || true
```

---

### Task 5: Push to fork (autonomous)

**Step 1: Push feature branch to origin (fork)**

```bash
git push -u origin fix/resilient-session-load
```

No approval needed — push to fork is autonomous.

---

### Task 6: Create PR ⛔ GATE (requires explicit user approval)

> **Execution policy:** Task 6 requires **explicit user approval** before execution. The user may also choose to create the PR themselves.

**Step 0: Wait for user approval**

Before proceeding, present the completion summary from Tasks 1–4 and ask for approval to create the PR.

**Step 1: Create PR via gh CLI**

```bash
gh pr create --repo HKUDS/nanobot \
  --title "fix(session): resilient load with per-line error recovery" \
  --body '## Summary

`SessionManager._load()` currently returns `None` on any exception during JSONL parsing, causing complete session loss from a single corrupt line (e.g. truncated write during process restart).

This PR makes session loading resilient:

- **Per-line parsing**: Each JSONL line is parsed independently. A corrupt line is logged and skipped instead of failing the entire load.
- **Robust metadata**: Each metadata field (`created_at`, `last_consolidated`, `metadata`) is parsed individually with safe defaults on failure.
- **Consolidation safety**: When `last_consolidated` is corrupt, missing, the metadata line itself is invalid JSON, or a corrupt line was skipped *before* the consolidation boundary (position-aware index-shift protection), it defaults to `len(messages)` (assume all loaded messages are already consolidated), preventing re-consolidation and duplicate MEMORY.md/HISTORY.md entries.
- **Position-aware index-shift protection**: Unlike a blanket `skipped_count > 0` check, this PR tracks whether skipped lines fall before the consolidation boundary. Post-boundary corruption (the primary truncation scenario) leaves `last_consolidated` unchanged — unconsolidated messages remain visible to the LLM.
- **Lower-bound clamping**: Negative `last_consolidated` values are clamped to `0`. Upper-bound clamping is intentionally omitted — all consumers (`get_history()`, `pick_consolidation_boundary()`, `retain_recent_legal_suffix()`) handle `last_consolidated > len(messages)` correctly via Python slice semantics (`messages[N:]` → `[]`).
- **Encoding resilience**: Uses `utf-8-sig` encoding (BOM-tolerant). `UnicodeDecodeError` from mid-multi-byte truncation is caught gracefully.
- **Defensive guards**: Non-dict JSON values are skipped. `RecursionError` and `OverflowError` are caught.
- **Recovery logging**: Summary log after partial recovery (lines loaded vs skipped).

## Root cause

Process restart during `save()` (which uses `open("w")`) truncates the file before writing completes. A subsequent `_load()` fails on the truncated JSON, returning `None`.

**Follow-up:** Atomic save (write-to-tmp + `os.replace`) will be addressed in a separate PR to fix the root cause.

**Known:** `updated_at` is written by `save()` but not parsed by `_load()` — Session defaults to `datetime.now()`. This is pre-existing behavior and not a regression of this PR.

## Test plan

- [x] Truncated last line → all previous messages recovered, last_consolidated unchanged
- [x] Corrupt middle line → line skipped, before/after messages recovered
- [x] All lines corrupt → returns None (fresh session)
- [x] Empty file → returns None
- [x] Non-dict JSON line → skipped
- [x] UTF-8 BOM file → parsed correctly
- [x] RecursionError on deeply nested JSON → skipped
- [x] Mid-multi-byte UTF-8 truncation → returns None (no crash)
- [x] Metadata-only file (empty metadata dict) → returns Session (not None)
- [x] Invalid created_at → safe defaults
- [x] Invalid last_consolidated → fallback to len(messages)
- [x] Missing metadata fields → safe defaults + len(messages) fallback
- [x] Corrupt metadata JSON + valid messages → recovered with len(messages) fallback
- [x] Negative last_consolidated → clamped to 0
- [x] Overflow last_consolidated (1e999) → OverflowError → fallback to len(messages)
- [x] Skipped line before consolidation boundary → index-shift protection, fallback to len(messages)
- [x] Skipped line after consolidation boundary → last_consolidated unchanged (no over-consolidation)
- [x] Non-dict metadata field → defaults to empty dict
- [x] Messages only (no metadata line) → recovered with len(messages) fallback
- [x] Valid file roundtrip via fresh SessionManager → all fields including last_consolidated=7 and created_at intact
- [x] Existing session tests pass (no regression)' \
  --base main \
  --head data219:fix/resilient-session-load
```
