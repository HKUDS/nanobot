# Agent Package Structural Cleanup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all hard-limit violations in `nanobot/agent/` — oversized files, excessive exports, bloated constructor — through structural decomposition.

**Architecture:** Phase handlers for the PAOR loop, component dataclass grouping for MessageProcessor, two-phase coordinator setup, and `__init__` export trimming. No behavioral changes.

**Tech Stack:** Python 3.10+, dataclasses, Protocols, pytest, ruff, mypy

**Spec:** `docs/superpowers/specs/2026-03-24-agent-structural-cleanup-design.md`

---

### Task 1: Create branch and add public setters for private attribute access

**Files:**
- Modify: `nanobot/coordination/delegation.py` (add `set_trace_path`)
- Modify: `nanobot/coordination/registry.py` (add `set_default_role`)
- Modify: `nanobot/tools/builtin/scratchpad.py` (add `set_scratchpad` methods)

These setters are prerequisites for later tasks that replace `obj._attr = value` with `obj.set_attr(value)`.

- [ ] **Step 1: Create the feature branch**

```bash
git checkout -b refactor/agent-structural-cleanup
```

- [ ] **Step 2: Add `set_trace_path` to `DelegationDispatcher`**

In `nanobot/coordination/delegation.py`, add after the `__init__` method:

```python
def set_trace_path(self, path: Path) -> None:
    """Set the file path for routing trace persistence."""
    self._trace_path = path
```

- [ ] **Step 3: Add `set_default_role` to `AgentRegistry`**

In `nanobot/coordination/registry.py`, add after `get_default`:

```python
def set_default_role(self, role: str) -> None:
    """Set the default role name for routing fallback."""
    self._default_role = role
```

- [ ] **Step 4: Add `set_scratchpad` to scratchpad tools**

In `nanobot/tools/builtin/scratchpad.py`, both `ScratchpadWriteTool` and `ScratchpadReadTool` already have `_scratchpad` attributes. Add a public setter to each:

```python
# On ScratchpadWriteTool, after __init__:
def set_scratchpad(self, scratchpad: Scratchpad) -> None:
    """Update the scratchpad instance for this session."""
    self._scratchpad = scratchpad

# On ScratchpadReadTool, after __init__:
def set_scratchpad(self, scratchpad: Scratchpad) -> None:
    """Update the scratchpad instance for this session."""
    self._scratchpad = scratchpad
```

- [ ] **Step 5: Run lint + typecheck + tests**

```bash
make lint && make typecheck && python -m pytest tests/ -x --timeout=30
```

- [ ] **Step 6: Commit**

```bash
git add nanobot/coordination/delegation.py nanobot/coordination/registry.py nanobot/tools/builtin/scratchpad.py
git commit -m "refactor: add public setters for cross-subsystem wiring attributes"
```

---

### Task 2: Extract `turn_phases.py` from `turn_orchestrator.py`

**Files:**
- Create: `nanobot/agent/turn_phases.py`
- Modify: `nanobot/agent/turn_orchestrator.py`
- Modify: `tests/test_turn_orchestrator.py` (update imports if needed)

- [ ] **Step 1: Create `nanobot/agent/turn_phases.py`**

Move the following from `turn_orchestrator.py`:
- Module constants: `_ARGS_REDACT_TOOLS`, `_DELEGATION_TOOL_NAMES`, `_GREETING_MAX_LEN`, `_CONTEXT_RESERVE_RATIO`, `_PLANNING_SIGNALS` (lines 49-92)
- Helper functions: `_safe_int` (lines 100-103), `_needs_planning` (lines 106-120), `_dynamic_preserve_recent` (lines 123-155)
- `_ToolBatchResult` dataclass (lines 163-171)
- `ActPhase` class wrapping the body of `_process_tool_results` (lines 594-722)
- `ReflectPhase` class wrapping the body of `_evaluate_progress` (lines 724-823)

The file structure should be:

```python
"""PAOR phase handlers: Act and Reflect.

Extracted from ``turn_orchestrator.py`` to decompose the PAOR loop into
independently testable phase handlers.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.callbacks import (
    ProgressCallback,
    ToolCallEvent,
    ToolResultEvent,
)
from nanobot.agent.failure import FailureClass, ToolCallTracker, _build_failure_prompt
from nanobot.agent.streaming import strip_think
from nanobot.context.context import ContextBuilder
from nanobot.context.prompt_loader import PromptLoader
from nanobot.coordination.delegation import DelegationDispatcher
from nanobot.coordination.task_types import has_parallel_structure
from nanobot.observability.tracing import bind_trace

if TYPE_CHECKING:
    from nanobot.agent.turn_types import TurnState
    from nanobot.coordination.delegation_advisor import DelegationAdvisor
    from nanobot.providers.base import LLMResponse
    from nanobot.tools.executor import ToolExecutor

# --- Module constants (moved from turn_orchestrator.py) ---

_ARGS_REDACT_TOOLS: frozenset[str] = frozenset(
    {"write_file", "edit_file", "exec", "web_fetch", "web_search"}
)
_DELEGATION_TOOL_NAMES: frozenset[str] = frozenset({"delegate", "delegate_parallel"})
_GREETING_MAX_LEN: int = 20
_CONTEXT_RESERVE_RATIO: float = 0.80
_PLANNING_SIGNALS: tuple[str, ...] = (
    " and ", " then ", " after that", " also ", " steps",
    " first ", " second ", " finally ",
    "\n-", "\n*", "\n1.", "\n2.",
    " research ", " analyze ", " compare ", " investigate ",
    " create ", " build ", " implement ", " set up ",
    " configure ", " plan ", " schedule ", " organize ",
)


# --- Module-level helpers ---

def _safe_int(obj: Any, attr: str, default: int) -> int:
    """Safely extract an integer attribute, returning *default* when not numeric."""
    val = getattr(obj, attr, default)
    return int(val) if isinstance(val, (int, float)) else default


def _needs_planning(text: str) -> bool:
    """Heuristic: does this message benefit from explicit planning?"""
    if not text:
        return False
    text_lower = text.strip().lower()
    if len(text_lower) < _GREETING_MAX_LEN:
        return False
    return any(signal in text_lower for signal in _PLANNING_SIGNALS)


def _dynamic_preserve_recent(
    messages: list[dict[str, Any]],
    last_tool_call_idx: int = -1,
    *,
    floor: int = 6,
    cap: int = 30,
) -> int:
    """Calculate how many tail messages to preserve during compression."""
    n = len(messages)
    if n <= floor:
        return floor
    if last_tool_call_idx >= 0:
        needed = n - last_tool_call_idx
        return max(floor, min(needed, cap))
    for offset in range(1, n):
        idx = n - offset
        m = messages[idx]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            needed = n - idx
            return max(floor, min(needed, cap))
    return floor


# --- Data types ---

@dataclass(slots=True)
class ToolBatchResult:
    """Return value of ActPhase.execute_tools."""

    any_failed: bool
    failed_this_batch: list[tuple[str, FailureClass]]
    nudged_for_final: bool
    last_tool_call_msg_idx: int
    tool_calls_this_batch: int


# --- Phase handlers ---

class ActPhase:
    """Execute tool calls and process their results (ACT + OBSERVE)."""

    def __init__(
        self,
        *,
        tool_executor: ToolExecutor,
        context: ContextBuilder,
    ) -> None:
        self._tool_executor = tool_executor
        self._context = context

    async def execute_tools(
        self,
        state: TurnState,
        response: LLMResponse,
        tools_used: list[str],
        on_progress: ProgressCallback | None,
    ) -> ToolBatchResult:
        """Execute tool calls and process their results.

        Mutates state.messages, tools_used, and state.disabled_tools in-place.
        Returns a ToolBatchResult with scalar state changes.
        """
        # (Entire body of TurnOrchestrator._process_tool_results, lines 606-722)
        ...  # placeholder — copy full method body during implementation


class ReflectPhase:
    """Evaluate progress and inject guidance (REFLECT)."""

    def __init__(
        self,
        *,
        dispatcher: DelegationDispatcher,
        delegation_advisor: DelegationAdvisor,
        prompts: PromptLoader,
        role_name: str,
    ) -> None:
        self._dispatcher = dispatcher
        self._delegation_advisor = delegation_advisor
        self._prompts = prompts
        self._role_name = role_name

    def evaluate(
        self,
        state: TurnState,
        response: LLMResponse,
        any_failed: bool,
        failed_this_batch: list[tuple[str, FailureClass]],
    ) -> None:
        """Append REFLECT-phase system messages based on turn state.

        Mutates state in-place.
        """
        # (Entire body of TurnOrchestrator._evaluate_progress, lines 736-823)
        ...  # placeholder — copy full method body during implementation
```

