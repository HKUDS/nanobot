# Typed Progress Events (Option C) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 8-kwarg `ProgressCallback` Protocol with a typed discriminated union of event dataclasses, extract `CliProgressHandler` into a testable class, and close the three test-coverage gaps that allowed the CLI progress crash to go undetected.

**Architecture:** New module `nanobot/agent/callbacks.py` defines six frozen event dataclasses and a `ProgressCallback = Callable[[ProgressEvent], Awaitable[None]]` type alias. All existing call sites in `loop.py`, `streaming.py`, and `delegation.py` are migrated to emit typed events. `_cli_progress` is extracted from the `agent` command closure into `nanobot/cli/progress.py::CliProgressHandler` (independently testable). Four test gaps are closed: unit tests for `CliProgressHandler`, a cross-event-type contract test, a retry-path integration test, and a tool-call emitter test.

**Tech Stack:** Python 3.10+, `dataclasses` (frozen, slots), pytest-asyncio (auto mode), `rich.console.Console`, mypy, ruff.

---

## Files Changed

| File | Change |
|---|---|
| `nanobot/agent/callbacks.py` | **New** — event dataclasses + `ProgressCallback` type alias |
| `nanobot/agent/loop.py` | Delete Protocol; add import; remove `type: ignore`; rewrite `_progress` closure; update 5 call sites + 2 signatures |
| `nanobot/agent/streaming.py` | Update 2 call sites |
| `nanobot/agent/delegation.py` | Update 3 call sites |
| `nanobot/agent/__init__.py` | Add `callbacks` module exports to `__all__` |
| `nanobot/cli/progress.py` | **New** — `CliProgressHandler` |
| `nanobot/cli/__init__.py` | Create `__all__` with `CliProgressHandler` |
| `nanobot/cli/commands.py` | Replace `_cli_progress` closure; update `_silent` signature |
| `tests/helpers.py` | Add `make_agent_loop()` and `error_response()` helpers |
| `tests/test_cli_progress.py` | **New** — 4a unit tests |
| `tests/contract/test_progress_callbacks.py` | **New** — 4b contract tests |
| `tests/test_cli_retry_path.py` | **New** — 4c integration tests |
| `tests/test_agent_loop.py` | Add 4d tool call event test |

---

## Task 1: Create `nanobot/agent/callbacks.py`

**Files:**
- Create: `nanobot/agent/callbacks.py`

This is the prerequisite for every other task. Pure data types — no logic, no tests needed. Run lint + typecheck as verification.

- [ ] **Step 1: Create the module**

```python
# nanobot/agent/callbacks.py
"""Typed progress event hierarchy for the agent callback protocol.

Replaces the 8-kwarg ProgressCallback Protocol in loop.py with a proper
discriminated union. Each event type represents exactly one thing that
happened. Consumers match on type; emitters construct typed objects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass(frozen=True, slots=True)
class TextChunk:
    """Streaming or final text content from the agent."""

    content: str
    streaming: bool = False


@dataclass(frozen=True, slots=True)
class ToolCallEvent:
    """Agent is invoking a tool."""

    tool_call_id: str
    tool_name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolResultEvent:
    """Tool has returned a result."""

    tool_call_id: str
    result: str
    tool_name: str = ""


@dataclass(frozen=True, slots=True)
class DelegateStartEvent:
    """Agent is delegating to a child agent."""

    delegation_id: str
    child_role: str
    task_title: str = ""


@dataclass(frozen=True, slots=True)
class DelegateEndEvent:
    """Child agent delegation completed."""

    delegation_id: str
    success: bool


@dataclass(frozen=True, slots=True)
class StatusEvent:
    """Lifecycle signal: thinking, retrying, calling_tool."""

    status_code: str  # "thinking" | "retrying" | "calling_tool"
    label: str = ""


ProgressEvent = (
    TextChunk
    | ToolCallEvent
    | ToolResultEvent
    | DelegateStartEvent
    | DelegateEndEvent
    | StatusEvent
)

ProgressCallback = Callable[[ProgressEvent], Awaitable[None]]

__all__ = [
    "DelegateEndEvent",
    "DelegateStartEvent",
    "ProgressCallback",
    "ProgressEvent",
    "StatusEvent",
    "TextChunk",
    "ToolCallEvent",
    "ToolResultEvent",
]
```

- [ ] **Step 2: Run lint + typecheck**

```bash
make lint && make typecheck
```

Expected: no errors in `nanobot/agent/callbacks.py`.

- [ ] **Step 3: Commit**

```bash
git add nanobot/agent/callbacks.py
git commit -m "feat: add typed progress event hierarchy (callbacks.py)"
```

---

## Task 2: TDD `CliProgressHandler` — write failing tests, then implement

