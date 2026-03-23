# Phase 4: Structural Cleanup

**Date:** 2026-03-23
**Topic:** Clean up the deferred import between message_processor and turn_orchestrator; complete CapabilityRegistry adoption
**Status:** Approved
**Part of:** Comprehensive agent refactoring (Phase 4 of 5)
**Depends on:** Phase 1 (agent_factory.py) — construction moves to factory, reducing churn

---

## Goal

Two independent cleanups:
1. Eliminate the deferred import in `message_processor.py` by introducing a Protocol for the orchestrator interface
2. Complete the CapabilityRegistry adoption (ADR-009 Phase C) so tools and skills register through the unified registry

## Revised Scope

The original plan included "unify tool execution paths (TurnOrchestrator vs run_tool_loop)." After analysis, this is **out of scope**:

- `run_tool_loop` is a deliberately stripped-down engine for delegation and mission sub-agent contexts
- It intentionally omits planning, verification, failure tracking, streaming, and delegation advising to prevent recursive cost explosion
- The separation is architecturally justified (documented at delegation.py:935-943)
- Unifying would mean either adding a "lite mode" flag to TurnOrchestrator (complexity) or creating adapter layers (no net benefit)

Both paths share `ToolExecutor.execute_batch()` as the common execution primitive. The divergence above that layer is intentional.

---

## Part A: Eliminate Deferred Import

### Current State

`message_processor.py:476` has a deferred import:
```python
from nanobot.agent.turn_orchestrator import TurnOrchestrator, TurnState
```

This import lives inside `_run_orchestrator()` and is used for:
1. `isinstance(self.orchestrator, TurnOrchestrator)` — type guard (line 478)
2. `TurnState(...)` construction — building the state object (line 481)

The constructor already types the orchestrator as `Any` (line 63), suggesting a Protocol was always intended.

### Actual Dependency Analysis

There is **no true circular dependency**:
- `turn_orchestrator.py` has zero imports from `message_processor.py`
- `message_processor.py` imports from `turn_orchestrator.py` only via the deferred import

The deferred import exists to avoid coupling module initialization order, not to break a cycle. However, it is fragile: any future top-level import of `turn_orchestrator` in `message_processor` would create tight coupling, and the `isinstance` check prevents clean duck-typing in tests.

### Proposed Change

Create a minimal Protocol in a new file `nanobot/agent/orchestrator_protocol.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from nanobot.agent.failure import ToolCallTracker


@dataclass(slots=True)
class TurnState:
    """Mutable state for a single PAOR turn."""
    messages: list[dict[str, Any]]
    user_text: str
    disabled_tools: set[str] = field(default_factory=set)
    tracker: ToolCallTracker = field(default_factory=ToolCallTracker)
    nudged_for_final: bool = False
    turn_tool_calls: int = 0
    last_tool_call_msg_idx: int = -1
    last_delegation_advice: DelegationAction | None = None  # TYPE_CHECKING import from delegation_advisor
    has_plan: bool = False
    plan_enforced: bool = False
    consecutive_errors: int = 0
    iteration: int = 0
    tools_def_cache: list[dict[str, Any]] = field(default_factory=list)
    tools_def_snapshot: frozenset[str] = field(default_factory=frozenset)


class Orchestrator(Protocol):
    """Minimal interface for the turn orchestrator."""
    async def run(
        self,
        state: TurnState,
        on_progress: Any = None,
    ) -> Any: ...
```

