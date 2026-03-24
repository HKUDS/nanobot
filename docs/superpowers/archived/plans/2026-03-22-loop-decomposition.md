# AgentLoop Decomposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate `AgentLoop` (1,948 lines) into three focused modules — `AgentRuntime`, `MessageProcessor`, and `TurnOrchestrator` — by extracting `_make_bus_progress`, `_process_message`, and `_run_agent_loop` into dedicated files with explicit `TurnState`.

**Architecture:** Single branch `refactor/loop-decomposition`. Five migration steps in dependency order: bus_progress → MessageProcessor (+ consolidation infra) → TurnState naming → TurnOrchestrator → final validation. Public API of `AgentLoop` is preserved exactly throughout — all callers unchanged.

**Tech Stack:** Python 3.10+, pytest-asyncio (auto mode), ruff, mypy. Run `make lint && make typecheck` after every edit. `make check` before every commit.

**Spec:** `docs/superpowers/specs/2026-03-22-loop-decomposition-design.md`

**Worktree:** Create at `../nanobot-refactor-loop` on branch `refactor/loop-decomposition` before starting.

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `nanobot/agent/bus_progress.py` | `make_bus_progress()` factory — maps typed `ProgressEvent`s to bus `OutboundMessage`s |
| Create | `nanobot/agent/message_processor.py` | `MessageProcessor` — per-request pipeline: session, memory pre-checks, context, save, consolidation |
| Create | `nanobot/agent/turn_orchestrator.py` | `TurnOrchestrator` + `TurnState` + `TurnResult` — PAOR state machine |
| Modify | `nanobot/agent/loop.py` | Shrink to ~300-line runtime: bus poll, MCP lifecycle, coordinator, stop/start |
| Modify | `nanobot/agent/__init__.py` | Export `TurnResult` |
| Modify | `docs/architecture.md` | Add new module boundary rules |
| Modify | `docs/adr/ADR-002-agent-loop-ownership.md` | Update with final line counts |
| Create | `tests/test_bus_progress.py` | Unit tests for `make_bus_progress()` |
| Create | `tests/test_message_processor.py` | Contract tests for `MessageProcessor` |
| Create | `tests/test_turn_orchestrator.py` | Unit tests for `TurnOrchestrator` |

---

## Task 1: Extract `make_bus_progress()` into `bus_progress.py`

**Files:**
- Create: `nanobot/agent/bus_progress.py`
- Create: `tests/test_bus_progress.py`
- Modify: `nanobot/agent/loop.py` (call `make_bus_progress()` instead of `_make_bus_progress`)
- Modify: `nanobot/agent/__init__.py` (export `make_bus_progress`)

This is the lowest-risk extraction — a self-contained closure factory with no loop state dependency. Natural completion of the typed-progress-events work from PR #33.

- [ ] **Step 1: Create the test file**

`tests/test_bus_progress.py`:

```python
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.bus_progress import make_bus_progress
from nanobot.agent.callbacks import (
    DelegateEndEvent,
    DelegateStartEvent,
    StatusEvent,
    TextChunk,
    ToolCallEvent,
    ToolResultEvent,
)


def _make_deps():
    bus = MagicMock()
    bus.publish_outbound = AsyncMock()
    canonical = MagicMock()
    canonical.text_flush = MagicMock(return_value={"type": "text"})
    canonical.tool_call = MagicMock(return_value={"type": "tool_call"})
    canonical.tool_result = MagicMock(return_value={"type": "tool_result"})
    canonical.delegate_start = MagicMock(return_value={"type": "delegate_start"})
    canonical.delegate_end = MagicMock(return_value={"type": "delegate_end"})
    canonical.status = MagicMock(return_value={"type": "status"})
    base_meta = {"_progress": True, "session_id": "s1"}
    return bus, canonical, base_meta


async def _call(event):
    bus, canonical, base_meta = _make_deps()
    cb = make_bus_progress(
        bus=bus, channel="telegram", chat_id="c1",
        base_meta=base_meta, canonical_builder=canonical,
    )
    await cb(event)
    return bus.publish_outbound.call_args[0][0]


async def test_text_chunk_sets_streaming_and_canonical():
    msg = await _call(TextChunk(content="hello", streaming=True))
    assert msg.metadata["_streaming"] is True
    assert msg.metadata["_canonical"] == {"type": "text"}
    assert msg.content == "hello"


async def test_text_chunk_empty_content_no_canonical():
    msg = await _call(TextChunk(content="", streaming=False))
    assert "_canonical" not in msg.metadata
    assert msg.content == ""


async def test_tool_call_sets_tool_hint_and_canonical():
    msg = await _call(ToolCallEvent(tool_call_id="tc1", tool_name="read_file", args={"path": "/x"}))
    assert msg.metadata["_tool_hint"] is True
    assert msg.metadata["_tool_call"]["toolCallId"] == "tc1"
    assert msg.metadata["_canonical"] == {"type": "tool_call"}
    assert msg.content == ""


async def test_tool_result_sets_result_meta():
    msg = await _call(ToolResultEvent(tool_call_id="tc1", result="ok", tool_name="read_file"))
    assert msg.metadata["_tool_result"]["toolCallId"] == "tc1"
    assert "_tool_hint" not in msg.metadata


async def test_delegate_start_sets_canonical():
    msg = await _call(DelegateStartEvent(delegation_id="d1", child_role="research", task_title="Find X"))
    assert msg.metadata["_canonical"] == {"type": "delegate_start"}


async def test_delegate_end_sets_canonical():
    msg = await _call(DelegateEndEvent(delegation_id="d1", success=True))
    assert msg.metadata["_canonical"] == {"type": "delegate_end"}


async def test_status_event_sets_canonical():
    msg = await _call(StatusEvent(status_code="thinking", label="Thinking…"))
    assert msg.metadata["_canonical"] == {"type": "status"}


async def test_base_meta_is_shallow_copied():
    """Each event gets its own meta dict — events must not share state."""
    bus, canonical, base_meta = _make_deps()
    cb = make_bus_progress(
        bus=bus, channel="telegram", chat_id="c1",
        base_meta=base_meta, canonical_builder=canonical,
    )
    await cb(TextChunk(content="a", streaming=False))
    await cb(TextChunk(content="b", streaming=False))
    assert bus.publish_outbound.call_count == 2
    first_meta = bus.publish_outbound.call_args_list[0][0][0].metadata
    second_meta = bus.publish_outbound.call_args_list[1][0][0].metadata
    assert first_meta is not second_meta
```

