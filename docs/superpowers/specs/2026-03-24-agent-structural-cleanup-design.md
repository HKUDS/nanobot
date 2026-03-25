# Agent Package Structural Cleanup — Design Spec

**Date:** 2026-03-24
**Branch:** refactor/agent-structural-cleanup
**Scope:** `nanobot/agent/` — fix hard-limit violations, improve internal design

## Problem Statement

The `agent/` package has 4 hard-limit violations per CLAUDE.md:

| Violation | Current | Limit |
|-----------|---------|-------|
| `turn_orchestrator.py` LOC | 822 | 500 |
| `message_processor.py` LOC | 667 | 500 |
| `loop.py` LOC | 666 | 500 |
| `__init__.py` exports | 15 | 12 |
| `MessageProcessor.__init__` params | 16 | 7 |

Additionally, `loop.py` contains a second composition root (`_ensure_coordinator()`) that
violates the single-wiring-point rule, and channel-tool wiring methods that couple `agent/`
to concrete `tools/builtin/` types.

## Design Decisions

### Structural over mechanical

Each file gets a design-level improvement, not just code shuffling to satisfy LOC limits.
This costs more effort but produces genuinely better architecture.

### No behavioral changes

All refactoring is purely structural. No new features, no changed behavior, no new
dependencies. Tests should pass with minimal or no updates.

---

## 1. `turn_orchestrator.py` — Phase Decomposition

### Current state

`TurnOrchestrator.run()` is a 290-line method containing all four PAOR phases inline:
plan injection (lines 256-288), act loop with LLM calls and tool execution (lines 293-493),
reflect via `_evaluate_progress()` (lines 724-822), and verification (lines 504-509).

Two large private methods — `_process_tool_results()` (128 lines) and
`_evaluate_progress()` (99 lines) — handle observe and reflect respectively.

### Target design

Decompose into two phase handler classes, each owning one PAOR concern:

**`turn_phases.py`** (new file, ~410 LOC):

```python
@dataclass(slots=True)
class ActPhase:
    """Executes tool calls and processes results."""
    tool_executor: ToolExecutor
    on_progress: ProgressCallback | None

    async def execute_tools(self, state: TurnState, response: LLMResponse) -> ToolBatchResult:
        """Process all tool calls from an LLM response."""
        # Moved from TurnOrchestrator._process_tool_results()

    def _filter_malformed_calls(self, ...) -> list[ToolCall]:
        # Moved from inline in run()


@dataclass(slots=True)
class ReflectPhase:
    """Evaluates progress and injects guidance."""
    dispatcher: DelegationDispatcher
    delegation_advisor: DelegationAdvisor
    prompt_loader: PromptLoader

    def evaluate(self, state: TurnState, response: LLMResponse,
                 any_failed: bool, failed_this_batch: list[...]) -> None:
        """Mutates state with reflect-phase guidance."""
        # Moved from TurnOrchestrator._evaluate_progress()
```

Also contains:
- `_ToolBatchResult` dataclass (co-located with `ActPhase`)
- Module-level helpers: `_needs_planning()`, `_dynamic_preserve_recent()`, `_safe_int()`
- Module constants: `_ARGS_REDACT_TOOLS`, `_DELEGATION_TOOL_NAMES`, `_GREETING_MAX_LEN`,
  `_CONTEXT_RESERVE_RATIO`, `_PLANNING_SIGNALS`

**Plan phase** stays inline in `run()` — it's only ~30 lines and tightly coupled to the
loop entry point. Not worth a separate class.

**`_handle_llm_error()`** stays on `TurnOrchestrator` as a private method — it is called
between the LLM call and the Act phase and is tightly coupled to the loop flow, not to
either phase handler.

**What remains in `turn_orchestrator.py`:**
- `TurnOrchestrator` class with `__init__`, `run()`, `_inject_planning()`,
  `_handle_llm_error()`, and `_finalize()`
- Re-exports of `TurnState` and `TurnResult` (for backward compat)

**`TurnOrchestrator.run()`** becomes a ~120-line coordinator:

```python
async def run(self, state: TurnState, ...) -> TurnResult:
    # Plan phase (~30 lines, inline)
    self._inject_planning(state)

    # Act-Observe-Reflect loop
    while state.iteration < self._max_iterations:
        response = await self._llm_caller.call(...)

        if response.has_tool_calls:
            result = await self._act.execute_tools(state, response)
            self._reflect.evaluate(state, response, result.any_failed, result.failed)
        else:
            return self._finalize(state, response)

    return self._finalize(state, None)
```

### Result

| File | Before | After |
|------|--------|-------|
| `turn_orchestrator.py` | 822 | ~480 |
| `turn_phases.py` | — | ~410 |

---

## 2. `message_processor.py` — Component Grouping + Extraction

### Current state

`MessageProcessor.__init__` takes 16 parameters. `_process_message()` is 246 lines
handling session setup, slash commands, memory pre-checks, tool context, context building,
orchestration, recovery, and session save.

### Target design

**Step A: Group constructor params into component dataclasses.**

