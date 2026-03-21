# Design: Typed Progress Events (Option C)

**Date:** 2026-03-21
**Status:** Approved
**Scope:** Callback protocol + test infrastructure
**Out of scope:** AgentLoop decomposition (CQ-H1) — to follow after this merges

---

## Problem

`ProgressCallback` in `loop.py` is a Protocol with 8 mutually exclusive keyword-only
parameters representing six distinct event types crammed into one function signature.
This design has three compounding defects:

1. **Manual discriminated union enforced by convention.** Nothing prevents a caller from
   passing `tool_call=` and `status_code=` simultaneously. The `_progress` closure handles
   this with a fragile `if/elif` chain on which kwarg is non-None.

2. **Suppressed type boundary.** `process_direct` declares `on_progress` as
   `Callable[[str], Awaitable[None]]` (simplified). Internally it is passed to
   `_run_agent_loop` which expects the full `ProgressCallback`. The mismatch is silenced
   with `# type: ignore[arg-type]` and a BP-M2 deferral comment.

3. **Untestable integration boundary.** `_cli_progress` is a closure inside the `agent`
   command function, capturing `agent_loop` and `console`. CLI tests mock `process_direct`
   entirely (`return "ok-response"`), so `_cli_progress` is never called in tests. The
   retry path (`_handle_llm_error` → `on_progress("", status_code="retrying")`) has no
   test coverage. This is how the `_cli_progress` kwarg crash survived undetected.

---

## Solution: Typed Event Hierarchy (Option C)

Replace the 8-kwarg Protocol with a proper discriminated union of typed event dataclasses.
Each event type maps to exactly one thing that happened. Consumers match on type; emitters
construct typed objects. Mutual exclusivity is enforced by the type system.

---

## Section 1: Event Type Hierarchy

**New module:** `nanobot/agent/callbacks.py`

```python
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
    status_code: str   # "thinking" | "retrying" | "calling_tool"
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
```

**Design decisions:**
- `frozen=True, slots=True` — events are value objects, consistent with `ToolResult`
- Separate module so consumers import only event types, not the 2,200-line `loop.py`
- The existing `ProgressCallback` Protocol in `loop.py:147-168` is deleted entirely
- The `# type: ignore[arg-type]` at `loop.py:1813` and BP-M2 comment are removed
- `nanobot/agent/__init__.py` must add `callbacks` exports to `__all__`

---

## Section 2: Migration of Call Sites

### `nanobot/agent/streaming.py` (2 sites)

```python
# Before
await on_progress("", status_code="thinking", status_label=label or "Thinking…")
await on_progress(full_clean, streaming=True)

# After
await on_progress(StatusEvent(status_code="thinking", label=label or "Thinking…"))
await on_progress(TextChunk(content=full_clean, streaming=True))
```

### `nanobot/agent/delegation.py` (3 sites)

```python
# Before
await self.on_progress("", delegate_start={"delegation_id": ..., ...})
await self.on_progress("", delegate_end={"delegation_id": ..., "success": True})
await self.on_progress("", delegate_end={"delegation_id": ..., "success": False})

# After
await self.on_progress(DelegateStartEvent(delegation_id=..., child_role=..., task_title=...))
await self.on_progress(DelegateEndEvent(delegation_id=..., success=True))
await self.on_progress(DelegateEndEvent(delegation_id=..., success=False))
```

### `nanobot/agent/loop.py` (5 sites + closure rewrite)

```python
# Before (scattered call sites)
await on_progress("", status_code="retrying")
await on_progress("", status_code="thinking")
await on_progress("", status_code="calling_tool")
await on_progress("", tool_call={"toolCallId": tc.id, "toolName": tc.name, "args": tc.arguments})
await on_progress("", tool_result={"toolCallId": tool_call.id, "result": result.to_llm_string()})

# After
await on_progress(StatusEvent(status_code="retrying"))
await on_progress(StatusEvent(status_code="thinking"))
await on_progress(StatusEvent(status_code="calling_tool"))
await on_progress(ToolCallEvent(tool_call_id=tc.id, tool_name=tc.name, args=tc.arguments))
await on_progress(ToolResultEvent(
    tool_call_id=tool_call.id,
    result=result.to_llm_string(),
    tool_name=tool_call.name,   # tool_call.name is available at this call site
))
```