- [ ] **Step 2: Run tests — confirm FAIL**

```bash
cd ../nanobot-refactor-loop
python -m pytest tests/test_bus_progress.py -v
```

Expected: `ImportError: cannot import name 'make_bus_progress' from 'nanobot.agent.bus_progress'`

- [ ] **Step 3: Create `nanobot/agent/bus_progress.py`**

```python
"""Bus progress callback factory.

Extracted from AgentLoop._make_bus_progress. Provides make_bus_progress(),
a factory that returns a ProgressCallback publishing typed events onto the
message bus as OutboundMessages.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
from nanobot.bus.models import OutboundMessage

if TYPE_CHECKING:
    from nanobot.agent.context import CanonicalEventBuilder
    from nanobot.bus.base import MessageBus

__all__ = ["make_bus_progress"]


def make_bus_progress(
    *,
    bus: MessageBus,
    channel: str,
    chat_id: str,
    base_meta: dict[str, Any],
    canonical_builder: CanonicalEventBuilder,
) -> ProgressCallback:
    """Return a ProgressCallback that maps typed events to OutboundMessages on the bus.

    Each call shallow-copies base_meta, merges per-event fields, and attaches
    the appropriate canonical event before publishing. The returned coroutine
    captures all arguments by value so it remains valid for the full turn.
    """

    async def _progress(event: ProgressEvent) -> None:
        meta = dict(base_meta)
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
        await bus.publish_outbound(
            OutboundMessage(
                channel=channel,
                chat_id=chat_id,
                content=event.content if isinstance(event, TextChunk) else "",
                metadata=meta,
            )
        )

    return _progress
```

- [ ] **Step 4: Run tests — confirm PASS**

```bash
python -m pytest tests/test_bus_progress.py -v
```

Expected: 8 passed

- [ ] **Step 5: Update `loop.py` to use `make_bus_progress`**

In `loop.py`, replace the `_make_bus_progress` method body with a delegation call. Add the import at the top of the file:

```python
from nanobot.agent.bus_progress import make_bus_progress
```

Replace `_make_bus_progress` (lines 1504–1559) with:

```python
def _make_bus_progress(
    self,
    channel: str,
    chat_id: str,
    base_meta: dict,
    canonical_builder: CanonicalEventBuilder,
) -> ProgressCallback:
    """Delegate to the standalone make_bus_progress factory."""
    return make_bus_progress(
        bus=self.bus,
        channel=channel,
        chat_id=chat_id,
        base_meta=base_meta,
        canonical_builder=canonical_builder,
    )
```

- [ ] **Step 6: Add `make_bus_progress` to `nanobot/agent/__init__.py`**

Add to imports and `__all__`:
```python
from nanobot.agent.bus_progress import make_bus_progress
```

- [ ] **Step 7: Lint, typecheck, run tests**

```bash
make lint && make typecheck
python -m pytest tests/test_bus_progress.py tests/test_agent_loop.py -v --tb=short
```

Expected: all pass, no lint/type errors.

- [ ] **Step 8: Commit**

```bash
git add nanobot/agent/bus_progress.py nanobot/agent/loop.py nanobot/agent/__init__.py tests/test_bus_progress.py
git commit -m "refactor: extract make_bus_progress() into bus_progress.py"
```

---

## Task 2: Write failing contract tests for `MessageProcessor`

**Files:**
- Create: `tests/test_message_processor.py`

Write tests that describe `MessageProcessor`'s contract using a mock `TurnOrchestrator`. These tests will FAIL until Task 3 creates the class.

- [ ] **Step 1: Create the test file**

`tests/test_message_processor.py`:

```python
"""Contract tests for MessageProcessor.

Uses a mock TurnOrchestrator so tests are independent of the PAOR loop.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.bus.models import InboundMessage


def _make_processor(**overrides):
    """Build a MessageProcessor with all dependencies mocked."""
    from nanobot.agent.message_processor import MessageProcessor
    from nanobot.agent.turn_orchestrator import TurnResult

    orchestrator = MagicMock()
    orchestrator.run = AsyncMock(
        return_value=TurnResult(content="answer", tools_used=[], messages=[])
    )
    sessions = MagicMock()
    session = MagicMock()
    session.get_history = MagicMock(return_value=[])
    sessions.get_or_create = MagicMock(return_value=session)
    sessions.save = MagicMock()

    context = MagicMock()
    context.build_messages = AsyncMock(return_value=[{"role": "user", "content": "hi"}])
    context.add_assistant_message = MagicMock()
    context.skills = MagicMock()
    context.skills.detect_relevant_skills = MagicMock(return_value=[])

    bus = MagicMock()
    bus.publish_outbound = AsyncMock()

    config = MagicMock()
    config.memory_window = 20
    config.memory = MagicMock()

    consolidator = MagicMock()
    consolidator.consolidate = AsyncMock()

    verifier = MagicMock()
    verifier.should_force_verification = MagicMock(return_value=False)
    verifier.attempt_recovery = AsyncMock(return_value=(None, []))
    verifier.build_no_answer_explanation = MagicMock(return_value="No answer.")

    tools = MagicMock()
    role_manager = MagicMock()
    role_manager.apply = MagicMock(return_value=MagicMock())
    role_manager.reset = MagicMock()

    provider = MagicMock()
    model = "claude-sonnet-4-6"

    defaults = dict(
        orchestrator=orchestrator,
        context=context,
        sessions=sessions,
        tools=tools,
        consolidator=consolidator,
        verifier=verifier,
        bus=bus,
        config=config,
        workspace=Path("/tmp/ws"),
        role_name="default",
        role_manager=role_manager,
        provider=provider,
        model=model,
    )
    defaults.update(overrides)
    return MessageProcessor(**defaults), defaults


async def test_process_direct_returns_orchestrator_content():
    processor, deps = _make_processor()
    result = await processor.process_direct("hello", session_key="cli:s1")
    assert result == "answer"
    deps["orchestrator"].run.assert_called_once()


async def test_process_direct_saves_session():
    processor, deps = _make_processor()
    await processor.process_direct("hello", session_key="cli:s1")
    deps["sessions"].save.assert_called_once()


async def test_process_direct_calls_build_messages():
    processor, deps = _make_processor()
    await processor.process_direct("hello", session_key="cli:s1")
    deps["context"].build_messages.assert_called_once()


async def test_process_inbound_message_returns_outbound():
    from nanobot.bus.models import OutboundMessage
    processor, _ = _make_processor()
    msg = InboundMessage(channel="telegram", chat_id="123", content="hi", sender_id="u1")
    result = await processor.process(msg)
    assert isinstance(result, OutboundMessage)
    assert result.content == "answer"


async def test_new_command_clears_history():
    processor, deps = _make_processor()
    session = deps["sessions"].get_or_create.return_value
    await processor.process_direct("/new", session_key="cli:s1")
    session.clear.assert_called_once()


async def test_empty_orchestrator_result_triggers_recovery():
    from nanobot.agent.turn_orchestrator import TurnResult
    processor, deps = _make_processor()
    deps["orchestrator"].run.return_value = TurnResult(
        content="", tools_used=[], messages=[{"role": "user", "content": "q?"}]
    )
    deps["verifier"].should_force_verification.return_value = True
    deps["verifier"].attempt_recovery.return_value = ("recovered answer", [])
    result = await processor.process_direct("q?", session_key="cli:s1")
    assert result == "recovered answer"
```

- [ ] **Step 2: Run tests — confirm FAIL**

```bash
python -m pytest tests/test_message_processor.py -v
```