Add to `agent_components.py`:

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

Note: The leading underscore means "internal to the `agent/` package" — it is imported
by `agent_factory.py` (same package) but not by external consumers.

`MessageProcessor.__init__` becomes:

```python
def __init__(self, *, services: _ProcessorServices, config: AgentConfig,
             workspace: Path, role_name: str, provider: LLMProvider,
             model: str) -> None:
```

That's **6 params** (under the 7 limit). `role_manager` is set post-construction
via `set_role_manager()` (already the case). `span_module` moves into `_ProcessorServices`.

**Step B: Extract tool context wiring.**

**`turn_context.py`** (new file, ~120 LOC):

```python
class TurnContextManager:
    """Sets per-turn context on routing-aware tools."""

    def __init__(self, tools: ToolExecutor, dispatcher: DelegationDispatcher,
                 missions: MissionManager) -> None:
        self._tools = tools
        self._dispatcher = dispatcher
        self._missions = missions
        self._scratchpad: Scratchpad | None = None

    def set_tool_context(self, channel: str, chat_id: str, session_dir: Path) -> None:
        """Update per-turn context for all context-aware tools."""
        # Moved from MessageProcessor._set_tool_context()

    def ensure_scratchpad(self, session_dir: Path, role_name: str) -> None:
        """Create or retrieve per-session scratchpad."""
        # Moved from MessageProcessor._ensure_scratchpad()
```

`MessageProcessor` receives `TurnContextManager` via `_ProcessorServices` and calls
`self._services.turn_context.set_tool_context(...)` instead of doing it inline.

**Inherited concrete imports:** `TurnContextManager` inherits the `isinstance` checks
and concrete `tools/builtin/` imports from the methods it absorbs (`MessageTool`,
`ScratchpadReadTool`, `ScratchpadWriteTool`, `CronTool`, `FeedbackTool`,
`MissionStartTool`). This is acceptable for this branch — the coupling is isolated
into a single file rather than scattered through `message_processor.py`. Branch C
(dependency inversion) will replace these with protocol-based tool context setting.

**Private attribute mutation:** The current code writes to private attributes across
subsystem boundaries (e.g., `self._dispatcher._trace_path = ...`,
`write_tool._scratchpad = ...`). As part of this extraction, add public setter methods:
- `DelegationDispatcher.set_trace_path(path: Path) -> None`
- `ScratchpadWriteTool.set_scratchpad(scratchpad: Scratchpad) -> None`
- `ScratchpadReadTool.set_scratchpad(scratchpad: Scratchpad) -> None`

`TurnContextManager` calls these setters instead of mutating private attributes.

**Step C: Decompose `_process_message()` into named methods.**

The 246-line method becomes a sequence of calls:

```python
async def _process_message(self, msg, on_progress):
    session = await self._load_or_create_session(msg)       # ~30 lines
    if self._handle_system_message(msg, session): return     # ~20 lines
    await self._run_pre_turn_checks(msg, session)            # ~40 lines
    self._services.turn_context.set_tool_context(...)        # 1 line
    context = await self._build_turn_context(msg, session)   # ~30 lines
    result = await self._run_orchestrator(context, session)  # ~30 lines
    await self._save_and_finalize(msg, session, result)      # ~40 lines
```

Each extracted method is a private method on `MessageProcessor` — no new classes needed
for the decomposition. `_pre_turn_memory()` stays as-is (already well-scoped).

### Result

| File | Before | After |
|------|--------|-------|
| `message_processor.py` | 667 | ~480 |
| `turn_context.py` | — | ~120 |
| `agent_components.py` | 111 | ~140 |

---

## 3. `loop.py` — Two-Phase Coordinator + Method Decomposition

### Current state

`_ensure_coordinator()` (lines 511-542) is a second composition root — it constructs a
`Coordinator` and wires it into the dispatcher, missions, and tool registry. It runs
lazily at the start of `run()`, **after** MCP tools are connected — this timing matters
because `wire_delegate_tools()` captures the available capabilities at call time.

`set_deliver_callback()`, `set_email_fetch()`, `set_contacts_provider()`, and
`handle_reaction()` import concrete tool types from `tools/builtin/` for `isinstance`
checks and setter calls.

### Target design

**Step A: Two-phase coordinator setup.**

The lazy-init timing constraint is real: coordinator construction depends on MCP tools
being available. A full eager move to `build_agent()` would miss MCP tools.

Solution: split coordinator setup into construction (factory) and wiring (lazy):

1. **Construction in `build_agent()`:** Create the `Coordinator` instance and store it
   in `_AgentComponents.coordinator: Coordinator | None`. This eliminates the composition
   root violation — the factory decides *whether* to build a coordinator.