**Changes:**
- `TurnState` moves from `turn_orchestrator.py` to `orchestrator_protocol.py` (it's a data class with no orchestrator logic)
- `turn_orchestrator.py` imports `TurnState` from `orchestrator_protocol.py`
- `message_processor.py` imports `TurnState` and `Orchestrator` from `orchestrator_protocol.py` (top-level, no deferred import)
- The `isinstance` check is replaced with the Protocol — `self.orchestrator: Orchestrator`
- `TurnResult` stays in `turn_orchestrator.py` (it's a return type, not needed by the processor)

**Backward compat:**
```python
# In turn_orchestrator.py
from nanobot.agent.orchestrator_protocol import TurnState  # canonical home
from nanobot.agent.orchestrator_protocol import TurnState as TurnState  # re-export for existing importers
```

Tests importing `TurnState` from `turn_orchestrator` continue to work via re-export. Known consumers:
- `turn_orchestrator.py` — imports and re-exports `TurnState` (canonical re-export)
- `loop.py:75` — imports `TurnState` from `turn_orchestrator` (two-hop: loop → turn_orchestrator → orchestrator_protocol)
- `tests/test_turn_orchestrator.py:23` — imports `TurnState` via `nanobot.agent.loop` (three-hop chain)

All three resolve correctly as long as the re-export in `turn_orchestrator.py` is preserved.

### Impact

- `message_processor.py` drops the deferred import entirely
- `message_processor.py` types `orchestrator` as `Orchestrator` Protocol instead of `Any`
- Tests can provide any object satisfying the Protocol without `isinstance` checks
- No behavioral change

---

## Part B: Complete CapabilityRegistry Adoption

### Current State (ADR-009 Gap)

The CapabilityRegistry was intended to be the single source of truth for tools, skills, and roles. In practice:

| Kind | Registered through CapabilityRegistry? | Current path |
|------|---------------------------------------|--------------|
| Tools | No | `ToolExecutor.register()` → `ToolRegistry` directly |
| Skills | No | `SkillsLoader.discover_tools()` → `ToolExecutor.register()` |
| Roles | Yes | `CapabilityRegistry.register_role()` / `merge_register_role()` |

Result: 14 of 21 `CapabilityRegistry` public methods are never called in production. `get_available(kind="tool")` returns empty. `refresh_health()` only checks role entries (no tools).

### Proposed Change

Route all tool and skill registration through `CapabilityRegistry.register_tool()`:

**1. Change `tool_setup.py:register_default_tools()`:**
- Accept `capabilities: CapabilityRegistry` instead of `tools: ToolExecutor`
- Replace all `tools.register(tool)` calls with `capabilities.register_tool(tool)`
- `CapabilityRegistry.register_tool()` already writes to the underlying `ToolRegistry`, so `ToolExecutor` continues to work

**2. Change skill tool registration in `tool_setup.py`:**
- Replace `tools.register(skill_tool)` with `capabilities.register_tool(skill_tool)`

**3. Wire through `_build_tools()` (in `agent_factory.py` after Phase 1):**
- Pass `capabilities` instead of `tools` to `register_default_tools()`

**4. Remove the compensating fallback scan in `get_unavailable_summary()`:**
- Lines 253-261 of `capability.py` scan `ToolRegistry` directly for tools that bypassed `CapabilityRegistry`. Once all tools go through the registry, this fallback is dead code.

### What this enables

- `get_available(kind="tool")` returns the actual available tool list
- `refresh_health()` checks tool availability (binary exists, API key configured, etc.)
- `get_unavailable_summary()` works from a single source of truth
- The CapabilityRegistry becomes the actual registry, not a partial facade

### Scope limit

This phase does NOT:
- Add new capability-based routing (e.g., intent-based tool selection)
- Change how tools are discovered at runtime
- Modify the `ToolExecutor` or `ToolRegistry` APIs
- Change how `ContextBuilder.get_tool_definitions()` works (it reads from `ToolRegistry`, which is still populated)

It only fixes the registration path so data flows through `CapabilityRegistry` as ADR-009 intended.

---

## Constraints

- No behavioral change — same tools registered, same execution paths
- All existing tests pass
- Part A and Part B are independent — can be implemented and merged separately
- `TurnState` backward-compat re-export from `turn_orchestrator.py` preserves existing test imports

## Success criteria

- `message_processor.py` has zero deferred imports
- `message_processor.py` types orchestrator as `Orchestrator` Protocol, not `Any`
- All tools registered via `register_default_tools()` go through `CapabilityRegistry.register_tool()` (note: `mission.py._build_tool_registry()` and `delegation.py`'s per-delegation `ToolRegistry` are intentionally out of scope — they create isolated tool sets for sub-agent contexts and do not participate in the main registry)
- `CapabilityRegistry.get_available(kind="tool")` returns the correct tool list
- `CapabilityRegistry.refresh_health()` covers tools
- Compensating fallback scan removed from `get_unavailable_summary()`
- `make check` passes