**Files:**
- Create: `tests/test_cli_progress.py`
- Create: `nanobot/cli/progress.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli_progress.py
"""Unit tests for CliProgressHandler (4a).

Tests the handler in complete isolation — no CLI stack, no agent loop.
"""
from __future__ import annotations

from io import StringIO
from types import SimpleNamespace

import pytest
from rich.console import Console

from nanobot.agent.callbacks import (
    DelegateEndEvent,
    DelegateStartEvent,
    StatusEvent,
    TextChunk,
    ToolCallEvent,
    ToolResultEvent,
)
from nanobot.cli.progress import CliProgressHandler


def _handler(
    send_progress: bool = True, send_tool_hints: bool = True
) -> tuple[CliProgressHandler, StringIO]:
    buf = StringIO()
    ch = SimpleNamespace(send_progress=send_progress, send_tool_hints=send_tool_hints)
    return CliProgressHandler(Console(file=buf, highlight=False), channels_config=ch), buf


async def test_text_chunk_printed() -> None:
    h, buf = _handler()
    await h(TextChunk(content="hello"))
    assert "hello" in buf.getvalue()


async def test_text_chunk_suppressed_when_send_progress_off() -> None:
    h, buf = _handler(send_progress=False)
    await h(TextChunk(content="hello"))
    assert buf.getvalue() == ""


async def test_empty_text_chunk_produces_no_output() -> None:
    h, buf = _handler()
    await h(TextChunk(content=""))
    assert buf.getvalue() == ""


async def test_tool_call_printed_when_hints_on() -> None:
    h, buf = _handler(send_tool_hints=True)
    await h(ToolCallEvent(tool_call_id="tc1", tool_name="read_file", args={}))
    assert "read_file" in buf.getvalue()


async def test_tool_call_suppressed_when_hints_off() -> None:
    h, buf = _handler(send_tool_hints=False)
    await h(ToolCallEvent(tool_call_id="tc1", tool_name="read_file", args={}))
    assert buf.getvalue() == ""


async def test_no_channels_config_prints_text() -> None:
    """Without channels_config, handler defaults to printing everything."""
    buf = StringIO()
    h = CliProgressHandler(Console(file=buf, highlight=False), channels_config=None)
    await h(TextChunk(content="hi there"))
    assert "hi there" in buf.getvalue()


async def test_no_channels_config_prints_tool_calls() -> None:
    buf = StringIO()
    h = CliProgressHandler(Console(file=buf, highlight=False), channels_config=None)
    await h(ToolCallEvent(tool_call_id="tc1", tool_name="list_dir", args={}))
    assert "list_dir" in buf.getvalue()


async def test_status_event_silent() -> None:
    h, buf = _handler()
    await h(StatusEvent(status_code="retrying"))
    assert buf.getvalue() == ""


async def test_tool_result_event_silent() -> None:
    h, buf = _handler()
    await h(ToolResultEvent(tool_call_id="tc1", result="ok", tool_name="read_file"))
    assert buf.getvalue() == ""


async def test_delegate_start_event_silent() -> None:
    h, buf = _handler()
    await h(DelegateStartEvent(delegation_id="d1", child_role="research"))
    assert buf.getvalue() == ""


async def test_delegate_end_event_silent() -> None:
    h, buf = _handler()
    await h(DelegateEndEvent(delegation_id="d1", success=True))
    assert buf.getvalue() == ""
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_cli_progress.py -v
```

Expected: `ImportError: cannot import name 'CliProgressHandler' from 'nanobot.cli.progress'` (module does not exist yet).

- [ ] **Step 3: Implement `CliProgressHandler`**

```python
# nanobot/cli/progress.py
"""CLI progress event renderer.

Extracted from the _cli_progress closure in commands.py so that
CliProgressHandler can be instantiated and tested independently of the
full CLI command stack.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console

from nanobot.agent.callbacks import (
    DelegateEndEvent,
    DelegateStartEvent,
    ProgressEvent,
    StatusEvent,
    TextChunk,
    ToolCallEvent,
    ToolResultEvent,
)

if TYPE_CHECKING:
    from nanobot.config.schema import ChannelsConfig

__all__ = ["CliProgressHandler"]


class CliProgressHandler:
    """Renders agent progress events to the terminal.

    Extracted from the _cli_progress closure in commands.py so it can be
    instantiated and tested independently of the CLI command stack.
    """

    def __init__(
        self,
        console: Console,
        channels_config: ChannelsConfig | None = None,
    ) -> None:
        self._console = console
        self._channels_config = channels_config

    async def __call__(self, event: ProgressEvent) -> None:
        ch = self._channels_config
        match event:
            case TextChunk(content=content):
                if ch and not ch.send_progress:
                    return
                if content:
                    self._console.print(f"  [dim]↳ {content}[/dim]")
            case ToolCallEvent(tool_name=name):
                if ch and not ch.send_tool_hints:
                    return
                self._console.print(f"  [dim]↳ {name}(…)[/dim]")
            case StatusEvent() | ToolResultEvent() | DelegateStartEvent() | DelegateEndEvent():
                pass  # CLI does not render these; ignored explicitly
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_cli_progress.py -v
```