- [ ] **Step 2: Copy the exact method bodies**

Copy `_process_tool_results` body (lines 606-722) into `ActPhase.execute_tools`. Replace `self._context` and `self._tool_executor` references (they match). The method signature adds `tools_used` and `on_progress` as params instead of `self` accessing them.

Copy `_evaluate_progress` body (lines 736-823) into `ReflectPhase.evaluate`. Replace `self._dispatcher`, `self._delegation_advisor`, `self._prompts`, `self._role_name` references (they match the new `__init__` fields).

- [ ] **Step 3: Update `turn_orchestrator.py`**

Remove from `turn_orchestrator.py`:
- All module constants (lines 49-92) — now in `turn_phases.py`
- Helper functions `_safe_int`, `_needs_planning`, `_dynamic_preserve_recent` (lines 100-155)
- `_ToolBatchResult` dataclass (lines 163-171)
- `_process_tool_results` method (lines 594-722)
- `_evaluate_progress` method (lines 724-823)

Add imports from `turn_phases`:
```python
from nanobot.agent.turn_phases import (
    ActPhase,
    ReflectPhase,
    ToolBatchResult,
    _CONTEXT_RESERVE_RATIO,
    _DELEGATION_TOOL_NAMES,
    _dynamic_preserve_recent,
    _needs_planning,
    _safe_int,
)
```

Update `TurnOrchestrator.__init__` to construct phase handlers:
```python
# After existing __init__ assignments:
self._act = ActPhase(tool_executor=tool_executor, context=context)
self._reflect = ReflectPhase(
    dispatcher=dispatcher,
    delegation_advisor=delegation_advisor,
    prompts=prompts,
    role_name=role_name,
)
```

Update `run()` to delegate to phase handlers:
- Replace `await self._process_tool_results(state, response, tools_used, on_progress)` with `await self._act.execute_tools(state, response, tools_used, on_progress)`
- Replace `self._evaluate_progress(state, response, batch.any_failed, batch.failed_this_batch)` with `self._reflect.evaluate(state, response, batch.any_failed, batch.failed_this_batch)`
- Change `_ToolBatchResult` references to `ToolBatchResult`

**What remains in `turn_orchestrator.py`:**
- `TurnOrchestrator` class with `__init__`, `run()`, `_inject_planning()` (plan phase inline), `_handle_llm_error()`, and finalization logic
- Re-exports of `TurnState` and `TurnResult`
- Imports from `turn_phases` for constants, helpers, and phase handlers

**Do NOT remove:** `_handle_llm_error` — it stays on `TurnOrchestrator` (tightly coupled to the loop flow, not to either phase handler).

- [ ] **Step 4: Run lint + typecheck**

```bash
make lint && make typecheck
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_turn_orchestrator.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Verify LOC counts**

```bash
wc -l nanobot/agent/turn_orchestrator.py nanobot/agent/turn_phases.py
```

Expected: both files ≤ 500 LOC.

- [ ] **Step 7: Write unit tests for ActPhase and ReflectPhase**

Create `tests/test_turn_phases.py` with tests for the new phase handlers. These are now independently testable — that was the point of the decomposition.

At minimum test:
- `ActPhase.execute_tools` with a mock `ToolExecutor` that returns successes and failures
- `ReflectPhase.evaluate` with different `DelegationAction` scenarios
- `_needs_planning` with short/long messages
- `_dynamic_preserve_recent` with various message histories

```python
"""Tests for nanobot.agent.turn_phases."""
from __future__ import annotations

import pytest
from nanobot.agent.turn_phases import _needs_planning, _dynamic_preserve_recent


class TestNeedsPlanning:
    def test_empty_string(self) -> None:
        assert _needs_planning("") is False

    def test_short_greeting(self) -> None:
        assert _needs_planning("hi there") is False

    def test_multi_step_task(self) -> None:
        assert _needs_planning("first do X and then do Y") is True

    def test_numbered_list(self) -> None:
        assert _needs_planning("Please:\n1. Read the file\n2. Update it") is True


