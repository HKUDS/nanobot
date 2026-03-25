# Dependency Inversion Fixes — Design Spec

**Date:** 2026-03-24
**Goal:** Eliminate all 18 known dependency inversion violations tracked in `check_imports.py` ALLOWLIST, reducing it to 4 legitimate exceptions.

## Problem

The orchestration layer (`agent/`) imports concrete tool and coordination classes at runtime for:
- `isinstance` checks to call tool-specific methods (11 sites)
- Lazy construction of subsystems outside the composition root (5 sites)
- Type annotations that don't need runtime imports (3 sites)
- A cross-package function import (1 site)

These couple orchestration to domain subsystem internals, violating the dependency inversion principle enforced by `check_imports.py`.

## Strategy Overview

| Strategy | What | Violations Fixed |
|----------|------|-----------------|
| A | Tool lifecycle hooks on `Tool` base class | 11 isinstance + 2 private attr mutations |
| B | Move annotation-only imports to `TYPE_CHECKING` | 3 |
| C | Move `Coordinator` construction to `agent_factory.py`; inject `mcp_connector` callable | 2 |
| D | Inject `scratchpad_factory` + `delegate_tool_factory`; remove MemoryStore fallback | 3 |
| E | Move `feedback_summary` to `context/` | 1 |
| — | Reclassify `DelegationAction` + `has_parallel_structure` as legitimate | 2 remain |

**Final ALLOWLIST:** 4 legitimate entries (2 pre-existing + 2 reclassified).

## Strategy A: Tool Lifecycle Hooks

### Current problem

Orchestration imports 8 concrete tool classes to call tool-specific methods:

```python
# message_processor.py — repeated for MessageTool, CronTool, FeedbackTool, MissionStartTool
from nanobot.tools.builtin.message import MessageTool
tool = self.tools.get("message")
if isinstance(tool, MessageTool):
    tool.set_context(channel, chat_id, message_id)
```

And mutates private attributes:

```python
from nanobot.tools.builtin.scratchpad import ScratchpadWriteTool
if isinstance(write_tool, ScratchpadWriteTool):
    write_tool._scratchpad = self._scratchpad
```

### Design

Add lifecycle hook methods to `Tool` base class in `nanobot/tools/base.py`. All are no-ops by default — tools override only what they need.

```python
class Tool(ABC):
    # ... existing abstract properties ...

    def set_context(
        self,
        channel: str = "",
        chat_id: str = "",
        message_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Receive per-turn routing context. No-op by default.

        Tools that need routing context (channel, chat_id) override this.
        Additional tool-specific kwargs (e.g. session_key, events_file) are
        passed through **kwargs — tools pick what they need and ignore the rest.
        """

    def on_turn_start(self) -> None:
        """Reset per-turn state. No-op by default."""

    def on_session_change(self, **kwargs: Any) -> None:
        """Receive session-scoped dependencies (e.g. scratchpad). No-op by default."""

    @property
    def sent_in_turn(self) -> bool:
        """Whether this tool has sent output this turn. Override if applicable."""
        return False
```

**Signature note:** The `**kwargs` in `set_context` is deliberate. Tools like `FeedbackTool` accept `session_key` and `events_file`; `MessageTool` uses `message_id`. Each tool's override extracts only the kwargs it cares about. The orchestration broadcasts all context — tools self-select. This avoids growing the base signature every time a tool needs a new context field.

**Existing `set_context` methods:** `MessageTool`, `FeedbackTool`, `MissionStartTool`, and `CronTool` already define `set_context` with compatible signatures. They now override the base class no-op instead of being standalone methods. The only change: ensure each accepts `**kwargs` for forward-compatibility (ignore unknown kwargs).

### Tool overrides

| Tool | Hook | Behavior |
|------|------|----------|
| `MessageTool` | `set_context` | Store channel/chat_id/message_id |
| `MessageTool` | `on_turn_start` | Reset `_sent_in_turn = False` (replaces existing `start_turn()`) |
| `MessageTool` | `sent_in_turn` property | Return `self._sent_in_turn` |
| `FeedbackTool` | `set_context` | Store channel/chat_id; extract `session_key`, `events_file` from kwargs |
| `MissionStartTool` | `set_context` | Store channel/chat_id |
| `CronTool` | `set_context` | Store channel/chat_id |
| `ScratchpadReadTool` | `on_session_change` | `self._scratchpad = kwargs["scratchpad"]` |
| `ScratchpadWriteTool` | `on_session_change` | `self._scratchpad = kwargs["scratchpad"]` |