Expected: all 11 tests PASS.

- [ ] **Step 5: Lint + typecheck**

```bash
make lint && make typecheck
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add nanobot/cli/progress.py tests/test_cli_progress.py
git commit -m "feat: extract CliProgressHandler with unit tests (4a)"
```

---

## Task 3: Contract tests — every callback × every event variant (4b)

**Files:**
- Create: `tests/contract/test_progress_callbacks.py`

Contract tests ensure every known `ProgressCallback` implementation handles every `ProgressEvent` variant without raising. Adding a new event type to `callbacks.py` will immediately fail this test for any consumer that does not handle it. **This is the test class that would have caught the original bug.**

- [ ] **Step 1: Write the contract tests**

```python
# tests/contract/test_progress_callbacks.py
"""Contract tests: every ProgressCallback × every ProgressEvent variant (4b).

When adding a new ProgressCallback implementation anywhere in the codebase,
register it in all_known_callbacks(). When adding a new event type to
callbacks.py, add it to ALL_EVENT_VARIANTS.
"""
from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console

from nanobot.agent.callbacks import (
    DelegateEndEvent,
    DelegateStartEvent,
    StatusEvent,
    TextChunk,
    ToolCallEvent,
    ToolResultEvent,
)
from nanobot.cli.progress import CliProgressHandler

ALL_EVENT_VARIANTS = [
    TextChunk(content="hello", streaming=False),
    TextChunk(content="hello", streaming=True),
    TextChunk(content=""),
    ToolCallEvent(tool_call_id="tc1", tool_name="read_file", args={"path": "/tmp"}),
    ToolResultEvent(tool_call_id="tc1", result="contents", tool_name="read_file"),
    DelegateStartEvent(delegation_id="d1", child_role="research", task_title="Find info"),
    DelegateEndEvent(delegation_id="d1", success=True),
    DelegateEndEvent(delegation_id="d1", success=False),
    StatusEvent(status_code="thinking"),
    StatusEvent(status_code="retrying"),
    StatusEvent(status_code="calling_tool"),
]


def all_known_callbacks() -> list[tuple[str, CliProgressHandler]]:
    """Registry of every ProgressCallback implementation in the codebase.
    Add new implementations here when they are created."""
    return [
        (
            "CliProgressHandler",
            CliProgressHandler(Console(file=StringIO()), channels_config=None),
        ),
    ]


@pytest.mark.parametrize(
    "name,callback",
    all_known_callbacks(),
    ids=lambda x: x if isinstance(x, str) else "",
)
@pytest.mark.parametrize("event", ALL_EVENT_VARIANTS, ids=repr)
async def test_callback_handles_all_event_variants(
    name: str, callback: CliProgressHandler, event: object
) -> None:
    """Every ProgressCallback must accept every ProgressEvent without raising."""
    await callback(event)  # type: ignore[arg-type]
```

- [ ] **Step 2: Run tests to verify they pass**

```bash
python -m pytest tests/contract/test_progress_callbacks.py -v
```

Expected: 11 × 1 = 11 tests PASS. `CliProgressHandler` already handles all variants.

- [ ] **Step 3: Commit**

```bash
git add tests/contract/test_progress_callbacks.py
git commit -m "test: add progress callback contract tests (4b)"
```

---

## Task 4: Consolidate loop factory into `helpers.py`, add 4c tests

**Files:**
- Modify: `tests/helpers.py`
- Modify: `tests/test_agent_loop.py`
- Create: `tests/test_cli_retry_path.py`

The spec says `make_agent_loop` "wraps `_make_loop(tmp_path, provider)`." But `_make_loop` is a private function in `test_agent_loop.py`. Rather than duplicating the factory logic in two files (creating divergence risk), move the shared factory functions (`_make_config` and `_make_loop`) to `helpers.py` and update `test_agent_loop.py` to import from there.

Write the 4c tests before the loop migration. They will fail with ImportError (missing helpers) and then with assertion failures (loop still uses old signature). After Task 8 (loop migration), they will pass without changes.

- [ ] **Step 1: Move factory functions from `test_agent_loop.py` to `helpers.py`**

Add to `tests/helpers.py` (after the `ScriptedProvider` class). Add missing imports at top:

```python
import tempfile
from pathlib import Path

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentConfig


def _make_config(tmp_path: Path, **overrides: object) -> AgentConfig:
    """Build a minimal AgentConfig for tests. Mirrors the function in test_agent_loop.py."""
    defaults: dict[str, object] = dict(
        workspace=str(tmp_path),
        model="test-model",
        memory_window=10,
        max_iterations=5,
        planning_enabled=False,
        verification_mode="off",
    )
    defaults.update(overrides)
    return AgentConfig(**defaults)  # type: ignore[arg-type]


def _make_loop(tmp_path: Path, provider: LLMProvider, **config_overrides: object) -> AgentLoop:
    """Build a minimal AgentLoop for tests. Mirrors the function in test_agent_loop.py."""
    bus = MessageBus()
    config = _make_config(tmp_path, **config_overrides)
    return AgentLoop(bus, provider, config)


def make_agent_loop(provider: LLMProvider, **config_overrides: object) -> AgentLoop:
    """Construct a minimal AgentLoop backed by the given provider.

    Uses a temporary directory for workspace. Suitable for integration tests
    that do not receive a pytest tmp_path fixture.
    """
    tmp = Path(tempfile.mkdtemp())
    return _make_loop(tmp, provider, **config_overrides)


def error_response(message: str = "quota exceeded") -> LLMResponse:
    """Return an LLMResponse that triggers the retry path in _handle_llm_error."""
    return LLMResponse(content=message, finish_reason="error")
```

- [ ] **Step 2: Update `tests/test_agent_loop.py` to import shared factories from helpers**

Replace the private `_make_config` and `_make_loop` definitions in `test_agent_loop.py` with imports:

```python
# Remove these local definitions from test_agent_loop.py:
#   def _make_config(tmp_path: Path, **overrides) -> AgentConfig: ...
#   def _make_loop(tmp_path: Path, provider: LLMProvider, **config_overrides) -> AgentLoop: ...

# Add to imports from tests.helpers:
from tests.helpers import ScriptedProvider, _make_config, _make_loop
```

- [ ] **Step 3: Run existing tests to verify no regression**

```bash
python -m pytest tests/test_agent_loop.py -v
```

Expected: all tests PASS (no behaviour changed, only import source moved).

- [ ] **Step 4: Write the failing 4c tests**

```python
# tests/test_cli_retry_path.py
"""Integration tests for the LLM error/retry path (4c).

Closes the layer-mocking gap: CLI tests mocked process_direct entirely,
so _cli_progress was never called, and the retry StatusEvent path was
never exercised. These tests use a real AgentLoop + ScriptedProvider.
"""
from __future__ import annotations

from nanobot.agent.callbacks import ProgressEvent, StatusEvent
from nanobot.providers.base import LLMResponse
from tests.helpers import ScriptedProvider, error_response, make_agent_loop


async def test_llm_error_emits_retrying_status_event() -> None:
    """A single LLM error emits exactly one StatusEvent(retrying) then succeeds."""
    provider = ScriptedProvider(
        [
            error_response(),
            LLMResponse(content="Hello, I can help!"),
        ]
    )
    received: list[ProgressEvent] = []

    async def tracking(event: ProgressEvent) -> None:
        received.append(event)

    loop = make_agent_loop(provider)
    result = await loop.process_direct("hello", on_progress=tracking)

    retry_signals = [
        e for e in received if isinstance(e, StatusEvent) and e.status_code == "retrying"
    ]
    assert len(retry_signals) == 1
    assert "Hello" in result


async def test_llm_error_three_times_returns_fallback_message() -> None:
    """Three consecutive errors return the fallback message without crashing."""
    provider = ScriptedProvider(
        [error_response(), error_response(), error_response()]
    )
    received: list[ProgressEvent] = []

    async def tracking(event: ProgressEvent) -> None:
        received.append(event)

    loop = make_agent_loop(provider)
    result = await loop.process_direct("hello", on_progress=tracking)

    assert "trouble reaching the language model" in result
    retry_signals = [
        e for e in received if isinstance(e, StatusEvent) and e.status_code == "retrying"
    ]
    # Signals on attempt 1 and 2; attempt 3 breaks the loop
    assert len(retry_signals) == 2
```

- [ ] **Step 5: Run tests to verify they fail**

```bash
python -m pytest tests/test_cli_retry_path.py -v
```

Expected: FAIL — `loop.process_direct` still uses old `Callable[[str], Awaitable[None]]` signature, so `on_progress("", status_code="retrying")` raises `TypeError`.

- [ ] **Step 6: Lint + typecheck**

```bash
make lint && make typecheck
```

Expected: no errors in `tests/helpers.py`.

- [ ] **Step 7: Commit**