Note: `tool_call.name` is available at the `tool_result` emit site in
`_process_tool_results`. Populating `ToolResultEvent.tool_name` here prevents a silent
downgrade where canonical tool-result events would otherwise lose the tool name.

### `_progress` closure rewrite

The `if/elif` chain in `_make_bus_progress` (loop.py:1537–1592) becomes a `match`.

`base_meta` (constructed upstream in `_process_message`) already contains
`{"_progress": True, ...channel/session fields...}`. The `dict(base_meta)` copy
preserves this key — no change needed.

The `_tool_hint` metadata key is preserved for `ToolCallEvent` so that
`ChannelManager._dispatch_outbound` (channels/manager.py:242-248) continues to gate
tool-hint messages correctly for production channels (Telegram, Discord, Slack, etc.).
The `send_tool_hints` check in `ChannelManager` reads `meta["_tool_hint"]`; removing
this key silently breaks that filter for all bot sessions.

```python
async def _progress(event: ProgressEvent) -> None:
    meta = dict(base_meta)  # inherits _progress=True from base_meta
    match event:
        case TextChunk(content=content, streaming=streaming):
            meta["_streaming"] = streaming
            if content:
                meta["_canonical"] = canonical_builder.text_flush(content)
        case ToolCallEvent(tool_call_id=tcid, tool_name=name, args=args):
            meta["_tool_hint"] = True   # preserved for ChannelManager gate
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
```

The `_make_bus_progress` return annotation (`-> ProgressCallback`) must import
`ProgressCallback` from `nanobot.agent.callbacks` after the Protocol is deleted from
`loop.py`. Add to `loop.py` imports:
```python
from nanobot.agent.callbacks import ProgressCallback, ProgressEvent, ...
```

### `process_direct` and `_process_message` signature updates

Both methods in `loop.py` use the old simplified type and must be updated together:

```python
# process_direct (line ~1937) — public entry point
on_progress: ProgressCallback | None = None

# _process_message (line ~1599) — internal propagation method
on_progress: ProgressCallback | None = None
```

Updating both removes the type mismatch that previously required `# type: ignore[arg-type]`
at line 1813.

### `commands.py` — `_silent` heartbeat callback

`commands.py` contains a second `on_progress` consumer used by the heartbeat path:

```python
# Before
async def _silent(*_args: Any, **_kwargs: Any) -> None:
    pass

# After — explicit ProgressEvent type for mypy compliance
async def _silent(event: ProgressEvent) -> None:  # noqa: ARG001
    pass
```

This is a one-line change. `_silent` stays in `commands.py`; it does not need extraction
since it has no logic to test.

---

## Section 3: Consumer Side — `CliProgressHandler`

`_cli_progress` is extracted from the `agent` command closure into a standalone,
independently-testable class.

**New module:** `nanobot/cli/progress.py`

Rationale for new file: `commands.py` imports Typer, Rich, and the full CLI stack.
Any test importing `CliProgressHandler` from `commands.py` drags all of that in.
`progress.py` only imports `Rich.Console`, `ChannelsConfig` (TYPE_CHECKING only), and
event types. This matches the reason `StreamingLLMCaller` was extracted from `loop.py`.

The project uses pytest-asyncio in auto mode (configured project-wide). New async test
files inherit this automatically; no per-file `asyncio_mode` setting is needed.

```python
from __future__ import annotations
from typing import TYPE_CHECKING
from rich.console import Console
from nanobot.agent.callbacks import (
    ProgressEvent, TextChunk, ToolCallEvent, ToolResultEvent,
    DelegateStartEvent, DelegateEndEvent, StatusEvent,
)

if TYPE_CHECKING:
    from nanobot.config.schema import ChannelsConfig


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

**`commands.py` wire-up** replaces the `_cli_progress` closure:

```python
handler = CliProgressHandler(console=console, channels_config=agent_loop.channels_config)
coro = agent_loop.process_direct(message, session_id, on_progress=handler)
```

---

## Section 4: Test Infrastructure

The project uses pytest-asyncio in auto mode. All async test functions are collected
automatically; no `@pytest.mark.asyncio` decorator is required in new test files.

### 4a — `tests/test_cli_progress.py` (CliProgressHandler unit tests)

Tests the handler in complete isolation — no CLI stack, no agent loop.

```python
from io import StringIO
from types import SimpleNamespace
from rich.console import Console
from nanobot.agent.callbacks import TextChunk, ToolCallEvent, StatusEvent
from nanobot.cli.progress import CliProgressHandler