class TestDynamicPreserveRecent:
    def test_short_history(self) -> None:
        messages = [{"role": "user"}] * 3
        assert _dynamic_preserve_recent(messages) == 6

    def test_with_known_index(self) -> None:
        messages = [{"role": "user"}] * 20
        assert _dynamic_preserve_recent(messages, last_tool_call_idx=15) == 6
```

- [ ] **Step 8: Run new tests**

```bash
python -m pytest tests/test_turn_phases.py -v
```

- [ ] **Step 9: Commit**

```bash
git add nanobot/agent/turn_phases.py nanobot/agent/turn_orchestrator.py tests/test_turn_phases.py
git commit -m "refactor: extract ActPhase and ReflectPhase from TurnOrchestrator"
```

---

### Task 3: Add `_ProcessorServices` and `TurnContextManager`

**Files:**
- Create: `nanobot/agent/turn_context.py`
- Modify: `nanobot/agent/agent_components.py` (add `_ProcessorServices`)

- [ ] **Step 1: Add `_ProcessorServices` to `agent_components.py`**

Add after `_Subsystems`:

```python
@dataclass(slots=True)
class _ProcessorServices:
    """Subsystems consumed by MessageProcessor. Internal to agent/ package."""

    orchestrator: Orchestrator
    dispatcher: DelegationDispatcher
    missions: MissionManager
    context: ContextBuilder
    sessions: SessionManager
    tools: ToolExecutor
    consolidator: ConsolidationOrchestrator
    verifier: AnswerVerifier
    bus: MessageBus
    turn_context: TurnContextManager
    span_module: Any = None