```bash
git add tests/helpers.py tests/test_agent_loop.py tests/test_cli_retry_path.py
git commit -m "refactor: move _make_loop/_make_config to helpers.py; add make_agent_loop/error_response + failing 4c tests"
```

---

## Task 5: Write failing 4d tool call event test

**Files:**
- Modify: `tests/test_agent_loop.py`

Write the 4d test now while the gap is clear. It will fail until Task 8 migrates `loop.py`. Add it to the existing `TestAgentLoopSingleTurn` class or a new class — use a new class for clarity.

- [ ] **Step 1: Add the failing test to `tests/test_agent_loop.py`**

Add this import at the top of the file (with existing imports). After Task 4's refactor, `_make_loop` is imported from `helpers` so the import section will already be updated; just add the callbacks imports:
```python
from nanobot.agent.callbacks import ProgressEvent, ToolCallEvent
```

Add this new test class at the end of the file:
```python
class TestProgressEvents:
    """Test that the agent emits correct typed progress events."""

    async def test_tool_call_emits_tool_call_event(self, tmp_path: Path) -> None:
        """ToolCallEvent is emitted with correct tool_name when a tool is invoked."""
        provider = ScriptedProvider(
            [
                LLMResponse(
                    tool_calls=[ToolCallRequest(id="tc1", name="read_file", arguments={"path": "/tmp/x"})]
                ),
                LLMResponse(content="Done."),
            ]
        )
        received: list[ProgressEvent] = []

        async def tracking(event: ProgressEvent) -> None:
            received.append(event)

        loop = _make_loop(tmp_path, provider)
        await loop.process_direct("read a file", on_progress=tracking)

        tool_events = [e for e in received if isinstance(e, ToolCallEvent)]
        assert any(e.tool_name == "read_file" for e in tool_events)
```

- [ ] **Step 2: Run the new test to verify it fails**

```bash
python -m pytest tests/test_agent_loop.py::TestProgressEvents -v
```

Expected: FAIL — either `TypeError` (old on_progress signature) or the test passes vacuously if the callback is never called. Confirm the test actually fails.

- [ ] **Step 3: Commit**

```bash
git add tests/test_agent_loop.py
git commit -m "test: add failing 4d tool call event test"
```

---

## Task 6: Migrate `nanobot/agent/streaming.py` (2 call sites)

**Files:**
- Modify: `nanobot/agent/streaming.py`

- [ ] **Step 1: Add import**

At the top of `streaming.py`, add to the existing imports:
```python
from nanobot.agent.callbacks import ProgressCallback, ProgressEvent, StatusEvent, TextChunk
```

Update the existing import line:
```python
# Before
from typing import TYPE_CHECKING, Any, Awaitable, Callable

# After — remove Awaitable and Callable if no longer used here,
# or keep them if used elsewhere in the file
from typing import TYPE_CHECKING, Any
```

Update the `on_progress` parameter type in `StreamingLLMCaller.call`:
```python
# Before
on_progress: Callable[..., Awaitable[None]] | None,

# After
on_progress: ProgressCallback | None,
```

- [ ] **Step 2: Update call site 1 — thinking status**

```python
# Before (around line 152)
await on_progress("", status_code="thinking", status_label=label or "Thinking…")

# After
await on_progress(StatusEvent(status_code="thinking", label=label or "Thinking…"))
```

- [ ] **Step 3: Update call site 2 — streaming text**

```python
# Before (around line 156)
await on_progress(full_clean, streaming=True)

# After
await on_progress(TextChunk(content=full_clean, streaming=True))
```

- [ ] **Step 4: Run lint + typecheck**

```bash
make lint && make typecheck
```

Expected: no errors. Note: mypy may report errors in `loop.py` (not yet migrated) — those are expected and will be resolved in Task 7.

- [ ] **Step 5: Commit**

```bash
git add nanobot/agent/streaming.py
git commit -m "refactor: migrate streaming.py to typed ProgressEvent callbacks"
```

---

## Task 7: Migrate `nanobot/agent/delegation.py` (3 call sites)

**Files:**
- Modify: `nanobot/agent/delegation.py`

- [ ] **Step 1: Add import**

```python
# Add to existing imports in delegation.py
from nanobot.agent.callbacks import (
    DelegateEndEvent,
    DelegateStartEvent,
    ProgressCallback,
)
```

Update the `on_progress` attribute and parameter type:
```python
# In __init__ parameter list (around line 212)
on_progress: ProgressCallback | None = None,

# In attribute assignment (around line 274)
self.on_progress: ProgressCallback | None = on_progress
```

Remove `Awaitable`, `Callable` from `typing` imports if no longer used. Keep if still needed elsewhere in the file.