2. **Wiring stays lazy in `AgentLoop`:** A slim `_wire_coordinator()` method (replacing
   `_ensure_coordinator()`) calls `dispatcher.set_coordinator(coordinator)`,
   `dispatcher.wire_delegate_tools()`, and `missions.set_coordinator(coordinator)`.
   This runs after MCP connection, preserving the timing constraint. Critically, it
   does **not construct** the coordinator — it only wires an already-constructed instance.

   **Role registration** (currently done inside `_ensure_coordinator()` via
   `CapabilityRegistry.register_role()` and `merge_register_role()`) happens in
   `build_agent()` as part of construction, since it populates the `CapabilityRegistry`
   that the `Coordinator` constructor receives. The `set_default_role()` call also
   happens in construction. Only the `wire_delegate_tools()` call (which captures
   the current tool capabilities) must happen lazily after MCP tools are available.

3. **Private attribute fix:** The current code sets `registry._default_role` directly.
   Add a public `AgentRegistry.set_default_role(role: str) -> None` method instead.

This preserves the lazy-wiring timing while moving construction to the composition root.

**Step B: Decompose `run()` into named methods.**

`AgentLoop.run()` is 184 lines. Decompose into:
- `_consume_messages()` — bus polling loop
- `_classify_and_route()` — coordinator classification + role switching
- `_handle_timeout()` — timeout enforcement

The channel wiring methods (`set_deliver_callback`, `set_email_fetch`,
`set_contacts_provider`, `handle_reaction`) **stay on `AgentLoop`**. Moving them to a
`ChannelBridge` class would just relocate the concrete tool imports without eliminating
them — violating the "no architectural debt by design" rule. Branch C (dependency
inversion) will introduce a `TurnContextAware` protocol that makes these methods
generic. Until then, keeping them on `AgentLoop` is honest about the current coupling.

### Result

| File | Before | After |
|------|--------|-------|
| `loop.py` | 666 | ~490 |
| `agent_factory.py` | 466 | ~490 |

`agent_factory.py` grows slightly from absorbing coordinator construction but stays
under 500 LOC since no `ChannelBridge` construction is added.

---

## 4. `__init__.py` — Trim Exports

### Current state

15 exports in `__all__`. Hard limit is 12.

### Target

Remove these from `__all__`:
- `ConsolidationOrchestrator` — internal subsystem, only used by `agent_factory.py`
- `MessageProcessor` — internal subsystem, only used by `agent_factory.py`
- `StreamingLLMCaller` — internal subsystem, only used by `agent_factory.py`

Consumers of callback events already can import from `nanobot.agent.callbacks`.

**Result: 12 exports** (at the limit, not over).

---

## File Impact Summary

### New files (2)

| File | LOC | Responsibility |
|------|-----|---------------|
| `turn_phases.py` | ~410 | ActPhase + ReflectPhase + helper functions + constants |
| `turn_context.py` | ~120 | TurnContextManager (per-turn tool context wiring) |

### Modified files (6)

| File | Before LOC | After LOC | Change |
|------|-----------|----------|--------|
| `turn_orchestrator.py` | 822 | ~480 | Phase extraction, `_handle_llm_error` stays |
| `message_processor.py` | 667 | ~480 | Component grouping + method decomposition |
| `loop.py` | 666 | ~490 | Two-phase coordinator + method decomposition |
| `agent_factory.py` | 466 | ~490 | Absorbs coordinator construction |
| `agent_components.py` | 111 | ~150 | Adds `_ProcessorServices` + `coordinator` field |
| `__init__.py` | 39 | ~36 | Remove 3 exports |

### Other modified files (public setter additions)

| File | Change |
|------|--------|
| `coordination/delegation.py` | Add `set_trace_path()` public method |
| `tools/builtin/scratchpad.py` | Add `set_scratchpad()` public methods on Read/Write tools |
| `coordination/registry.py` | Add `set_default_role()` public method on `AgentRegistry` |

### Package metrics after refactoring

| Metric | Before | After | Limit |
|--------|--------|-------|-------|
| Top-level files | 12 | 14 | 15 |
| Max file LOC | 822 | ~490 | 500 |
| `__init__` exports | 15 | 12 | 12 (at limit) |
| `MessageProcessor` params | 16 | 6 | 7 |
| Total package LOC | ~3,866 | ~3,900 | 5,000 |

### Post-refactoring risks

- **File count near limit (14/15).** One more file addition requires extracting a
  subpackage. Candidates: callbacks + turn_types + turn_phases → `agent/turn/`.
- **`agent_factory.py` near 490 LOC.** If future changes push it past 500, extract
  `_build_tools()` into `_tool_factory.py`.

---

## Testing Strategy

- All existing tests should pass without changes (no behavioral changes)
- If tests import moved classes directly, update import paths
- Add unit tests for `ActPhase.execute_tools()` and `ReflectPhase.evaluate()` (these
  are now independently testable, which was the point of the decomposition)
- Run `make check` after each file split to catch regressions immediately

## Success Criteria

1. `make check` passes (lint + typecheck + import-check + prompt-check + tests)
2. All files in `agent/` are ≤ 500 LOC
3. `__init__.py` has ≤ 12 exports
4. `MessageProcessor.__init__` has ≤ 7 params
5. Coordinator construction in `agent_factory.py`, wiring-only in `loop.py`
6. No private attribute mutation across subsystem boundaries
7. No new import boundary violations (`make import-check`)