```

Add the necessary TYPE_CHECKING imports:
```python
from nanobot.agent.turn_context import TurnContextManager
from nanobot.agent.turn_types import Orchestrator
from nanobot.bus.queue import MessageBus
```

- [ ] **Step 2: Create `nanobot/agent/turn_context.py`**

```python
"""Per-turn tool context wiring.

Sets routing context (channel, chat_id) on tools that need it, and
manages the per-session scratchpad lifecycle.

Extracted from ``MessageProcessor._set_tool_context`` and
``MessageProcessor._ensure_scratchpad``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from loguru import logger

from nanobot.tools.builtin.message import MessageTool
from nanobot.tools.builtin.scratchpad import ScratchpadReadTool, ScratchpadWriteTool

if TYPE_CHECKING:
    from nanobot.context.context import ContextBuilder
    from nanobot.coordination.delegation import DelegationDispatcher
    from nanobot.coordination.mission import MissionManager
    from nanobot.coordination.scratchpad import Scratchpad
    from nanobot.tools.executor import ToolExecutor


class TurnContextManager:
    """Sets per-turn context on routing-aware tools."""

    def __init__(
        self,
        *,
        tools: ToolExecutor,
        dispatcher: DelegationDispatcher,
        missions: MissionManager,
        context: ContextBuilder,
    ) -> None:
        self._tools = tools
        self._dispatcher = dispatcher
        self._missions = missions
        self._context = context
        self._scratchpad: Scratchpad | None = None
        self._contacts_provider: Callable[[], list[str]] | None = None

    @property
    def scratchpad(self) -> Scratchpad | None:
        """Current session scratchpad, if initialised."""
        return self._scratchpad

    def set_contacts_provider(self, provider: Callable[[], list[str]]) -> None:
        """Set callback that returns known contacts."""
        self._contacts_provider = provider

    def set_tool_context(
        self, channel: str, chat_id: str, message_id: str | None = None
    ) -> None:
        """Update per-turn context for all context-aware tools."""
        from nanobot.tools.builtin.cron import CronTool
        from nanobot.tools.builtin.feedback import FeedbackTool
        from nanobot.tools.builtin.mission import MissionStartTool

        if self._contacts_provider is not None:
            self._context.set_contacts_context(self._contacts_provider())

        msg_t = self._tools.get("message")
        if isinstance(msg_t, MessageTool):
            msg_t.set_context(channel, chat_id, message_id)
        ms_t = self._tools.get("mission_start")
        if isinstance(ms_t, MissionStartTool):
            ms_t.set_context(channel, chat_id)
        cr_t = self._tools.get("cron")
        if isinstance(cr_t, CronTool):
            cr_t.set_context(channel, chat_id)
        fb_t = self._tools.get("feedback")
        if isinstance(fb_t, FeedbackTool):
            fb_t.set_context(channel, chat_id, session_key=f"{channel}:{chat_id}")

    def ensure_scratchpad(self, session_key: str, workspace: Path) -> None:
        """Create or retrieve per-session scratchpad and update tools."""
        from nanobot.coordination.scratchpad import Scratchpad
        from nanobot.utils.helpers import safe_filename

        safe_key = safe_filename(session_key.replace(":", "_"))
        session_dir = workspace / "sessions" / safe_key
        session_dir.mkdir(parents=True, exist_ok=True)
        self._scratchpad = Scratchpad(session_dir)

        # Update subsystem references via public setters
        self._dispatcher.scratchpad = self._scratchpad
        self._dispatcher.set_trace_path(session_dir / "routing_trace.jsonl")
        self._missions.scratchpad = self._scratchpad

        # Update scratchpad tool references via public setters
        write_tool = self._tools.get("write_scratchpad")
        if isinstance(write_tool, ScratchpadWriteTool):
            write_tool.set_scratchpad(self._scratchpad)
        read_tool = self._tools.get("read_scratchpad")
        if isinstance(read_tool, ScratchpadReadTool):
            read_tool.set_scratchpad(self._scratchpad)
```

- [ ] **Step 3: Run lint + typecheck**

```bash
make lint && make typecheck
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/ -x --timeout=30
```

- [ ] **Step 5: Commit**

```bash
git add nanobot/agent/turn_context.py nanobot/agent/agent_components.py
git commit -m "refactor: add TurnContextManager and _ProcessorServices dataclass"
```

---

### Task 4: Refactor `MessageProcessor` to use `_ProcessorServices`

**Files:**
- Modify: `nanobot/agent/message_processor.py`
- Modify: `nanobot/agent/agent_factory.py` (construct `_ProcessorServices` + `TurnContextManager`)
- Modify: `tests/test_message_processor.py` (update construction)

- [ ] **Step 1: Update `MessageProcessor.__init__` signature**

Replace the 16-param constructor with:

```python
def __init__(
    self,
    *,
    services: _ProcessorServices,
    config: AgentConfig,
    workspace: Path,
    role_name: str,
    provider: LLMProvider,
    model: str,
) -> None:
    self.orchestrator = services.orchestrator
    self._dispatcher = services.dispatcher
    self._missions = services.missions
    self.context = services.context
    self.sessions = services.sessions
    self.tools = services.tools
    self._consolidator = services.consolidator
    self.verifier = services.verifier
    self.bus = services.bus
    self._turn_context = services.turn_context
    self._span_module: Any | None = services.span_module
    self.config = config
    self.workspace = workspace
    self.role_name = role_name
    self._role_manager: TurnRoleManager | None = None
    self.provider = provider
    self.model = model

    # Per-turn state (unchanged)
    self._turn_tokens_prompt = 0
    self._turn_tokens_completion = 0
    self._turn_llm_calls = 0
    self.classification_result: ClassificationResult | None = None
    self._last_turn_result: Any | None = None
    self._scratchpad: Scratchpad | None = None
```

- [ ] **Step 2: Replace `_set_tool_context` and `_ensure_scratchpad` calls**

In `_process_message`, replace:
- `self._set_tool_context(channel, chat_id, msg.metadata.get("message_id"))` → `self._turn_context.set_tool_context(channel, chat_id, msg.metadata.get("message_id"))`
- `self._set_tool_context(msg.channel, msg.chat_id, msg.metadata.get("message_id"))` → `self._turn_context.set_tool_context(msg.channel, msg.chat_id, msg.metadata.get("message_id"))`
- `self._ensure_scratchpad(key)` → `self._turn_context.ensure_scratchpad(key, self.workspace)`

Remove the `_set_tool_context` and `_ensure_scratchpad` methods entirely from `MessageProcessor`.

Remove the now-unused imports:
```python
# Remove these:
from nanobot.tools.builtin.message import MessageTool
from nanobot.tools.builtin.scratchpad import ScratchpadReadTool, ScratchpadWriteTool
```

Note: `MessageTool` is still used at line 285 (`isinstance(message_tool, MessageTool)`) and line 414. Keep it imported for those uses. The scratchpad imports can be fully removed.

- [ ] **Step 3: Replace `_contacts_provider` forwarding**

In `MessageProcessor`, the `_contacts_provider` attribute and its usage in `_set_tool_context` are now owned by `TurnContextManager`. Remove the `_contacts_provider` attribute from `MessageProcessor.__init__`.

In `AgentLoop.set_contacts_provider` (loop.py:211-217), simplify to only forward to TurnContextManager:
```python
def set_contacts_provider(
    self,
    provider: Callable[[], list[str]],
) -> None:
    """Set a callback that returns known email contacts (refreshed per-turn)."""
    self._processor._turn_context.set_contacts_provider(provider)
```

Also **remove `_refresh_contacts`** (loop.py:230-233) — contacts refreshing is now handled by `TurnContextManager.set_tool_context()` which calls `self._context.set_contacts_context(self._contacts_provider())` each turn. The `_refresh_contacts` method is dead code after this refactor.

- [ ] **Step 4: Update `agent_factory.py` to construct `_ProcessorServices`**

In `build_agent()`, after constructing all subsystems (step 12), construct `TurnContextManager` and `_ProcessorServices`:

```python
# 12.5 Construct TurnContextManager
from nanobot.agent.turn_context import TurnContextManager
turn_context = TurnContextManager(
    tools=_tool_build.tools,
    dispatcher=dispatcher,
    missions=_tool_build.missions,
    context=context,
)

# 13. Construct _ProcessorServices and MessageProcessor
from nanobot.agent.agent_components import _ProcessorServices
services = _ProcessorServices(
    orchestrator=orchestrator,
    dispatcher=dispatcher,
    missions=_tool_build.missions,
    context=context,
    sessions=sessions,
    tools=_tool_build.tools,
    consolidator=consolidator,
    verifier=verifier,
    bus=bus,
    turn_context=turn_context,
    span_module=sys.modules["nanobot.agent.loop"],
)
processor = MessageProcessor(
    services=services,
    config=config,
    workspace=config.workspace_path,
    role_name=role_config.name if role_config else "",
    provider=provider,
    model=model,
)
```

- [ ] **Step 5: Update test construction**

In `tests/test_message_processor.py`, update any direct `MessageProcessor(...)` construction to use `_ProcessorServices`. If tests use mock constructors, update kwargs accordingly.

- [ ] **Step 6: Run lint + typecheck**

```bash
make lint && make typecheck
```

- [ ] **Step 7: Run all tests**

```bash
python -m pytest tests/test_message_processor.py tests/test_agent_factory.py tests/test_agent_loop.py -v
```

- [ ] **Step 8: Verify LOC**

```bash
wc -l nanobot/agent/message_processor.py
```

Expected: ≤ 500 LOC (target ~480).

- [ ] **Step 9: Commit**

```bash
git add nanobot/agent/message_processor.py nanobot/agent/agent_factory.py nanobot/agent/agent_components.py nanobot/agent/loop.py tests/test_message_processor.py
git commit -m "refactor: replace MessageProcessor 16-param constructor with _ProcessorServices"
```

---

### Task 5: Two-phase coordinator and `loop.py` decomposition

**Files:**
- Modify: `nanobot/agent/loop.py`
- Modify: `nanobot/agent/agent_factory.py`
- Modify: `nanobot/agent/agent_components.py`

- [ ] **Step 1: Add `coordinator` field to `_AgentComponents`**

In `agent_components.py`, add to the TYPE_CHECKING block:
```python
from nanobot.coordination.coordinator import Coordinator
```

Add field to `_AgentComponents`:
```python
coordinator: Coordinator | None = None
```

- [ ] **Step 2: Move coordinator construction to `build_agent()`**

In `agent_factory.py`, after step 8 (DelegationDispatcher construction), add:

```python
# 8.5 Construct Coordinator (if routing is enabled)
coordinator: Coordinator | None = None
if routing_config and routing_config.enabled:
    from nanobot.coordination.coordinator import DEFAULT_ROLES, Coordinator
    from nanobot.coordination.registry import AgentRegistry as _AgentRegistry

    # Register roles on the capability registry
    for role in DEFAULT_ROLES:
        _tool_build.capabilities.register_role(role)
    for role_cfg in routing_config.roles:
        _tool_build.capabilities.merge_register_role(role_cfg)
    assert _tool_build.capabilities.agent_registry is not None
    _tool_build.capabilities.agent_registry.set_default_role(routing_config.default_role)

    coordinator = Coordinator(
        provider=provider,
        registry=_tool_build.capabilities.agent_registry,
        classifier_model=routing_config.classifier_model,
        default_role=routing_config.default_role,
        confidence_threshold=routing_config.confidence_threshold,
    )
    dispatcher.coordinator = coordinator
    _tool_build.missions.coordinator = coordinator
```

Add `coordinator` to `_AgentComponents` construction:
```python
components = _AgentComponents(
    bus=bus,
    provider=provider,
    config=config,
    core=_core,
    infra=_infra,
    subsystems=_subs,
    role_manager=None,
    coordinator=coordinator,
)
```

- [ ] **Step 3: Replace `_ensure_coordinator` in `loop.py`**

In `AgentLoop.__init__`, add:
```python
self._coordinator = components.coordinator
```

Replace the `_ensure_coordinator` method (lines 511-542) with a slim wiring method:

```python
def _wire_coordinator(self) -> None:
    """Wire delegate tools into the coordinator (after MCP tools are available)."""
    if self._coordinator is None:
        return
    if self._coordinator_wired:
        return
    self._coordinator_wired = True
    self._dispatcher.wire_delegate_tools(
        available_roles_fn=self._capabilities.role_names,
    )
    logger.info(
        "Multi-agent routing wired with {} roles",
        len(self._capabilities.agent_registry),
    )
```

Add `self._coordinator_wired = False` to `__init__` runtime state.

Replace both calls to `self._ensure_coordinator()` (in `run()` line 335 and `process_direct()` line 632) with `self._wire_coordinator()`.

- [ ] **Step 4: Decompose `run()` into named methods**

Extract from `AgentLoop.run()`:

```python
async def _classify_and_route(
    self, msg: InboundMessage
) -> TurnContext | None:
    """Classify message via coordinator and apply role overrides."""
    if not self._coordinator or msg.channel == "system":
        return None
    t0_classify = time.monotonic()
    cls_result = await self._coordinator.classify(msg.content)
    self._last_classification_result = cls_result
    self._processor.set_classification_result(cls_result)
    role_name, confidence = cls_result.role_name, cls_result.confidence
    classify_latency_ms = (time.monotonic() - t0_classify) * 1000
    threshold = (
        self._routing_config.confidence_threshold
        if self._routing_config
        else _DEFAULT_CONFIDENCE_THRESHOLD
    )
    if confidence < threshold:
        role_name = (
            self._routing_config.default_role
            if self._routing_config
            else "general"
        )
        logger.info(
            "Low confidence ({:.2f} < {:.2f}), using default role '{}'",
            confidence, threshold, role_name,
        )
    role = (
        self._coordinator.route_direct(role_name)
        or self._coordinator.registry.get_default()
        or AgentRoleConfig(name=role_name, description="General assistant")
    )
    self._dispatcher.record_route_trace(
        "route", role=role.name, confidence=confidence,
        latency_ms=classify_latency_ms, message_excerpt=msg.content,
    )
    return self._role_manager.apply(role)
```

Then `run()` simplifies the trace block to:
```python
async with trace_request(...):
    turn_ctx = await self._classify_and_route(msg)
    # ... timeout + process_message (unchanged)
```

- [ ] **Step 5: Run lint + typecheck**

```bash
make lint && make typecheck
```

- [ ] **Step 6: Run all tests**

```bash
python -m pytest tests/test_agent_loop.py tests/test_agent_factory.py -v
```

- [ ] **Step 7: Verify LOC**

```bash
wc -l nanobot/agent/loop.py nanobot/agent/agent_factory.py
```

Expected: both ≤ 500 LOC.

- [ ] **Step 8: Commit**

```bash
git add nanobot/agent/loop.py nanobot/agent/agent_factory.py nanobot/agent/agent_components.py
git commit -m "refactor: two-phase coordinator setup and loop.py decomposition"
```

---

### Task 6: Trim `__init__.py` exports

**Files:**
- Modify: `nanobot/agent/__init__.py`

- [ ] **Step 1: Check for external consumers**

```bash
# Search for imports of the 3 exports we want to remove
grep -r "from nanobot.agent import ConsolidationOrchestrator\|from nanobot.agent import MessageProcessor\|from nanobot.agent import StreamingLLMCaller" nanobot/ tests/ --include="*.py" | grep -v __init__.py | grep -v agent_factory.py
```

Expected: no external consumers (these are internal subsystems).

- [ ] **Step 2: Remove from `__all__` and imports**

Remove from `__init__.py`:
- `ConsolidationOrchestrator` (and its import line)
- `MessageProcessor` (and its import line)
- `StreamingLLMCaller` (and its import line)

Result:
```python
"""Agent core module."""

from __future__ import annotations

from nanobot.agent.agent_factory import build_agent
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
from nanobot.agent.loop import AgentLoop
from nanobot.agent.turn_types import TurnResult
from nanobot.agent.verifier import AnswerVerifier

__all__ = [
    "AgentLoop",
    "AnswerVerifier",
    "DelegateEndEvent",
    "DelegateStartEvent",
    "ProgressCallback",
    "ProgressEvent",
    "StatusEvent",
    "TextChunk",
    "ToolCallEvent",
    "ToolResultEvent",
    "TurnResult",
    "build_agent",
]
```

That's 12 exports — at the limit.

- [ ] **Step 3: Update any broken imports**

If any test or module was importing `ConsolidationOrchestrator`, `MessageProcessor`, or `StreamingLLMCaller` from `nanobot.agent`, update them to import from the specific module instead.

- [ ] **Step 4: Run lint + typecheck + tests**

```bash
make lint && make typecheck && python -m pytest tests/ -x --timeout=30
```

- [ ] **Step 5: Commit**

```bash
git add nanobot/agent/__init__.py
git commit -m "refactor: trim agent __init__.py exports to 12"
```

---

### Task 7: Update private attribute mutations to use public setters

**Files:**
- Modify: `nanobot/agent/loop.py` (replace `registry._default_role`)
- Modify: `nanobot/agent/turn_context.py` (already uses setters from Task 3)

- [ ] **Step 1: Verify turn_context.py uses public setters**

Confirm `turn_context.py` already calls:
- `self._dispatcher.set_trace_path(...)` instead of `self._dispatcher._trace_path = ...`
- `write_tool.set_scratchpad(...)` instead of `write_tool._scratchpad = ...`
- `read_tool.set_scratchpad(...)` instead of `read_tool._scratchpad = ...`

These were written correctly in Task 3.

- [ ] **Step 2: Fix `loop.py` `_sent_in_turn` access**

In `message_processor.py` line 414:
```python
if isinstance(message_tool, MessageTool) and message_tool._sent_in_turn:
```

Check if `MessageTool` has a public accessor for `_sent_in_turn`. If not, add a property:

In `nanobot/tools/builtin/message.py`, add:
```python
@property
def sent_in_turn(self) -> bool:
    """Whether a message was sent during this turn."""
    return self._sent_in_turn
```

Then update `message_processor.py`:
```python
if isinstance(message_tool, MessageTool) and message_tool.sent_in_turn:
```

- [ ] **Step 3: Run lint + typecheck + tests**

```bash
make lint && make typecheck && python -m pytest tests/ -x --timeout=30
```

- [ ] **Step 4: Commit**

```bash
git add nanobot/agent/message_processor.py nanobot/tools/builtin/message.py
git commit -m "refactor: replace private attribute access with public setters/properties"
```

---

### Task 8: Full validation and final commit

**Files:** All modified files

- [ ] **Step 1: Run full validation**

```bash
make check
```

Expected: all checks pass (lint + typecheck + import-check + prompt-check + tests).

- [ ] **Step 2: Verify all success criteria**

```bash
# File LOC counts
wc -l nanobot/agent/turn_orchestrator.py nanobot/agent/turn_phases.py nanobot/agent/message_processor.py nanobot/agent/turn_context.py nanobot/agent/loop.py nanobot/agent/agent_factory.py

# File count
find nanobot/agent -maxdepth 1 -name '*.py' ! -name '__init__.py' | wc -l

# Export count
grep -c '"' nanobot/agent/__init__.py

# Import boundary check
make import-check
```

Expected:
- All files ≤ 500 LOC
- File count ≤ 15
- 12 exports in `__init__.py`
- No import boundary violations

- [ ] **Step 3: Fix any remaining issues**

If any check fails, fix the issue and re-run `make check`.

- [ ] **Step 4: Final commit (if any fixes were needed)**

```bash
git add -u
git commit -m "refactor: fix remaining issues from agent structural cleanup"
```