- [ ] **Step 2: Update call site 1 — delegate start**

```python
# Before (around line 765)
await self.on_progress(
    "",
    delegate_start={
        "delegation_id": delegation_id,
        "child_role": ...,
        "task_title": ...,
    },
)

# After
await self.on_progress(
    DelegateStartEvent(
        delegation_id=delegation_id,
        child_role=child_role,   # the local variable already set above
        task_title=task_title,   # the local variable already set above
    )
)
```

- [ ] **Step 3: Update call sites 2 and 3 — delegate end (success + failure)**

```python
# Before success path (around line 804)
await self.on_progress(
    "",
    delegate_end={"delegation_id": delegation_id, "success": True},
)

# After
await self.on_progress(DelegateEndEvent(delegation_id=delegation_id, success=True))

# Before failure path (around line 828)
await self.on_progress(
    "",
    delegate_end={"delegation_id": delegation_id, "success": False},
)

# After
await self.on_progress(DelegateEndEvent(delegation_id=delegation_id, success=False))
```

- [ ] **Step 4: Run lint + typecheck**

```bash
make lint && make typecheck
```

Expected: no errors in `delegation.py`. Residual errors in `loop.py` are expected until Task 8.

- [ ] **Step 5: Commit**

```bash
git add nanobot/agent/delegation.py
git commit -m "refactor: migrate delegation.py to typed ProgressEvent callbacks"
```

---

## Task 8: Migrate `nanobot/agent/loop.py` (Protocol deletion + 5 call sites + closure rewrite)

**Files:**
- Modify: `nanobot/agent/loop.py`

This is the largest single change. After this task, the 4c and 4d tests will pass.

- [ ] **Step 1: Delete the `ProgressCallback` Protocol (lines 147–168)**

Delete the entire class:
```python
# DELETE this entire block (lines 147-168)
class ProgressCallback(Protocol):
    """Signature for progress callbacks passed through the agent call chain.
    ...
    """
    async def __call__(
        self,
        content: str,
        *,
        tool_hint: bool = ...,
        streaming: bool = ...,
        tool_call: dict | None = ...,
        tool_result: dict | None = ...,
        delegate_start: dict | None = ...,
        delegate_end: dict | None = ...,
        status_code: str = ...,
        status_label: str = ...,
    ) -> None:
        pass
```

- [ ] **Step 2: Add import from `callbacks` module**

In the imports section of `loop.py`, add:
```python
from nanobot.agent.callbacks import (
    DelegateEndEvent,
    DelegateStartEvent,
    ProgressCallback,
    ProgressEvent,
    StatusEvent,
    TextChunk,
    ToolCallEvent,
    ToolResultEvent,
)
```

Remove `Protocol` from the `typing` import if `ProgressCallback` was the only Protocol in `loop.py`. Check for other Protocol uses first with a quick search.

- [ ] **Step 3: Update `process_direct` signature (line ~1937)**

```python
# Before
on_progress: Callable[[str], Awaitable[None]] | None = None,

# After
on_progress: ProgressCallback | None = None,
```

- [ ] **Step 4: Update `_process_message` signature (line ~1599)**

```python
# Before
on_progress: Callable[[str], Awaitable[None]] | None = None,

# After
on_progress: ProgressCallback | None = None,
```

- [ ] **Step 5: Remove `type: ignore[arg-type]` and BP-M2 comment (line ~1813)**

```python
# Before
on_progress=(on_progress or _bus_progress) if self.config.streaming_enabled else None,  # type: ignore[arg-type]

# After
on_progress=(on_progress or _bus_progress) if self.config.streaming_enabled else None,
```

(Remove the `# type: ignore[arg-type]` comment and the multi-line BP-M2 comment above it.)

- [ ] **Step 6: Update call site — `_handle_llm_error` (line ~660)**

```python
# Before
await on_progress("", status_code="retrying")

# After
await on_progress(StatusEvent(status_code="retrying"))
```

- [ ] **Step 7: Update call site — `_run_agent_loop` thinking status (line ~1067)**

```python
# Before
await on_progress("", status_code="thinking")

# After
await on_progress(StatusEvent(status_code="thinking"))
```

- [ ] **Step 8: Update call site — calling_tool status (line ~1155)**

```python
# Before
await on_progress("", status_code="calling_tool")

# After
await on_progress(StatusEvent(status_code="calling_tool"))
```

- [ ] **Step 9: Update call sites — tool_call events (line ~1157)**

```python
# Before
for tc in response.tool_calls:
    await on_progress(
        "",
        tool_call={
            "toolCallId": tc.id,
            "toolName": tc.name,
            "args": tc.arguments,
        },
    )

# After
for tc in response.tool_calls:
    await on_progress(
        ToolCallEvent(
            tool_call_id=tc.id,
            tool_name=tc.name,
            args=tc.arguments,
        )
    )
```