**`MessageTool.start_turn()` rename:** The existing `start_turn()` method is renamed to `on_turn_start()` to match the base hook. Any direct callers (only `message_processor.py` via isinstance, which is being removed) are updated. No external callers exist. Tests that call `start_turn()` are updated to `on_turn_start()`.

### Orchestration changes

**`message_processor.py::_set_tool_context()`** becomes:

```python
def _set_tool_context(self, channel: str, chat_id: str, message_id: str | None) -> None:
    for tool in self._tool_executor.all_tools():
        tool.set_context(
            channel=channel,
            chat_id=chat_id,
            message_id=message_id,
            session_key=f"{channel}:{chat_id}",
        )
```

No imports. No isinstance. Tools that don't override `set_context` get the no-op.

**`message_processor.py::_ensure_scratchpad()`** replaces private attr mutation:

```python
# After constructing scratchpad (see Strategy D for factory injection):
for tool in self._tool_executor.all_tools():
    tool.on_session_change(scratchpad=self._scratchpad)
```

**`message_processor.py` turn-sent check** replaces `isinstance + _sent_in_turn`:

```python
if (msg_tool := self.tools.get("message")) and msg_tool.sent_in_turn:
    return None
```

**`loop.py::set_deliver_callback()`** — one-time callback wiring, not per-turn lifecycle. Use `hasattr`:

```python
def set_deliver_callback(self, callback):
    if tool := self.tools.get("message"):
        if hasattr(tool, "set_send_callback"):
            tool.set_send_callback(callback)
```

**`loop.py::set_email_fetch()`** — same pattern for `CheckEmailTool` callback wiring:

```python
def set_email_fetch(self, fetch_callback, fetch_unread_callback):
    if tool := self.tools.get("check_email"):
        if hasattr(tool, "_fetch"):
            tool._fetch = fetch_callback
            tool._fetch_unread = fetch_unread_callback
```

Note: `CheckEmailTool` already accepts fetch callbacks in its constructor. A cleaner alternative would be adding a `set_fetch_callbacks(fetch, fetch_unread)` public method to `CheckEmailTool` and using `hasattr(tool, "set_fetch_callbacks")`. This avoids mutating private attrs from outside. Implementation choice — either works.

**`loop.py` reaction handling (FeedbackTool)** — replace isinstance with base class calls:

```python
feedback_tool = self.tools.get("feedback")
if feedback_tool is None:
    return
feedback_tool.set_context(
    channel=reaction.channel,
    chat_id=reaction.chat_id,
    session_key=f"{reaction.channel}:{reaction.chat_id}",
)
result = await feedback_tool.execute(rating=rating, ...)
```

### ToolExecutor.all_tools()

Add a forwarding method to `nanobot/tools/executor.py` (since `message_processor.py` holds a `ToolExecutor`, not a `ToolRegistry` directly):

```python
def all_tools(self) -> list[Tool]:
    """Return all registered tool instances."""
    return self._registry.all_tools()
```

And the underlying method on `nanobot/tools/registry.py`:

```python
def all_tools(self) -> list[Tool]:
    """Return all registered tool instances."""
    return list(self._tools.values())
```

### Imports removed

After Strategy A, these imports are deleted:
- `loop.py`: `CheckEmailTool`, `FeedbackTool`, `MessageTool`
- `message_processor.py`: `MessageTool`, `ScratchpadReadTool`, `ScratchpadWriteTool`, `CronTool`, `FeedbackTool`, `MissionStartTool`

## Strategy B: TYPE_CHECKING Moves

Three imports are used only in type annotations (confirmed by tracing all usage sites). With `from __future__ import annotations`, annotations are strings and don't need runtime imports.

| File | Import | Move to `TYPE_CHECKING` |
|------|--------|------------------------|
| `agent/loop.py:46` | `TurnContext` from `coordination.role_switching` | Yes |
| `agent/message_processor.py:35` | `TurnRoleManager` from `coordination.role_switching` | Yes |
| `agent/turn_orchestrator.py:39` | `DelegationDispatcher` from `coordination.delegation` | Yes |

## Strategy C: Factory Construction

### Coordinator

**Current:** `loop.py::_ensure_coordinator()` lazily imports and constructs `Coordinator` at runtime (line 518–543).

**Fix:** Construct in `agent_factory.py::build_agent()` when `routing_config.enabled`:

```python
# In agent_factory.py
coordinator: Coordinator | None = None
if routing_config and routing_config.enabled:
    coordinator = _build_coordinator(
        provider=provider,
        capabilities=_tool_build.capabilities,
        routing_config=routing_config,
    )
```

