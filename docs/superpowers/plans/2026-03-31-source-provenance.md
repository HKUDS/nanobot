# Source Provenance on Memory Events — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every memory event carries meaningful provenance (channel + tool hints) so the agent can distinguish where facts came from when they're injected into the prompt.

**Architecture:** Repurpose the existing `MemoryEvent.source` field (currently defaulting to `"chat"`) to carry `"channel,tool:hint,tool:hint"` strings. Add `source_timestamp` to metadata. Thread provenance from `message_processor.py` through the micro-extractor. Update `context_assembler.py` to render provenance in the prompt. No schema changes, no new files.

**Tech Stack:** Python 3.10+, pytest, pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-03-31-source-provenance-design.md`

**Key finding from exploration:** The full extractor (`MemoryExtractor.extract_structured_memory`) is not called from any production code path — only from tests. Only the `MicroExtractor` is wired into the production message processor pipeline. This plan focuses on `MicroExtractor` for the production path. The full extractor change is deferred (Task 5) since it's dead code in production.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `tests/test_source_provenance.py` | **Create** | All provenance unit tests |
| `nanobot/agent/message_processor.py` | **Modify** (lines 338-342) | Extract tool hints, pass to micro-extractor |
| `nanobot/memory/write/micro_extractor.py` | **Modify** (lines 97-126) | Accept provenance params, build source string, stamp events |
| `nanobot/memory/read/context_assembler.py` | **Modify** (lines 420-427) | Render `from: <source>` in prompt, drop `src=` |

---

### Task 1: Tool Hint Extraction — Tests and Implementation

Tests and implementation for `_extract_tool_hints()` — the boundary function in `message_processor.py` that converts `ToolAttempt` objects into primitive tool hint strings.

**Files:**
- Create: `tests/test_source_provenance.py`
- Modify: `nanobot/agent/message_processor.py`

- [ ] **Step 1: Write failing tests for `_extract_tool_hints`**

Create `tests/test_source_provenance.py`:

```python
"""Tests for source provenance on memory events."""

from __future__ import annotations

from nanobot.agent.turn_types import ToolAttempt


def _make_attempt(tool_name: str, arguments: dict | None = None) -> ToolAttempt:
    """Helper to build a ToolAttempt with sensible defaults."""
    return ToolAttempt(
        tool_name=tool_name,
        arguments=arguments or {},
        success=True,
        output_empty=False,
        output_snippet="some output",
        iteration=1,
    )