- [ ] **Step 10: Update call site — tool_result event (line ~752)**

```python
# Before
await on_progress(
    "",
    tool_result={
        "toolCallId": tool_call.id,
        "result": result.to_llm_string(),
    },
)

# After
await on_progress(
    ToolResultEvent(
        tool_call_id=tool_call.id,
        result=result.to_llm_string(),
        tool_name=tool_call.name,   # populate to prevent silent downgrade in canonical event
    )
)
```

- [ ] **Step 11: Rewrite `_progress` closure in `_make_bus_progress`**

Replace the entire `_progress` async function body (lines ~1537–1592) and its return type annotation:

```python
# Change return type annotation from:
def _make_bus_progress(
    self,
    channel: str,
    chat_id: str,
    base_meta: dict,
    canonical_builder: CanonicalEventBuilder,
) -> ProgressCallback:

# (The return type annotation now correctly reflects ProgressCallback from callbacks)
```

Replace the `_progress` closure body:

```python
        async def _progress(event: ProgressEvent) -> None:
            meta = dict(base_meta)  # inherits _progress=True from base_meta
            match event:
                case TextChunk(content=content, streaming=streaming):
                    meta["_streaming"] = streaming
                    if content:
                        meta["_canonical"] = canonical_builder.text_flush(content)
                case ToolCallEvent(tool_call_id=tcid, tool_name=name, args=args):
                    meta["_tool_hint"] = True  # preserved for ChannelManager gate
                    meta["_tool_call"] = {"toolCallId": tcid, "toolName": name, "args": args}
                    meta["_canonical"] = canonical_builder.tool_call(
                        tool_call_id=tcid, tool_name=name, args=args
                    )
                case ToolResultEvent(tool_call_id=tcid, result=result, tool_name=name):
                    meta["_tool_result"] = {"toolCallId": tcid, "result": result}
                    meta["_canonical"] = canonical_builder.tool_result(
                        tool_call_id=tcid, tool_name=name, result=result
                    )
                case DelegateStartEvent(delegation_id=did, child_role=role, task_title=title):
                    meta["_canonical"] = canonical_builder.delegate_start(
                        delegation_id=did, child_role=role, task_title=title
                    )
                case DelegateEndEvent(delegation_id=did, success=success):
                    meta["_canonical"] = canonical_builder.delegate_end(
                        delegation_id=did, success=success
                    )
                case StatusEvent(status_code=code, label=label):
                    meta["_canonical"] = canonical_builder.status(code, label=label)
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=channel,
                    chat_id=chat_id,
                    content=event.content if isinstance(event, TextChunk) else "",
                    metadata=meta,
                )
            )

        return _progress
```

Also remove the old `# type: ignore[return-value]` at the end of `_make_bus_progress` (the old `return _progress  # type: ignore[return-value]` line).

- [ ] **Step 12: Run lint + typecheck**

```bash
make lint && make typecheck
```

Expected: no errors. The `type: ignore[arg-type]` is gone; mypy now validates the boundary.

- [ ] **Step 13: Run the 4c and 4d tests to verify they pass**

```bash
python -m pytest tests/test_cli_retry_path.py tests/test_agent_loop.py::TestProgressEvents -v
```

Expected: all tests PASS.

- [ ] **Step 14: Run full test suite**

```bash
make test
```

Expected: all existing tests continue to pass.

- [ ] **Step 15: Commit**

```bash
git add nanobot/agent/loop.py
git commit -m "refactor: migrate loop.py to typed ProgressEvent — delete Protocol, rewrite closure, remove type: ignore"
```

---

## Task 9: Update `nanobot/agent/__init__.py`

**Files:**
- Modify: `nanobot/agent/__init__.py`

- [ ] **Step 1: Add `callbacks` import and exports**

```python
# Add import line (after existing imports, alphabetically):
from nanobot.agent.callbacks import (
    DelegateEndEvent,
    DelegateStartEvent,
    ProgressCallback,
    ProgressEvent,
    StatusEvent,
    TextChunk,
    ToolCallEvent,
    ToolResultEvent,
)
```

Add to `__all__` list (alphabetically):
```python
"DelegateEndEvent",
"DelegateStartEvent",
"ProgressCallback",
"ProgressEvent",
"StatusEvent",
"TextChunk",
"ToolCallEvent",
"ToolResultEvent",
```

- [ ] **Step 2: Run lint + typecheck**

```bash
make lint && make typecheck
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add nanobot/agent/__init__.py
git commit -m "feat: export callbacks module types from nanobot.agent"
```

---

## Task 10: Update `nanobot/cli/__init__.py`