The `_build_coordinator()` helper handles role registration, agent registry setup, and delegate tool wiring — all currently inside `_ensure_coordinator()`. Returns a fully wired `Coordinator`.

Add `coordinator` to `_Subsystems`. `AgentLoop` receives it and stores it — `_ensure_coordinator()` is deleted.

Wire `dispatcher.coordinator` and `missions.coordinator` in the factory after constructing all three.

### connect_mcp_servers

**Current:** `loop.py::_connect_mcp()` lazily imports `connect_mcp_servers` from `tools.builtin.mcp`.

**Fix:** Inject the function as a callable from `agent_factory.py`:

```python
# In agent_factory.py
from nanobot.tools.builtin.mcp import connect_mcp_servers
# Pass as: mcp_connector=connect_mcp_servers
```

`AgentLoop` receives `mcp_connector: Callable[..., Awaitable[None]] | None`. The `_connect_mcp()` method stays in `loop.py` (it manages async lifecycle, error handling, and post-connection tool propagation to missions/dispatcher) — it just no longer imports the function itself.

## Strategy D: Inject Factories / Remove Fallback

### Scratchpad in message_processor.py

**Current:** `message_processor.py::_ensure_scratchpad()` lazily imports `Scratchpad` from `coordination.scratchpad` and constructs a new instance per session.

**Fix:** Inject a `scratchpad_factory: Callable[[Path], Any]` from `agent_factory.py`:

```python
# In agent_factory.py
from nanobot.coordination.scratchpad import Scratchpad
# Wire: scratchpad_factory=Scratchpad
```

```python
# message_processor.py constructor
def __init__(self, ..., scratchpad_factory: Callable[[Path], Any]):
    self._scratchpad_factory = scratchpad_factory

# In _ensure_scratchpad():
    self._scratchpad = self._scratchpad_factory(session_dir)
```

The `_ensure_scratchpad()` method stays in `message_processor.py` (it manages per-session directory creation and tool wiring) — it just no longer imports `Scratchpad` directly.

### MemoryStore in ContextBuilder

**Current:** `context.py` has a fallback `from nanobot.memory.store import MemoryStore` inside `__init__` if `memory=None`.

**Fix:** Keep `memory` as an optional parameter (`MemoryStore | None = None`) but **remove the fallback construction**. If `memory` is `None`, store `None` — let callers that need memory pass it explicitly. This avoids breaking 16 test callsites that construct `ContextBuilder(workspace)` without memory.

```python
def __init__(self, workspace: Path, *, memory: MemoryStore | None = None, ...):
    self.memory = memory  # no fallback construction
```

The composition root always passes memory. Tests that don't pass memory get `self.memory = None`, which is fine for tests that don't exercise memory paths. Tests that do exercise memory already pass `memory=mock_store`.

**Affected tests (16 callsites):** `test_context_builder.py` (6), `test_capability_availability.py` (4), `test_context_prompt_cache.py` (2), `test_email_validation.py` (3), plus 1 other. Most don't exercise memory paths and need no changes beyond the ContextBuilder accepting `None`.

### DelegateTool in delegation.py

**Current:** `coordination/delegation.py` imports `DelegateTool` from `tools.builtin.delegate` and constructs it for child delegates (line 447).

**Fix:** Inject a factory callable from the composition root:

```python
# delegation.py — DelegationDispatcher constructor
def __init__(self, ..., delegate_tool_factory: Callable[[], Tool] | None = None):
    self._delegate_tool_factory = delegate_tool_factory

# In execute_delegated_agent(), replace:
#   child_delegate = DelegateTool()
# With:
    if self._delegate_tool_factory:
        child_delegate = self._delegate_tool_factory()
        child_delegate.set_dispatch(self.dispatch)
        if _grant(child_delegate.name):
            tools.register(child_delegate)
```

Wire in `agent_factory.py`:

```python
from nanobot.tools.builtin.delegate import DelegateTool
dispatcher = DelegationDispatcher(
    ...,
    delegate_tool_factory=DelegateTool,  # class itself is the factory
)
```

Also remove the `DelegateParallelTool` import from `delegation.py` if it's only used alongside `DelegateTool` (verify during implementation).

## Strategy E: Move feedback_summary

**Current:** `feedback_summary()` and `load_feedback_events()` live in `tools/builtin/feedback.py` but are imported by `context/context.py` for system prompt assembly.

**Fix:** Move both functions to `nanobot/context/feedback_context.py`.

These functions are pure — they read a JSONL file and return a string. They have no dependency on the `FeedbackTool` class or any tool infrastructure. Their purpose (building context for the system prompt) belongs in `context/`.