Expected: `ImportError: No module named 'nanobot.agent.message_processor'`

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_message_processor.py
git commit -m "test: add failing contract tests for MessageProcessor"
```

---

## Task 3: Create `MessageProcessor` — migrate `_process_message`

**Files:**
- Create: `nanobot/agent/message_processor.py`
- Modify: `nanobot/agent/loop.py` (delegate `_process_message`, `process_direct` to `MessageProcessor`)

This is the largest single extraction. Move ~300 lines of pipeline logic plus consolidation infrastructure from `AgentLoop` into `MessageProcessor`. `AgentLoop` becomes a thin wrapper.

**Key methods to migrate from `loop.py`:**
- `_process_message` (lines 1561–1859)
- `_save_turn` (find by name — saves messages to session)
- `_ensure_scratchpad` (lines 569–587)
- `_run_consolidation_task` (lines 1494–1502)
- `_consolidate_memory` (lines 1883–1892)
- Instance state: `_consolidating`, `_consolidation_tasks`, `_consolidation_sem`
- `process_direct` (lines 1894+) — move logic, leave thin delegate in `AgentLoop`

**Methods that stay in `AgentLoop`** (called from `_process_message` but owned by runtime):
- `_set_tool_context` (lines 553–567)
- `_refresh_contacts` (lines 548–551)
- `_connect_mcp` (lines 485–519)
- `_ensure_coordinator` (lines 1436–1467)

To resolve: `MessageProcessor` needs `_set_tool_context` and `_refresh_contacts`. Pass them as callbacks or inject the relevant tool references directly. The cleanest approach: move `_set_tool_context` into `MessageProcessor` (it only uses `tools` and `config` which are already injected) and pass `_refresh_contacts` as an optional callable.

- [ ] **Step 1: Create `nanobot/agent/message_processor.py`**

Module header and imports:

```python
"""Per-request message processing pipeline.

Extracted from AgentLoop._process_message. Owns the full turn pipeline:
session lookup, slash commands, memory pre-checks, context assembly,
TurnOrchestrator delegation, session save, and consolidation scheduling.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.bus_progress import make_bus_progress
from nanobot.agent.callbacks import ProgressCallback
from nanobot.observability.tracing import bind_trace, correlation_id
from nanobot.bus.models import InboundMessage, OutboundMessage

if TYPE_CHECKING:
    from nanobot.agent.context import CanonicalEventBuilder, ContextBuilder
    from nanobot.agent.coordinator import CoordinatorRegistry
    from nanobot.agent.role_switching import TurnRoleManager
    from nanobot.agent.turn_orchestrator import TurnOrchestrator, TurnResult
    from nanobot.agent.verifier import AnswerVerifier
    from nanobot.bus.base import MessageBus
    from nanobot.config.schema import AgentConfig
    from nanobot.session.manager import SessionManager

__all__ = ["MessageProcessor"]


class MessageProcessor:
    """Per-request pipeline: session → pre-checks → loop → save → consolidate."""

    def __init__(
        self,
        *,
        orchestrator: TurnOrchestrator,
        context: ContextBuilder,
        sessions: SessionManager,
        tools: Any,  # ToolExecutor — avoid circular import
        consolidator: Any,  # ConsolidationOrchestrator
        verifier: AnswerVerifier,
        bus: MessageBus,
        config: AgentConfig,
        workspace: Path,
        role_name: str,
        role_manager: TurnRoleManager,
        provider: Any,  # ChatProvider
        model: str,
        set_tool_context_fn: Any = None,  # callable(channel, chat_id, message_id)
    ) -> None:
        self._orchestrator = orchestrator
        self._context = context
        self._sessions = sessions
        self._tools = tools
        self._consolidator = consolidator
        self._verifier = verifier
        self._bus = bus
        self._config = config
        self._workspace = workspace
        self._role_name = role_name
        self._role_manager = role_manager
        self._provider = provider
        self._model = model
        self._set_tool_context_fn = set_tool_context_fn
        # Consolidation infrastructure (per-instance, not per-request)
        self._consolidating: set[str] = set()
        self._consolidation_tasks: set[asyncio.Task] = set()
        self._consolidation_sem = asyncio.Semaphore(1)
```

Implement `process()`, `process_direct()`, and private helpers by moving the relevant code from `loop.py`. The logic does not change — only the `self.` references update to match `MessageProcessor`'s attributes.

Key patterns to preserve:
- `_process_message` system message fast path (returns early without full pipeline)
- `/new` slash command: `session.clear()`, return confirmation
- Memory pre-check block: conflict detection + live corrections
- Progress callback construction via `make_bus_progress(...)`
- Post-loop verifier recovery: if `content` is empty and `verifier.should_force_verification()`, call `verifier.attempt_recovery()`
- `_save_turn`: persist messages, truncate tool results, filter ephemeral system messages
- `_consolidate_memory`: calls `self._consolidator.consolidate(session, self._provider, self._model, ...)`
- `_run_consolidation_task`: semaphore + lock + fire-and-forget task

- [ ] **Step 2: Update `loop.py` to delegate**

In `AgentLoop`, replace the body of `_process_message` and `process_direct` with delegation calls:

```python
async def _process_message(
    self,
    msg: InboundMessage,
    session_key: str | None = None,
    on_progress: ProgressCallback | None = None,
) -> OutboundMessage | None:
    return await self._processor.process(msg, session_key=session_key, on_progress=on_progress)

async def process_direct(
    self,
    content: str,
    session_key: str = "cli:direct",
    channel: str = "cli",
    chat_id: str = "direct",
    on_progress: ProgressCallback | None = None,
    forced_role: str | None = None,
) -> str:
    return await self._processor.process_direct(
        content, session_key=session_key, channel=channel,
        chat_id=chat_id, on_progress=on_progress, forced_role=forced_role,
    )
```

In `AgentLoop.__init__`, construct `MessageProcessor` and assign to `self._processor`:

```python
from nanobot.agent.message_processor import MessageProcessor

self._processor = MessageProcessor(
    orchestrator=self._orchestrator,  # created in __init__ from _run_agent_loop wrapper
    context=self.context,
    sessions=self.sessions,
    tools=self.tools,
    consolidator=self._consolidator,
    verifier=self._verifier,
    bus=self.bus,
    config=self.config,
    workspace=self.workspace,
    role_name=self.role_name,
    role_manager=self._role_manager,
    provider=self.provider,
    model=self.model,
    set_tool_context_fn=self._set_tool_context,
)
```

Note: At this step, `TurnOrchestrator` does not yet exist. Create a shim in `loop.py`:

```python
class _LegacyOrchestrator:
    """Temporary shim wrapping _run_agent_loop until TurnOrchestrator is extracted."""

    def __init__(self, loop: AgentLoop) -> None:
        self._loop = loop

    async def run(self, state, on_progress=None):
        from nanobot.agent.turn_orchestrator import TurnResult
        content, tools_used, messages = await self._loop._run_agent_loop(
            state.messages, on_progress=on_progress
        )
        return TurnResult(content=content or "", tools_used=tools_used, messages=messages)
```

Create `TurnResult` in a stub `nanobot/agent/turn_orchestrator.py` for now:

```python
"""Turn orchestrator — stub for TurnResult used during MessageProcessor extraction."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