class TestExtractToolHints:
    """Tests for _extract_tool_hints in message_processor."""

    def test_non_exec_tool_uses_name_directly(self):
        from nanobot.agent.message_processor import _extract_tool_hints

        attempts = [_make_attempt("read_file", {"path": "/foo/bar.md"})]
        assert _extract_tool_hints(attempts) == ["read_file"]

    def test_exec_with_command_extracts_first_word(self):
        from nanobot.agent.message_processor import _extract_tool_hints

        attempts = [_make_attempt("exec", {"command": "obsidian search query=DS10540"})]
        assert _extract_tool_hints(attempts) == ["exec:obsidian"]

    def test_exec_without_command_arg_returns_exec(self):
        from nanobot.agent.message_processor import _extract_tool_hints

        attempts = [_make_attempt("exec", {"working_dir": "/tmp"})]
        assert _extract_tool_hints(attempts) == ["exec"]

    def test_deduplicates_identical_hints(self):
        from nanobot.agent.message_processor import _extract_tool_hints

        attempts = [
            _make_attempt("exec", {"command": "obsidian search query=DS10540"}),
            _make_attempt("exec", {"command": "obsidian files folder=DS10540"}),
            _make_attempt("exec", {"command": "obsidian search query=other"}),
        ]
        assert _extract_tool_hints(attempts) == ["exec:obsidian"]

    def test_mixed_tools_sorted_and_deduped(self):
        from nanobot.agent.message_processor import _extract_tool_hints

        attempts = [
            _make_attempt("exec", {"command": "obsidian files folder=DS10540"}),
            _make_attempt("read_file", {"path": "/foo/bar.md"}),
            _make_attempt("exec", {"command": "obsidian search query=test"}),
            _make_attempt("list_dir", {"path": "/foo"}),
        ]
        result = _extract_tool_hints(attempts)
        assert sorted(result) == sorted(result)  # already sorted
        assert set(result) == {"exec:obsidian", "list_dir", "read_file"}

    def test_empty_attempts_returns_empty(self):
        from nanobot.agent.message_processor import _extract_tool_hints

        assert _extract_tool_hints([]) == []

    def test_exec_with_empty_command_string(self):
        from nanobot.agent.message_processor import _extract_tool_hints

        attempts = [_make_attempt("exec", {"command": ""})]
        assert _extract_tool_hints(attempts) == ["exec"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_source_provenance.py::TestExtractToolHints -v`
Expected: FAIL — `_extract_tool_hints` not found in `message_processor`

- [ ] **Step 3: Implement `_extract_tool_hints`**

Add to the bottom of `nanobot/agent/message_processor.py`, after the existing `_build_no_answer_explanation` function (after line 624):

```python
def _extract_tool_hints(attempts: list[ToolAttempt]) -> list[str]:
    """Convert ToolAttempt objects to deduplicated, sorted tool hint strings.

    Non-exec tools use their name directly (e.g. ``"read_file"``).
    Exec tools extract the first word of the command argument
    (e.g. ``"exec:obsidian"``).  Deduplicates and sorts alphabetically.
    """
    hints: set[str] = set()
    for attempt in attempts:
        if attempt.tool_name != "exec":
            hints.add(attempt.tool_name)
            continue
        cmd = attempt.arguments.get("command", "")
        if isinstance(cmd, str) and cmd.strip():
            first_word = cmd.strip().split()[0]
            hints.add(f"exec:{first_word}")
        else:
            hints.add("exec")
    return sorted(hints)
```

Also add the import for `ToolAttempt` at the top of the file. It's already imported via `turn_types` — `TurnState` is imported at line 23. Add `ToolAttempt` to that import:

Change line 23 from:
```python
from nanobot.agent.turn_types import TurnState
```
to:
```python
from nanobot.agent.turn_types import ToolAttempt, TurnState
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_source_provenance.py::TestExtractToolHints -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Run linter and type checker**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_source_provenance.py nanobot/agent/message_processor.py
git commit -m "feat(memory): add _extract_tool_hints for source provenance"
```

---

### Task 2: Source String Building in MicroExtractor — Tests and Implementation

Tests and implementation for `_build_source()` and the new provenance parameters on `MicroExtractor.submit()`.

**Files:**
- Modify: `tests/test_source_provenance.py`
- Modify: `nanobot/memory/write/micro_extractor.py`

- [ ] **Step 1: Write failing tests for `_build_source` and provenance stamping**

Append to `tests/test_source_provenance.py`:

```python
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.memory.write.micro_extractor import MicroExtractor, _build_source


class TestBuildSource:
    """Tests for _build_source in micro_extractor."""

    def test_channel_only_no_tools(self):
        assert _build_source("cli", []) == "cli"

    def test_channel_with_tools(self):
        assert _build_source("cli", ["exec:obsidian", "read_file"]) == "cli,exec:obsidian,read_file"

    def test_empty_channel_defaults_to_unknown(self):
        assert _build_source("", ["read_file"]) == "unknown,read_file"

    def test_tools_are_sorted(self):
        result = _build_source("web", ["read_file", "exec:git", "exec:obsidian"])
        assert result == "web,exec:git,exec:obsidian,read_file"

    def test_duplicate_tools_deduped(self):
        result = _build_source("cli", ["exec:obsidian", "exec:obsidian", "read_file"])
        assert result == "cli,exec:obsidian,read_file"


def _make_tool_response(events: list[dict]) -> MagicMock:
    """Create a mock LLM response with a save_events tool call."""
    tc = MagicMock()
    tc.name = "save_events"
    tc.arguments = {"events": events}
    resp = MagicMock()
    resp.tool_calls = [tc]
    resp.content = None
    return resp


class TestMicroExtractorProvenance:
    """Tests that MicroExtractor stamps provenance on events."""

    def setup_method(self):
        self.provider = AsyncMock()
        self.ingester = MagicMock()
        self.ingester.append_events = MagicMock(return_value=1)

    def _make_extractor(self) -> MicroExtractor:
        return MicroExtractor(
            provider=self.provider,
            ingester=self.ingester,
            model="test-model",
            enabled=True,
        )

    @pytest.mark.asyncio
    async def test_submit_stamps_source_on_events(self):
        events = [{"type": "fact", "summary": "DS10540 duration is 186 days"}]
        self.provider.chat = AsyncMock(return_value=_make_tool_response(events))
        ext = self._make_extractor()

        import asyncio

        await ext.submit(
            "summarize DS10540",
            "Duration is 186 days",
            channel="cli",
            tool_hints=["exec:obsidian", "read_file"],
            turn_timestamp="2026-03-31T14:30:00",
        )
        await asyncio.sleep(0.1)

        self.ingester.append_events.assert_called_once()
        written = self.ingester.append_events.call_args[0][0]
        assert len(written) == 1
        assert written[0].source == "cli,exec:obsidian,read_file"
        assert written[0].metadata.get("source_timestamp") == "2026-03-31T14:30:00"

    @pytest.mark.asyncio
    async def test_submit_without_provenance_uses_defaults(self):
        """Backward compat: calling submit() without provenance params still works."""
        events = [{"type": "fact", "summary": "test fact"}]
        self.provider.chat = AsyncMock(return_value=_make_tool_response(events))
        ext = self._make_extractor()

        import asyncio

        await ext.submit("hello", "hi")
        await asyncio.sleep(0.1)

        self.ingester.append_events.assert_called_once()
        written = self.ingester.append_events.call_args[0][0]
        assert written[0].source == "chat"  # default, unchanged
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_source_provenance.py::TestBuildSource tests/test_source_provenance.py::TestMicroExtractorProvenance -v`
Expected: FAIL — `_build_source` not found, `submit()` doesn't accept new params

- [ ] **Step 3: Implement `_build_source` and update `MicroExtractor.submit`**

In `nanobot/memory/write/micro_extractor.py`:

Add the `_build_source` function after the `_MICRO_EXTRACT_TOOL` definition (after line 71):

```python
def _build_source(channel: str, tool_hints: list[str]) -> str:
    """Build a provenance source string from channel and tool hints.

    Returns a comma-separated string: channel first, then sorted unique
    tool hints.  E.g. ``"cli,exec:obsidian,read_file"``.
    """
    ch = channel or "unknown"
    parts = [ch] + sorted(set(tool_hints))
    return ",".join(p for p in parts if p)
```

Update the `submit` method signature (line 97) from:
```python
    async def submit(self, user_message: str, assistant_message: str) -> None:
```
to:
```python
    async def submit(
        self,
        user_message: str,
        assistant_message: str,
        *,
        channel: str = "",
        tool_hints: list[str] | None = None,
        turn_timestamp: str = "",
    ) -> None:
```

Update the `submit` method body. Change line 101 from:
```python
        task = asyncio.create_task(self._extract_and_ingest(user_message, assistant_message))
```
to:
```python
        task = asyncio.create_task(
            self._extract_and_ingest(
                user_message,
                assistant_message,
                channel=channel,
                tool_hints=tool_hints or [],
                turn_timestamp=turn_timestamp,
            )
        )
```

Update `_extract_and_ingest` signature (line 105) from:
```python
    async def _extract_and_ingest(self, user_message: str, assistant_message: str) -> None:
```
to:
```python
    async def _extract_and_ingest(
        self,
        user_message: str,
        assistant_message: str,
        *,
        channel: str,
        tool_hints: list[str],
        turn_timestamp: str,
    ) -> None:
```

In `_extract_and_ingest`, after the line `events = [MemoryEvent.from_dict(e) for e in raw_events]` (line 124), add provenance stamping before ingestion:

Change:
```python
            events = [MemoryEvent.from_dict(e) for e in raw_events]
            self._ingester.append_events(events)
```
to:
```python
            events = [MemoryEvent.from_dict(e) for e in raw_events]
            if channel or tool_hints:
                source = _build_source(channel, tool_hints)
                for event in events:
                    event.source = source
                    if turn_timestamp:
                        event.metadata["source_timestamp"] = turn_timestamp
            self._ingester.append_events(events)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_source_provenance.py -v`
Expected: All tests PASS (both Task 1 and Task 2 tests)

- [ ] **Step 5: Run linter, type checker, and existing micro-extraction tests**

Run: `make lint && make typecheck && python -m pytest tests/test_micro_extraction.py -v`
Expected: All PASS. Existing tests still work because `submit()` defaults are backward-compatible.

- [ ] **Step 6: Commit**

```bash
git add nanobot/memory/write/micro_extractor.py tests/test_source_provenance.py
git commit -m "feat(memory): add source provenance to MicroExtractor"
```

---

### Task 3: Thread Provenance Through message_processor

Wire `_extract_tool_hints` into the actual `submit()` call in `message_processor.py`.

**Files:**
- Modify: `nanobot/agent/message_processor.py`

- [ ] **Step 1: Update the micro-extractor call site**

In `nanobot/agent/message_processor.py`, change lines 338-342 from:

```python
        if self._micro_extractor is not None and final_content:
            await self._micro_extractor.submit(
                user_message=msg.content,
                assistant_message=final_content,
            )
```

to:

```python
        if self._micro_extractor is not None and final_content:
            _tool_log = (
                getattr(self._last_turn_result, "tool_results_log", [])
                if self._last_turn_result is not None
                else []
            )
            _hints = _extract_tool_hints(_tool_log) if _tool_log else []
            await self._micro_extractor.submit(
                user_message=msg.content,
                assistant_message=final_content,
                channel=msg.channel,
                tool_hints=_hints,
                turn_timestamp=datetime.now(timezone.utc).isoformat(),
            )
```

Note: `datetime` and `timezone` are already imported at line 13.

- [ ] **Step 2: Run linter and type checker**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 3: Run all existing tests to verify no regressions**

Run: `python -m pytest tests/test_micro_extraction.py tests/test_source_provenance.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add nanobot/agent/message_processor.py
git commit -m "feat(memory): thread provenance through message processor to micro-extractor"
```

---

### Task 4: Render Provenance in Prompt — Tests and Implementation

Update `context_assembler.py` to show `from: <source>` in memory items and drop the `src=` retrieval method.

**Files:**
- Modify: `tests/test_source_provenance.py`
- Modify: `nanobot/memory/read/context_assembler.py`

- [ ] **Step 1: Write failing tests for `_memory_item_line` changes**

Append to `tests/test_source_provenance.py`:

```python
from nanobot.memory.read.retrieval_types import RetrievalScores, RetrievedMemory


class TestMemoryItemLineProvenance:
    """Tests for provenance rendering in context_assembler._memory_item_line."""

    @staticmethod
    def _make_item(
        source: str = "",
        summary: str = "DS10540 planned duration is 186 days",
        event_type: str = "fact",
        timestamp: str = "2026-03-25T14:30:00",
        provider: str = "vector",
    ) -> RetrievedMemory:
        return RetrievedMemory(
            id="test-1",
            type=event_type,
            summary=summary,
            timestamp=timestamp,
            source=source,
            scores=RetrievalScores(semantic=0.85, recency=0.72, provider=provider),
        )

    def test_with_provenance_includes_from(self):
        from nanobot.memory.read.context_assembler import ContextAssembler

        item = self._make_item(source="cli,exec:obsidian,read_file")
        line = ContextAssembler._memory_item_line(item)
        assert "from: cli,exec:obsidian,read_file" in line
        assert "(fact, from: cli,exec:obsidian,read_file)" in line

    def test_legacy_chat_source_no_provenance_label(self):
        from nanobot.memory.read.context_assembler import ContextAssembler

        item = self._make_item(source="chat")
        line = ContextAssembler._memory_item_line(item)
        assert "from:" not in line
        assert "(fact)" in line

    def test_empty_source_no_provenance_label(self):
        from nanobot.memory.read.context_assembler import ContextAssembler

        item = self._make_item(source="")
        line = ContextAssembler._memory_item_line(item)
        assert "from:" not in line

    def test_no_retrieval_method_in_output(self):
        from nanobot.memory.read.context_assembler import ContextAssembler

        item = self._make_item(source="cli", provider="vector")
        line = ContextAssembler._memory_item_line(item)
        assert "src=" not in line
        assert "src=vector" not in line

    def test_scores_still_present(self):
        from nanobot.memory.read.context_assembler import ContextAssembler

        item = self._make_item(source="cli")
        line = ContextAssembler._memory_item_line(item)
        assert "sem=0.85" in line
        assert "rec=0.72" in line
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_source_provenance.py::TestMemoryItemLineProvenance -v`
Expected: FAIL — current `_memory_item_line` doesn't include `from:` and still has `src=`

- [ ] **Step 3: Update `_memory_item_line` in context_assembler.py**

In `nanobot/memory/read/context_assembler.py`, replace the `_memory_item_line` static method (lines 420-427):

From:
```python
    @staticmethod
    def _memory_item_line(item: RetrievedMemory) -> str:
        return (
            f"- [{item.timestamp[:16]}] ({item.type}) {item.summary} "
            f"[sem={item.scores.semantic:.2f}, "
            f"rec={item.scores.recency:.2f}, "
            f"src={item.scores.provider}]"
        )
```

To:
```python
    @staticmethod
    def _memory_item_line(item: RetrievedMemory) -> str:
        source = item.source
        if source and source != "chat":
            type_label = f"{item.type}, from: {source}"
        else:
            type_label = item.type
        return (
            f"- [{item.timestamp[:16]}] ({type_label}) {item.summary} "
            f"[sem={item.scores.semantic:.2f}, "
            f"rec={item.scores.recency:.2f}]"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_source_provenance.py -v`
Expected: All tests PASS

- [ ] **Step 5: Run linter, type checker, and broader test suite**

Run: `make lint && make typecheck && python -m pytest tests/test_context.py tests/test_context_builder.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add nanobot/memory/read/context_assembler.py tests/test_source_provenance.py
git commit -m "feat(memory): render source provenance in memory prompt lines"
```

---

### Task 5: Full Extractor — Deferred Provenance Support (Optional)

The full `MemoryExtractor.extract_structured_memory` is not called from production code. This task adds provenance parameter support for future use when it's wired in, matching the micro-extractor pattern.

**Files:**
- Modify: `nanobot/memory/write/extractor.py`
- Modify: `tests/test_source_provenance.py`

- [ ] **Step 1: Write test for full extractor provenance stamping**

Append to `tests/test_source_provenance.py`:

```python
import json


class TestFullExtractorProvenance:
    """Tests that MemoryExtractor stamps provenance when params provided."""

    def setup_method(self):
        from nanobot.memory.write.extractor import MemoryExtractor

        self.extractor = MemoryExtractor(
            to_str_list=lambda x: list(x) if isinstance(x, list) else [],
            coerce_event=self._coerce_event,
            utc_now_iso=lambda: "2026-03-31T00:00:00",
        )

    @staticmethod
    def _coerce_event(item: dict, **kwargs) -> "MemoryEvent | None":
        from nanobot.memory.event import MemoryEvent

        return MemoryEvent.from_dict(item)

    @pytest.mark.asyncio
    async def test_extract_stamps_source_when_provided(self):
        tc = MagicMock()
        tc.arguments = json.dumps({
            "events": [{"type": "fact", "summary": "test fact", "source_span": [0, 1]}],
            "profile_updates": {},
        })
        resp = MagicMock()
        resp.has_tool_calls = True
        resp.tool_calls = [tc]
        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=resp)

        events, _ = await self.extractor.extract_structured_memory(
            provider=provider,
            model="test",
            current_profile={},
            lines=["User: test"],
            old_messages=[{"role": "user", "content": "test"}],
            source_start=0,
            channel="whatsapp",
            tool_hints=["exec:obsidian"],
            turn_timestamp="2026-03-31T14:30:00",
        )

        assert len(events) == 1
        assert events[0].source == "whatsapp,exec:obsidian"
        assert events[0].metadata.get("source_timestamp") == "2026-03-31T14:30:00"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_source_provenance.py::TestFullExtractorProvenance -v`
Expected: FAIL — `extract_structured_memory` doesn't accept `channel`/`tool_hints`/`turn_timestamp`

- [ ] **Step 3: Add provenance parameters to `extract_structured_memory`**

In `nanobot/memory/write/extractor.py`, update the `extract_structured_memory` signature (line 129):

From:
```python
    async def extract_structured_memory(
        self,
        provider: LLMProvider,
        model: str,
        current_profile: dict[str, Any],
        lines: list[str],
        old_messages: list[dict[str, Any]],
        *,
        source_start: int,
    ) -> tuple[list[MemoryEvent], dict[str, list[str]]]:
```

To:
```python
    async def extract_structured_memory(
        self,
        provider: LLMProvider,
        model: str,
        current_profile: dict[str, Any],
        lines: list[str],
        old_messages: list[dict[str, Any]],
        *,
        source_start: int,
        channel: str = "",
        tool_hints: list[str] | None = None,
        turn_timestamp: str = "",
    ) -> tuple[list[MemoryEvent], dict[str, list[str]]]:
```

Add an import at the top of `extractor.py`, after the existing `from ..event import MemoryEvent` import (line 28):

```python
from .micro_extractor import _build_source
```

After the line `self.last_extraction_source = "llm"` (line 191), before `return events, updates` (line 192), add provenance stamping:

```python
                    self.last_extraction_source = "llm"
                    if channel or tool_hints:
                        _source = _build_source(channel, tool_hints or [])
                        for event in events:
                            event.source = _source
                            if turn_timestamp:
                                event.metadata["source_timestamp"] = turn_timestamp
                    return events, updates
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_source_provenance.py -v`
Expected: All tests PASS

- [ ] **Step 5: Run full check**

Run: `make lint && make typecheck && python -m pytest tests/ -x --ignore=tests/integration -q`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add nanobot/memory/write/extractor.py tests/test_source_provenance.py
git commit -m "feat(memory): add provenance support to full MemoryExtractor"
```

---

### Task 6: Final Validation

Run the full validation suite and verify everything works end-to-end.

**Files:** None (validation only)

- [ ] **Step 1: Run `make check`**

Run: `make check`
Expected: PASS (lint + typecheck + import-check + structure-check + prompt-check + phase-todo-check + doc-check)

- [ ] **Step 2: Run full unit test suite**

Run: `python -m pytest tests/ --ignore=tests/integration -v`
Expected: All PASS, no regressions

- [ ] **Step 3: Verify import boundaries**

Run: `make import-check`
Expected: PASS — `_build_source` is in `memory/write/`, `_extract_tool_hints` is in `agent/`, no cross-boundary violations

- [ ] **Step 4: Commit any final fixes if needed, then run pre-push**

Run: `make pre-push`
Expected: PASS