`FeedbackTool` stays in `tools/builtin/feedback.py`. Verified: `FeedbackTool` does NOT use `load_feedback_events` or `feedback_summary` — it writes events directly via `json.dumps`. No import from `context/` needed.

### Placement gate check

- **Owning package:** `context/` — feedback summarization is prompt assembly
- **File count:** context/ currently has <15 files — within limits
- **Not a catch-all:** Single, focused purpose (feedback context for prompts)
- **`__init__.py` exports:** No need to export from `context/__init__.py` — only imported by `context/context.py`

## Reclassify as Legitimate

Two remaining allowlist entries are genuine runtime dependencies on data objects. These are function-level lazy imports inside `turn_orchestrator.py` methods (lines 257, 736 for `DelegationAction`; line 40 for `has_parallel_structure`).

| Entry | Current Category | New Category | Reason |
|-------|-----------------|--------------|--------|
| `turn_orchestrator.py` → `coordination.task_types` | Known violation | Legitimate: runtime pure function | `has_parallel_structure()` is a pure function called at runtime — no instantiation |
| `turn_orchestrator.py` → `coordination.delegation_advisor` | Known violation | Legitimate: runtime enum | `DelegationAction` enum values compared at runtime — data object, not service |

## Files Modified

| File | Changes |
|------|---------|
| `nanobot/tools/base.py` | Add `set_context`, `on_turn_start`, `on_session_change`, `sent_in_turn` |
| `nanobot/tools/registry.py` | Add `all_tools()` method |
| `nanobot/tools/executor.py` | Add `all_tools()` forwarding method |
| `nanobot/tools/builtin/message.py` | Rename `start_turn` → `on_turn_start`; add `sent_in_turn` property; add `**kwargs` to `set_context` |
| `nanobot/tools/builtin/feedback.py` | Remove `feedback_summary`, `load_feedback_events`; add `**kwargs` to `set_context` |
| `nanobot/tools/builtin/email.py` | Optionally add `set_fetch_callbacks()` public method |
| `nanobot/tools/builtin/cron.py` | Add `**kwargs` to `set_context` for forward-compat |
| `nanobot/tools/builtin/mission.py` | Add `**kwargs` to `set_context` for forward-compat |
| `nanobot/tools/builtin/scratchpad.py` | Override `on_session_change` |
| `nanobot/context/feedback_context.py` | New file — `feedback_summary`, `load_feedback_events` |
| `nanobot/context/context.py` | Import from `feedback_context`; remove MemoryStore fallback construction |
| `nanobot/agent/loop.py` | Remove tool imports; use `hasattr` for callbacks; receive Coordinator + mcp_connector via components |
| `nanobot/agent/message_processor.py` | Remove tool imports; use lifecycle hooks; receive `scratchpad_factory`; move `TurnRoleManager` to TYPE_CHECKING |
| `nanobot/agent/turn_orchestrator.py` | Move `DelegationDispatcher` to TYPE_CHECKING |
| `nanobot/agent/agent_factory.py` | Build Coordinator; inject mcp_connector, scratchpad_factory, delegate_tool_factory |
| `nanobot/agent/agent_components.py` | Add `coordinator`, `mcp_connector` to components |
| `nanobot/coordination/delegation.py` | Accept `delegate_tool_factory` callable; remove DelegateTool/DelegateParallelTool import |
| `scripts/check_imports.py` | Remove resolved allowlist entries; reclassify 2 as legitimate |

## Testing

| Area | Test Action |
|------|-------------|
| Lifecycle hooks | Add tests in `tests/test_tool_base.py`: verify `set_context`, `on_turn_start`, `on_session_change` are no-ops on base; verify `sent_in_turn` returns `False` |
| MessageTool | Update existing tests: `start_turn()` → `on_turn_start()`; test `sent_in_turn` property |
| ScratchpadTools | Test `on_session_change` wires scratchpad correctly |
| ContextBuilder | 16 callsites that pass no `memory=` — verify they still work with `memory=None` (no code changes needed if memory paths aren't exercised) |
| Integration | `make check` — full validation suite |

## Success Criteria

1. `python scripts/check_imports.py` passes with ALLOWLIST containing exactly 4 entries (2 pre-existing legitimate + 2 reclassified legitimate)
2. `make check` passes (lint + typecheck + import-check + tests)
3. No `isinstance` checks against concrete tool classes in `agent/`
4. No runtime imports from `tools.builtin` or `coordination` in `agent/` (except `agent_factory.py`)
5. No runtime imports from `memory` in `context/`

## Implementation Order

B → E → D → A → C (easiest/safest first, riskiest last). Each strategy is independently deployable — partial completion is safe.