__all__ = ["TurnResult"]

@dataclass(frozen=True, slots=True)
class TurnResult:
    content: str
    tools_used: list[str]
    messages: list[dict[str, Any]]
```

- [ ] **Step 3: Lint and typecheck**

```bash
make lint && make typecheck
```

Fix any errors before proceeding.

- [ ] **Step 4: Run contract tests and full suite**

```bash
python -m pytest tests/test_message_processor.py tests/test_agent_loop.py -v --tb=short
```

Expected: `test_message_processor.py` — 6 passed. `test_agent_loop.py` — all passed.

- [ ] **Step 5: Commit**

```bash
git add nanobot/agent/message_processor.py nanobot/agent/turn_orchestrator.py nanobot/agent/loop.py tests/test_message_processor.py
git commit -m "refactor: extract MessageProcessor from AgentLoop._process_message"
```

---

## Task 4: Introduce `TurnState` — name the loop's shared mutable state

**Files:**
- Modify: `nanobot/agent/turn_orchestrator.py` (add `TurnState` dataclass)
- Modify: `nanobot/agent/loop.py` (thread `TurnState` through `_run_agent_loop` and its helpers)

This is a **pure naming refactor** — no behavior change. Every existing test must pass unchanged. The goal is to make the 8-variable shared state explicit before extracting `TurnOrchestrator` in Task 6.

- [ ] **Step 1: Add `TurnState` to `turn_orchestrator.py`**

Add to the stub file created in Task 3:

```python
from dataclasses import dataclass, field
from nanobot.agent.failure import ToolCallTracker
from nanobot.agent.delegation import DelegationAction  # or appropriate import

@dataclass
class TurnState:
    """Mutable state shared across all iterations of the PAOR loop."""
    messages: list[dict[str, Any]]
    user_text: str
    disabled_tools: set[str] = field(default_factory=set)
    tracker: ToolCallTracker = field(default_factory=ToolCallTracker)
    nudged_for_final: bool = False
    turn_tool_calls: int = 0
    last_tool_call_msg_idx: int = -1
    last_delegation_advice: DelegationAction | None = None
    has_plan: bool = False
    plan_enforced: bool = False
    consecutive_errors: int = 0
    iteration: int = 0
    # Tool definition cache: recomputed only when disabled_tools changes.
    # _evaluate_progress may mutate this when delegation budget is exhausted.
    tools_def_cache: list[dict[str, Any]] = field(default_factory=list)
    tools_def_snapshot: frozenset[str] = field(default_factory=frozenset)
```

- [ ] **Step 2: Thread `TurnState` through `_run_agent_loop` in `loop.py`**

Inside `_run_agent_loop`, replace all individual variable declarations with a `TurnState` construction:

```python
# Before (lines 922–944):
iteration = 0
tools_used: list[str] = []
turn_tool_calls = 0
nudged_for_final = False
# ... etc