**Files:**
- Modify: `nanobot/cli/__init__.py`

Currently `nanobot/cli/__init__.py` has no `__all__` (just a module docstring). Add one.

- [ ] **Step 1: Add import and `__all__`**

```python
# nanobot/cli/__init__.py
"""CLI module for nanobot."""

from __future__ import annotations

from nanobot.cli.progress import CliProgressHandler

__all__ = ["CliProgressHandler"]
```

- [ ] **Step 2: Run lint + typecheck**

```bash
make lint && make typecheck
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add nanobot/cli/__init__.py
git commit -m "feat: add __all__ to nanobot.cli with CliProgressHandler export"
```

---

## Task 11: Update `nanobot/cli/commands.py`

**Files:**
- Modify: `nanobot/cli/commands.py`

Replace the `_cli_progress` closure with a `CliProgressHandler` instantiation. Update `_silent` signature.

- [ ] **Step 1: Add import for `CliProgressHandler`**

In the imports section of `commands.py`, add:
```python
from nanobot.cli.progress import CliProgressHandler
```

Also add to the `callbacks` imports (add after the existing nanobot imports):
```python
from nanobot.agent.callbacks import ProgressEvent
```

- [ ] **Step 2: Replace `_cli_progress` closure with `CliProgressHandler` instantiation**

Find and delete the entire `_cli_progress` closure (the `async def _cli_progress(content, *, tool_hint, streaming, status_code, status_label, **_kwargs)` function definition).

Replace the closure usage:
```python
# Before
coro = agent_loop.process_direct(message, session_id, on_progress=_cli_progress)

# After
handler = CliProgressHandler(
    console=console, channels_config=agent_loop.channels_config
)
coro = agent_loop.process_direct(message, session_id, on_progress=handler)
```

The `handler` variable should be defined once before the `run_once()` async function that uses it (or inside it — the closure already captures `console` and `agent_loop` so either works; prefer defining it once outside `run_once`).

- [ ] **Step 3: Update `_silent` callback signature in the heartbeat path**

```python
# Before (around line 508)
async def _silent(*_args: Any, **_kwargs: Any) -> None:
    pass

# After
async def _silent(event: ProgressEvent) -> None:  # noqa: ARG001
    pass
```

- [ ] **Step 4: Remove unused `Any` import if no longer needed**

Check if `Any` is still used elsewhere in `commands.py` after removing `_silent`'s `*_args: Any, **_kwargs: Any`. If not, remove it from `from typing import Any`.

- [ ] **Step 5: Run lint + typecheck**

```bash
make lint && make typecheck
```

Expected: no errors.

- [ ] **Step 6: Run full test suite**

```bash
make test
```

Expected: all tests pass including `tests/test_cli_progress.py` and `tests/contract/test_progress_callbacks.py`.

- [ ] **Step 7: Commit**

```bash
git add nanobot/cli/commands.py
git commit -m "refactor: replace _cli_progress closure with CliProgressHandler; update _silent signature"
```

---

## Task 12: Full validation

- [ ] **Step 1: Run the complete validation pipeline**

```bash
make check
```

Expected: lint + typecheck + import-check + prompt-check + test all pass (85% coverage gate).

- [ ] **Step 2: Verify key coverage assertions**

```bash
python -m pytest tests/test_cli_progress.py tests/contract/test_progress_callbacks.py tests/test_cli_retry_path.py tests/test_agent_loop.py::TestProgressEvents -v
```

Expected: all 4a + 4b + 4c + 4d tests PASS.

- [ ] **Step 3: Review documentation for accuracy**

Check that docstrings in `callbacks.py`, `progress.py`, and the updated `loop.py` are accurate. No CHANGELOG or ADR updates are required for this internal refactor.

- [ ] **Step 4: Final commit**

```bash
git commit --allow-empty -m "chore: full validation pass for typed progress events (Option C)"
```

(Use `--allow-empty` only if there are no remaining file changes. If Step 3 produced edits, commit those files normally.)

---

## Summary of Test Coverage Gained

| Test file | Gap closed |
|---|---|
| `tests/test_cli_progress.py` (4a) | `CliProgressHandler` behavioral regressions — the class that would have caught the original crash |
| `tests/contract/test_progress_callbacks.py` (4b) | Silent event-type drift in any callback consumer |
| `tests/test_cli_retry_path.py` (4c) | Retry/error path previously invisible to all tests |
| `tests/test_agent_loop.py::TestProgressEvents` (4d) | Emitter-side regression in `loop.py` tool dispatch |
| Removed `type: ignore[arg-type]` | mypy permanently guards the `on_progress` boundary |
| Option C type system | Mutual exclusivity violations; missing required fields caught at construction time |