def _handler(send_progress=True, send_tool_hints=True):
    buf = StringIO()
    ch = SimpleNamespace(send_progress=send_progress, send_tool_hints=send_tool_hints)
    return CliProgressHandler(Console(file=buf, highlight=False), channels_config=ch), buf

async def test_text_chunk_printed():
    h, buf = _handler()
    await h(TextChunk(content="hello"))
    assert "hello" in buf.getvalue()

async def test_text_chunk_suppressed_when_send_progress_off():
    h, buf = _handler(send_progress=False)
    await h(TextChunk(content="hello"))
    assert buf.getvalue() == ""

async def test_tool_call_printed_when_hints_on():
    h, buf = _handler(send_tool_hints=True)
    await h(ToolCallEvent(tool_call_id="1", tool_name="read_file", args={}))
    assert "read_file" in buf.getvalue()

async def test_tool_call_suppressed_when_hints_off():
    h, buf = _handler(send_tool_hints=False)
    await h(ToolCallEvent(tool_call_id="1", tool_name="read_file", args={}))
    assert buf.getvalue() == ""
```

### 4b — `tests/contract/test_progress_callbacks.py` (contract tests)

Validates every known `ProgressCallback` implementation against every event variant.
Adding a new event type to `callbacks.py` immediately fails this test for any consumer
that doesn't handle it. **This is the test that would have caught the original bug.**

When adding a new `ProgressCallback` implementation anywhere in the codebase, register
it in `all_known_callbacks()`.

```python
import pytest
from io import StringIO
from rich.console import Console
from nanobot.agent.callbacks import (
    TextChunk, ToolCallEvent, ToolResultEvent,
    DelegateStartEvent, DelegateEndEvent, StatusEvent,
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

def all_known_callbacks():
    """Registry of every ProgressCallback implementation in the codebase.
    Add new implementations here when they are created."""
    return [
        ("CliProgressHandler", CliProgressHandler(Console(file=StringIO()), channels_config=None)),
    ]

@pytest.mark.parametrize("name,callback", all_known_callbacks(), ids=lambda x: x if isinstance(x, str) else "")
@pytest.mark.parametrize("event", ALL_EVENT_VARIANTS, ids=repr)
async def test_callback_handles_all_event_variants(name, callback, event):
    """Every ProgressCallback must accept every ProgressEvent without raising."""
    await callback(event)
```

### 4c — `tests/test_cli_retry_path.py` (retry path integration)

Closes the layer-mocking gap. Uses real `AgentLoop` + `ScriptedProvider` configured to
fail then succeed. Asserts `StatusEvent(status_code="retrying")` flows end-to-end.

`make_agent_loop(provider)` is a new helper added to `tests/helpers.py` alongside
`ScriptedProvider`. It wraps `_make_loop(tmp_path, provider)` with a managed `tmp_path`
via `tempfile.mkdtemp()` so integration tests can construct a loop without a pytest
`tmp_path` fixture. Also add `error_response()`:

```python
# tests/helpers.py additions
import tempfile
from pathlib import Path

def make_agent_loop(provider: LLMProvider) -> AgentLoop:
    """Construct a minimal AgentLoop backed by the given provider.
    Uses a temporary directory for workspace; caller need not clean up."""
    tmp = Path(tempfile.mkdtemp())
    return _make_loop(tmp, provider)

def error_response(message: str = "quota exceeded") -> LLMResponse:
    """LLMResponse that triggers the retry path in _handle_llm_error."""
    return LLMResponse(content=message, finish_reason="error")
```

Tests:
```python
from tests.helpers import ScriptedProvider, make_agent_loop, error_response
from nanobot.agent.callbacks import ProgressEvent, StatusEvent
from nanobot.providers.base import LLMResponse

async def test_llm_error_emits_retrying_status_event():
    provider = ScriptedProvider([
        error_response(),
        LLMResponse(content="Hello, I can help!"),
    ])
    received: list[ProgressEvent] = []

    async def tracking(event: ProgressEvent) -> None:
        received.append(event)

    loop = make_agent_loop(provider)
    result = await loop.process_direct("hello", on_progress=tracking)

    retry_signals = [e for e in received if isinstance(e, StatusEvent) and e.status_code == "retrying"]
    assert len(retry_signals) == 1
    assert "Hello" in result

async def test_llm_error_three_times_returns_fallback_message():
    provider = ScriptedProvider([error_response(), error_response(), error_response()])
    received: list[ProgressEvent] = []

    async def tracking(event: ProgressEvent) -> None:
        received.append(event)

    loop = make_agent_loop(provider)
    result = await loop.process_direct("hello", on_progress=tracking)

    assert "trouble reaching the language model" in result
    retry_signals = [e for e in received if isinstance(e, StatusEvent) and e.status_code == "retrying"]
    assert len(retry_signals) == 2  # signals on attempt 1 and 2; attempt 3 breaks the loop
```

### 4d — Tool call event integration test (in `tests/test_agent_loop.py`)

Uses the existing `_make_loop(tmp_path, provider)` pattern already established in that
file. Verifies `ToolCallEvent` is emitted with the correct `tool_name` when a tool is
invoked.

```python
async def test_tool_call_emits_tool_call_event(tmp_path):
    provider = ScriptedProvider([
        LLMResponse(tool_calls=[ToolCall(name="read_file", arguments={"path": "/tmp"})]),
        LLMResponse(content="Done."),
    ])
    received: list[ProgressEvent] = []

    async def tracking(event: ProgressEvent) -> None:
        received.append(event)

    loop = _make_loop(tmp_path, provider)
    await loop.process_direct("read a file", on_progress=tracking)

    tool_events = [e for e in received if isinstance(e, ToolCallEvent)]
    assert any(e.tool_name == "read_file" for e in tool_events)
```

### 4e — Delegation event integration test (in `tests/test_delegation_dispatcher.py`)

The full delegation setup (AgentRegistry, Coordinator, two roles) is complex. This test
is **explicitly deferred** to a follow-up task. The contract test (4b) provides coverage
that `CliProgressHandler` can receive `DelegateStartEvent`/`DelegateEndEvent` without
raising. The emitter-side delegation test requires a dedicated spike to determine the
minimal setup needed in the existing `test_delegation_dispatcher.py` fixture pattern.

**Follow-up task:** Add `test_delegation_emits_delegate_start_end_events` once the
delegation test harness is understood. Acceptance criteria: one `DelegateStartEvent` and
one `DelegateEndEvent(success=True)` are received by a tracking callback when delegation
completes successfully.

---

## Files Changed

| File | Change |
|---|---|
| `nanobot/agent/callbacks.py` | **New** — event types + `ProgressCallback` type alias |
| `nanobot/agent/loop.py` | Delete Protocol (lines 147–168); add import from `callbacks`; remove `type: ignore` + BP-M2 comment; rewrite `_progress` closure; update 5 `on_progress` call sites; update `process_direct` + `_process_message` signatures |
| `nanobot/agent/streaming.py` | Update 2 call sites |
| `nanobot/agent/delegation.py` | Update 3 call sites |
| `nanobot/agent/__init__.py` | Add `callbacks` module exports to `__all__` |
| `nanobot/cli/progress.py` | **New** — `CliProgressHandler` |
| `nanobot/cli/__init__.py` | Add `CliProgressHandler` to `__all__` |
| `nanobot/cli/commands.py` | Replace `_cli_progress` closure with `CliProgressHandler` instantiation; update `_silent` callback signature |
| `tests/helpers.py` | Add `make_agent_loop()` and `error_response()` helpers |
| `tests/test_cli_progress.py` | **New** — 4a unit tests |
| `tests/contract/test_progress_callbacks.py` | **New** — 4b contract tests |
| `tests/test_cli_retry_path.py` | **New** — 4c integration tests |
| `tests/test_agent_loop.py` | Add 4d tool call event test |
| `tests/test_delegation_dispatcher.py` | 4e deferred — see note above |

---

## What This Prevents Going Forward

| Mechanism | Bug class prevented |
|---|---|
| 4a `test_cli_progress.py` | `CliProgressHandler` behavioural regressions |
| 4b `contract/test_progress_callbacks.py` | Silent event-type drift in any consumer |
| 4c `test_cli_retry_path.py` | Retry/error path invisible to tests |
| 4d tool call event test | Emitter-side regression in `loop.py` tool dispatch |
| Option C type system | Mutual exclusivity violations; missing required fields caught at construction |
| Removed `type: ignore` | mypy guards the `on_progress` boundary permanently |
| `_tool_hint` preserved in `ToolCallEvent` arm | `ChannelManager` tool-hint gate continues working for bot channels |