# After:
from nanobot.agent.turn_orchestrator import TurnState
state = TurnState(
    messages=messages,
    user_text=user_text,
    tools_def_cache=list(self.tools.get_definitions()),
)
```

Then update all references in `_run_agent_loop`, `_handle_llm_error`, `_process_tool_results`, and `_evaluate_progress` to use `state.field_name` instead of bare local variables.

Key substitutions (non-exhaustive — apply throughout):
- `iteration` → `state.iteration`
- `tools_used` → `state.tools_used`
- `disabled_tools` → `state.disabled_tools`
- `nudged_for_final` → `state.nudged_for_final`
- `tracker` → `state.tracker`
- `consecutive_errors` → `state.consecutive_errors`
- `_tools_def_cache` → `state.tools_def_cache`
- `_tools_def_snapshot` → `state.tools_def_snapshot`
- `_last_tool_call_msg_idx` → `state.last_tool_call_msg_idx`
- `has_plan` → `state.has_plan`
- `plan_enforced` → `state.plan_enforced`

Update `_handle_llm_error` signature:
```python
async def _handle_llm_error(self, state: TurnState, ...) -> str:
```

Update `_process_tool_results` signature:
```python
async def _process_tool_results(self, state: TurnState, ...) -> str:
```

Update `_evaluate_progress` signature:
```python
def _evaluate_progress(self, state: TurnState, ...) -> tuple[bool, str | None]:
```

- [ ] **Step 3: Lint and typecheck**

```bash
make lint && make typecheck
```

- [ ] **Step 4: Run full test suite — all must pass**

```bash
python -m pytest tests/test_agent_loop.py tests/test_message_processor.py -v --tb=short
```

Expected: all pass. Zero behavior change.

- [ ] **Step 5: Update `_LegacyOrchestrator` shim in `loop.py`**

After TurnState threading, the shim's call site must pass the full `TurnState` object instead
of `state.messages`:

```python
# In _LegacyOrchestrator.run():
content, tools_used, messages = await self._loop._run_agent_loop(
    state,  # now accepts TurnState, not bare messages list
    on_progress=on_progress,
)
```

Update `_run_agent_loop` signature accordingly:
```python
async def _run_agent_loop(
    self,
    state: TurnState,
    on_progress: ProgressCallback | None = None,
) -> tuple[str | None, list[str], list[dict]]:
```

- [ ] **Step 6: Commit**

```bash
git add nanobot/agent/turn_orchestrator.py nanobot/agent/loop.py
git commit -m "refactor: introduce TurnState to name PAOR loop shared mutable state"
```

---

## Task 5: Write failing tests for `TurnOrchestrator`

**Files:**
- Create: `tests/test_turn_orchestrator.py`

Write tests that describe `TurnOrchestrator.run()` in isolation using `ScriptedProvider`. These tests will FAIL until Task 6 implements the class.

- [ ] **Step 1: Create the test file**

`tests/test_turn_orchestrator.py`:

```python
"""Unit tests for TurnOrchestrator.

Uses ScriptedProvider for deterministic LLM responses — no AgentLoop needed.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import tempfile

import pytest

from nanobot.agent.turn_orchestrator import TurnOrchestrator, TurnResult, TurnState
from tests.helpers import ScriptedProvider


def _make_orchestrator(responses: list):
    """Build a TurnOrchestrator with ScriptedProvider responses."""
    from nanobot.agent.streaming import StreamingLLMCaller
    from nanobot.agent.turn_orchestrator import TurnOrchestrator

    provider = ScriptedProvider(responses)
    llm_caller = MagicMock()
    llm_caller.call = AsyncMock(side_effect=lambda **kw: provider.chat(**kw))

    tool_executor = MagicMock()
    tool_executor.get_definitions = MagicMock(return_value=[])
    tool_executor.execute_batch = AsyncMock(return_value=[])

    verifier = MagicMock()
    verifier.verify = AsyncMock(side_effect=lambda text, candidate, msgs: (candidate, msgs))

    dispatcher = MagicMock()
    dispatcher.active_messages = []
    dispatcher.delegation_count = 0

    advisor = MagicMock()
    advisor.advise_reflect_phase = MagicMock(return_value=None)

    config = MagicMock()
    config.max_iterations = 10
    config.context_window_tokens = 100_000
    config.delegation = MagicMock()
    config.delegation.max_delegations = 3

    prompts = MagicMock()
    prompts.get = MagicMock(return_value="")
    prompts.render = MagicMock(return_value="")

    context = MagicMock()
    context.add_assistant_message = MagicMock()
    context.add_tool_result = MagicMock()
    context.compress = AsyncMock(side_effect=lambda msgs, **kw: msgs)

    return TurnOrchestrator(
        llm_caller=llm_caller,
        tool_executor=tool_executor,
        verifier=verifier,
        dispatcher=dispatcher,
        delegation_advisor=advisor,
        config=config,
        prompts=prompts,
        context=context,
    )


async def test_run_returns_turn_result():
    from nanobot.providers.base import LLMResponse
    orchestrator = _make_orchestrator([LLMResponse(content="Done.", finish_reason="stop")])
    state = TurnState(messages=[{"role": "user", "content": "hello"}], user_text="hello")
    result = await orchestrator.run(state, on_progress=None)
    assert isinstance(result, TurnResult)
    assert result.content == "Done."
    assert result.tools_used == []


async def test_run_with_tool_call_populates_tools_used():
    from nanobot.providers.base import LLMResponse, ToolCallRequest
    tool_response = LLMResponse(
        content=None,
        finish_reason="tool_calls",
        tool_calls=[ToolCallRequest(id="tc1", name="read_file", arguments={"path": "/x"})],
    )
    final_response = LLMResponse(content="Result.", finish_reason="stop")
    orchestrator = _make_orchestrator([tool_response, final_response])
    orchestrator._tool_executor.execute_batch = AsyncMock(
        return_value=[MagicMock(tool_call_id="tc1", result="content", is_error=False)]
    )
    state = TurnState(messages=[{"role": "user", "content": "read it"}], user_text="read it")
    result = await orchestrator.run(state, on_progress=None)
    assert "read_file" in result.tools_used


async def test_run_error_finish_reason_emits_status_event():
    from nanobot.providers.base import LLMResponse
    from nanobot.agent.callbacks import StatusEvent
    error_resp = LLMResponse(content="quota exceeded", finish_reason="error")
    ok_resp = LLMResponse(content="Done.", finish_reason="stop")
    orchestrator = _make_orchestrator([error_resp, ok_resp])
    events = []
    async def capture(event):
        events.append(event)
    state = TurnState(messages=[{"role": "user", "content": "go"}], user_text="go")
    await orchestrator.run(state, on_progress=capture)
    assert any(isinstance(e, StatusEvent) and e.status_code == "retrying" for e in events)


async def test_run_returns_messages():
    from nanobot.providers.base import LLMResponse
    orchestrator = _make_orchestrator([LLMResponse(content="reply", finish_reason="stop")])
    state = TurnState(messages=[{"role": "user", "content": "hi"}], user_text="hi")
    result = await orchestrator.run(state, on_progress=None)
    assert any(m.get("role") == "assistant" for m in result.messages)
```

- [ ] **Step 2: Run tests — confirm FAIL**

```bash
python -m pytest tests/test_turn_orchestrator.py -v
```

Expected: `ImportError` or `AttributeError` — `TurnOrchestrator` is a stub with no `run()` method.

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_turn_orchestrator.py
git commit -m "test: add failing tests for TurnOrchestrator"
```

---

## Task 6: Create `TurnOrchestrator` — migrate `_run_agent_loop`

**Files:**
- Modify: `nanobot/agent/turn_orchestrator.py` (add full `TurnOrchestrator` class)
- Modify: `nanobot/agent/loop.py` (remove migrated methods, update `_LegacyOrchestrator` shim to use real `TurnOrchestrator`)

Move `_run_agent_loop`, `_handle_llm_error`, `_process_tool_results`, `_evaluate_progress` from `AgentLoop` into `TurnOrchestrator`. Move module-level helpers `_needs_planning` and `_dynamic_preserve_recent` from `loop.py` to `turn_orchestrator.py`.

- [ ] **Step 1: Add `TurnOrchestrator` class to `turn_orchestrator.py`**

```python
class TurnOrchestrator:
    """Owns the Plan-Act-Observe-Reflect loop.

    Accepts a TurnState and runs the agent loop until a final answer is
    produced or max_iterations is reached. All mutable state is held in
    TurnState, making it explicit and testable.
    """

    def __init__(
        self,
        *,
        llm_caller: Any,          # StreamingLLMCaller
        tool_executor: Any,        # ToolExecutor
        verifier: Any,             # AnswerVerifier
        dispatcher: Any,           # DelegationDispatcher
        delegation_advisor: Any,   # DelegationAdvisor
        config: Any,               # AgentConfig
        prompts: Any,              # PromptLoader
        context: Any,              # ContextBuilder
    ) -> None:
        self._llm_caller = llm_caller
        self._tool_executor = tool_executor
        self._verifier = verifier
        self._dispatcher = dispatcher
        self._delegation_advisor = delegation_advisor
        self._config = config
        self._prompts = prompts
        self._context = context

    async def run(
        self,
        state: TurnState,
        on_progress: ProgressCallback | None = None,
    ) -> TurnResult:
        """Execute PAOR loop. Mutates state in-place; returns TurnResult."""
        ...
```

Move `_run_agent_loop`'s loop body into `run()`, replacing `self._xxx` references with `self._xxx` (the collaborators are now `TurnOrchestrator`'s attributes). Replace `state.xxx` references from the TurnState threading done in Task 4.

Move these methods verbatim (updating `self.` references to use `TurnOrchestrator` attributes):
- `_handle_llm_error(self, state, ...) -> str`
- `_process_tool_results(self, state, ...) -> str`
- `_evaluate_progress(self, state, ...) -> tuple[bool, str | None]`

Move these module-level functions from `loop.py` to `turn_orchestrator.py` (no changes needed):
- `_needs_planning(text: str) -> bool`
- `_dynamic_preserve_recent(history_len, max_messages, config) -> int`

- [ ] **Step 2: Update `loop.py` — replace `_LegacyOrchestrator` with real `TurnOrchestrator`**

In `AgentLoop.__init__`, replace the shim:

```python
from nanobot.agent.turn_orchestrator import TurnOrchestrator

self._orchestrator = TurnOrchestrator(
    llm_caller=self._llm_caller,
    tool_executor=self.tools,
    verifier=self._verifier,
    dispatcher=self._dispatcher,
    delegation_advisor=self._delegation_advisor,
    config=self.config,
    prompts=self.prompts,
    context=self.context,
)
```

Remove the now-empty `_run_agent_loop`, `_handle_llm_error`, `_process_tool_results`, and `_evaluate_progress` methods from `AgentLoop`. Remove `_needs_planning` and `_dynamic_preserve_recent` from `loop.py` (they moved to `turn_orchestrator.py`).

- [ ] **Step 3: Update `MessageProcessor` to call `TurnOrchestrator` via `TurnState`**

`MessageProcessor.process()` must now construct a `TurnState` before calling `self._orchestrator.run(state, on_progress)`:

```python
from nanobot.agent.turn_orchestrator import TurnState

state = TurnState(
    messages=messages,
    user_text=user_text,
    tools_def_cache=list(self._tools.get_definitions()),
)
result = await self._orchestrator.run(state, on_progress=on_progress)
```

- [ ] **Step 4: Lint and typecheck**

```bash
make lint && make typecheck
```

Fix all errors before proceeding. Pay attention to:
- `DelegationAction` import in `TurnState` — use `TYPE_CHECKING` guard if needed to avoid circular imports
- Any `self.xxx` references in moved methods that should now be `self._xxx`

- [ ] **Step 5: Run all tests**

```bash
python -m pytest tests/test_turn_orchestrator.py tests/test_message_processor.py tests/test_agent_loop.py -v --tb=short
```

Expected: all pass. Verify `loop.py` line count:

```bash
wc -l nanobot/agent/loop.py
```

Expected: ≤ 500 lines (aiming for ~300 after removing migrated methods).

- [ ] **Step 6: Commit**

```bash
git add nanobot/agent/turn_orchestrator.py nanobot/agent/loop.py nanobot/agent/message_processor.py
git commit -m "refactor: extract TurnOrchestrator from AgentLoop._run_agent_loop"
```

---

## Task 7: Final validation, exports, and documentation

**Files:**
- Modify: `nanobot/agent/__init__.py`
- Modify: `docs/architecture.md`
- Modify: `docs/adr/ADR-002-agent-loop-ownership.md`

- [ ] **Step 1: Export `TurnResult` from `nanobot.agent`**

In `nanobot/agent/__init__.py`, add:

```python
from nanobot.agent.turn_orchestrator import TurnResult
```

Add `"TurnResult"` to `__all__`.

- [ ] **Step 2: Update `docs/architecture.md` module boundaries**

Add to the Module Ownership section:

```
- `agent/turn_orchestrator.py` must NEVER import from `channels/`, `bus/`, or `session/`
- `agent/message_processor.py` must NEVER import from `channels/`
- `agent/bus_progress.py` must NEVER import from `agent/loop`, `agent/turn_orchestrator`, or `agent/message_processor`
- `TurnState` is private to `turn_orchestrator.py` — never exported from `nanobot.agent`
```

- [ ] **Step 3: Update ADR-002**

In `docs/adr/ADR-002-agent-loop-ownership.md`, append a new section or update the existing status/line count:

```markdown
## Phase F — Three-Layer Decomposition (2026-03-22)

Separated `AgentLoop` into three distinct layers:

| Module | Lines | Responsibility |
|--------|-------|----------------|
| `loop.py` | ~300 | `AgentLoop` runtime: bus poll, MCP, coordinator, stop/start |
| `message_processor.py` | ~350 | `MessageProcessor`: per-request pipeline |
| `turn_orchestrator.py` | ~420 | `TurnOrchestrator` + `TurnState` + `TurnResult`: PAOR state machine |
| `bus_progress.py` | ~60 | `make_bus_progress()` factory |

Target from ADR-002 (800–1,000 lines for loop.py) achieved. Public API of `AgentLoop` unchanged.
```

- [ ] **Step 4: Run the full validation suite**

```bash
make check
```

Expected: lint + typecheck + import-check + prompt-check + tests all pass.

- [ ] **Step 5: Run targeted new tests**

```bash
python -m pytest tests/test_bus_progress.py tests/test_message_processor.py tests/test_turn_orchestrator.py -v
```

Expected: all pass.

- [ ] **Step 6: Confirm `loop.py` size**

```bash
wc -l nanobot/agent/loop.py nanobot/agent/message_processor.py nanobot/agent/turn_orchestrator.py nanobot/agent/bus_progress.py
```

Expected: `loop.py` ≤ 500 lines, all four files total ≤ 1,200 lines.

- [ ] **Step 7: Commit**

```bash
git add nanobot/agent/__init__.py docs/architecture.md docs/adr/ADR-002-agent-loop-ownership.md
git commit -m "docs: update exports, architecture boundaries, and ADR-002 for loop decomposition"
```

---

## Reference

- **Spec:** `docs/superpowers/specs/2026-03-22-loop-decomposition-design.md`
- **Key source:** `nanobot/agent/loop.py` — `_make_bus_progress` (lines 1504–1559), `_process_message` (lines 1561–1859), `_run_agent_loop` (lines 913–1222)
- **Pattern reference:** `nanobot/agent/streaming.py` — clean 4-param constructor example
- **Pattern reference:** `nanobot/agent/role_switching.py` — `Protocol`-based decoupling to avoid circular imports
- **Existing test infrastructure:** `tests/helpers.py` — `ScriptedProvider`, `make_agent_loop`, `error_response`
- **Circular import avoidance:** Use `TYPE_CHECKING` guards for type hints; use `Protocol` types for runtime interfaces (see `_LoopLike` in `role_switching.py`)
