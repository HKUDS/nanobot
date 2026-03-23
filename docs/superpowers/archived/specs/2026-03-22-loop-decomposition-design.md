# Design: AgentLoop Decomposition — Three-Layer Architecture

**Date:** 2026-03-22
**Status:** Draft
**Scope:** Separate `AgentLoop` into `AgentRuntime`, `MessageProcessor`, and `TurnOrchestrator`
**Out of scope:** Channel layer changes, provider changes, memory subsystem changes

---

## Problem

`AgentLoop` (`nanobot/agent/loop.py`, 1,948 lines) merges three distinct architectural
layers with different responsibilities, lifecycles, and test surfaces into a single class:

1. **AgentRuntime** — the long-running process supervisor: bus polling, MCP lifecycle,
   coordinator init, crash-barrier, stop/start. Lifecycle: per-process.

2. **MessageProcessor** — the per-request pipeline: session lookup, slash-command handling,
   memory pre-checks, conflict detection, context assembly, canonical event building,
   progress callback wiring, session save, response assembly. Lifecycle: per-message.

3. **TurnOrchestrator** — the Plan-Act-Observe-Reflect state machine: iterates up to
   `max_iterations`, manages an 8-variable shared mutable state, calls LLM, dispatches
   tools, applies reflective nudges, runs verification. Lifecycle: per-iteration.

This merger causes four compounding problems:

- **Untestable seams.** `TurnOrchestrator` logic cannot be exercised without constructing
  the full runtime (bus, MCP, coordinator). `MessageProcessor` logic cannot be tested
  independently of the loop state machine.

- **Constructor explosion.** `AgentLoop.__init__` wires 13 collaborators in one function
  (lines 236–388). No single layer needs more than 4–5 of them.

- **Invisible state machine.** The PAOR loop maintains 8 mutable variables
  (`messages`, `disabled_tools`, `tracker`, `nudged_for_final`, `turn_tool_calls`,
  `_last_tool_call_msg_idx`, `_last_delegation_advice`, `has_plan`/`plan_enforced`) that
  are passed implicitly between `_run_agent_loop`, `_handle_llm_error`,
  `_process_tool_results`, and `_evaluate_progress`. This shared state is undocumented,
  untypeable without a container, and creates 12-parameter method signatures.

- **ADR-002 target missed.** ADR-002 set a target of 800–1,000 lines for `loop.py` after
  the Phase A–E extractions. Current count: 1,948 lines.

---

## Solution: Explicit Three-Layer Decomposition

Separate the three layers into three focused modules. Introduce `TurnState` as an explicit
dataclass to name the inner loop's shared mutable state. Maintain the existing public API
of `AgentLoop` throughout — all callers (CLI, tests, channels) are unchanged.

---

## Section 1: Target File Structure

| Action | File | Lines (est.) | Responsibility |
|--------|------|--------------|----------------|
| Shrink | `nanobot/agent/loop.py` | ~300 | `AgentLoop` as thin runtime: bus poll, MCP lifecycle, coordinator init, stop/start |
| Create | `nanobot/agent/message_processor.py` | ~350 | `MessageProcessor`: per-request pipeline |
| Create | `nanobot/agent/turn_orchestrator.py` | ~420 | `TurnOrchestrator` + `TurnState`: PAOR state machine |
| Create | `nanobot/agent/bus_progress.py` | ~60 | `make_bus_progress()`: progress event → bus publisher |

**No changes to:** `streaming.py`, `delegation.py`, `tool_executor.py`, `role_switching.py`,
`verifier.py`, `tool_setup.py`, `context.py`, `coordinator.py`, `callbacks.py`, or any
channel/provider/config module.

---

## Section 2: `TurnState` Dataclass

**Location:** `nanobot/agent/turn_orchestrator.py`

`TurnState` makes the PAOR loop's shared mutable state explicit and typed. It is the
single argument passed between `TurnOrchestrator`'s internal methods, replacing the
current 8–12 parameter signatures.

```python
@dataclass
class TurnState:
    """Mutable state shared across iterations of the Plan-Act-Observe-Reflect loop."""
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
    # Tool definition cache: filtered list recomputed only when disabled_tools changes.
    # _evaluate_progress may mutate this (removes delegate tools when budget exhausted).
    tools_def_cache: list[dict[str, Any]] = field(default_factory=list)
    tools_def_snapshot: frozenset[str] = field(default_factory=frozenset)
```

`TurnState` is **not** exported from `nanobot/agent/__init__.py` — it is an implementation
detail of `TurnOrchestrator`. It is visible in `turn_orchestrator.py` only.

---

## Section 3: `TurnOrchestrator`

**Location:** `nanobot/agent/turn_orchestrator.py`

Owns the PAOR loop and the `TurnState`. Collaborators are injected at construction.

```python
class TurnOrchestrator:
    def __init__(
        self,
        *,
        llm_caller: StreamingLLMCaller,
        tool_executor: ToolExecutor,
        verifier: AnswerVerifier,
        dispatcher: DelegationDispatcher,
        delegation_advisor: DelegationAdvisor,
        config: AgentConfig,
        prompts: PromptLoader,
        context: ContextBuilder,
    ) -> None: ...

    async def run(
        self,
        state: TurnState,
        on_progress: ProgressCallback | None,
    ) -> TurnResult: ...
```

`TurnResult` is a small dataclass:

```python
@dataclass(frozen=True, slots=True)
class TurnResult:
    content: str
    tools_used: list[str]   # tool names called this turn; empty list = no tools used
    messages: list[dict[str, Any]]
```

Internal methods `_handle_llm_error`, `_process_tool_results`, and `_evaluate_progress`
become private methods of `TurnOrchestrator` that accept and mutate a `TurnState` —
replacing their current 8–12 parameter signatures with `(self, state: TurnState, ...) ->
None`.

`_needs_planning` and `_dynamic_preserve_recent` (currently module-level functions in
`loop.py`) move to `turn_orchestrator.py` as module-level private functions.

---

## Section 4: `MessageProcessor`

**Location:** `nanobot/agent/message_processor.py`

Owns the per-message pipeline. Calls `TurnOrchestrator.run()` and handles everything
before and after it.

```python
class MessageProcessor:
    def __init__(
        self,
        *,
        orchestrator: TurnOrchestrator,
        context: ContextBuilder,
        sessions: SessionManager,
        tools: ToolExecutor,
        consolidator: ConsolidationOrchestrator,
        # verifier is injected here (not just in TurnOrchestrator) because
        # MessageProcessor uses it for attempt_recovery() and
        # build_no_answer_explanation() after the turn loop returns, and for
        # should_force_verification() during pre-turn memory checks.
        verifier: AnswerVerifier,
        bus: MessageBus,
        config: AgentConfig,
        workspace: Path,
        role_name: str,
        role_manager: TurnRoleManager,
        # provider and model are needed by _consolidate_memory, which calls
        # ConsolidationOrchestrator.consolidate(session, provider, model, ...).
        provider: ChatProvider,
        model: str,
    ) -> None: ...

    async def process(
        self,
        message: InboundMessage,
        on_progress: ProgressCallback | None = None,
    ) -> OutboundMessage | None: ...

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: ProgressCallback | None = None,
        forced_role: str | None = None,
    ) -> str: ...
```

`AgentLoop.process_direct` preserves its current full signature and delegates:
```python
async def process_direct(self, content, session_key, channel, chat_id, on_progress, forced_role):
    return await self._processor.process_direct(
        content, session_key, channel, chat_id, on_progress, forced_role
    )
```

`_make_bus_progress` moves into `MessageProcessor` (or is called from it via
`bus_progress.py`). `_save_turn` and the memory pre-check block move here as private
methods.

---

## Section 5: `make_bus_progress()` Factory

**Location:** `nanobot/agent/bus_progress.py`

Extracted from `_make_bus_progress` in `loop.py` (lines 1504–1559). A standalone factory
function — no class needed.

```python
def make_bus_progress(
    *,
    bus: MessageBus,
    channel: str,
    chat_id: str,
    base_meta: dict[str, Any],
    canonical_builder: CanonicalEventBuilder,
) -> ProgressCallback:
    """Return a ProgressCallback that maps typed events to OutboundMessages on the bus."""
    ...
```

This is the natural completion of the typed-progress-events refactor from PR #33 —
the event types were extracted into `callbacks.py`; the bus publisher belongs alongside.

---

## Section 6: `AgentLoop` After Decomposition

`AgentLoop` becomes a thin runtime (~300 lines):

```python
class AgentLoop:
    """Long-running agent process: bus polling, MCP lifecycle, role routing."""

    def __init__(self, config: AgentConfig, bus: MessageBus, ...) -> None:
        # Wire collaborators, create MessageProcessor and TurnOrchestrator
        ...

    async def run(self) -> None:
        """Consume inbound messages, route via coordinator, dispatch to MessageProcessor."""
        ...

    async def process_direct(self, text: str, session_id: str, ...) -> str:
        """Thin delegate to self._processor.process_direct(...)"""
        return await self._processor.process_direct(text, session_id, ...)

    # Setters (set_deliver_callback, set_contacts_provider, set_email_fetch) — unchanged
    # close_mcp, stop — unchanged
```

The public API of `AgentLoop` is **preserved exactly**: `process_direct`, `run`,
`handle_reaction`, `set_deliver_callback`, `set_contacts_provider`, `set_email_fetch`,
`close_mcp`, `stop`, `channels_config`. All callers (CLI, tests, channels) are unaffected.

---

## Section 7: Dependency Chain

```
AgentLoop (runtime, ~300 lines)
    └─ creates: MessageProcessor
                    └─ creates: TurnOrchestrator
                                    └─ uses: StreamingLLMCaller, ToolExecutor,
                                             AnswerVerifier, DelegationDispatcher,
                                             DelegationAdvisor, ContextBuilder,
                                             PromptLoader, AgentConfig
                    └─ uses: ContextBuilder, SessionManager, ToolExecutor,
                             ConsolidationOrchestrator, AnswerVerifier,
                             MessageBus, AgentConfig, TurnRoleManager
    └─ uses: MessageBus, CoordinatorRegistry, MCPManager, AgentConfig
```

Constructor parameter counts after decomposition:
- `AgentLoop.__init__`: retains all current params (bus, config, provider, workspace,
  role_config, channels_config, brave_api_key, exec_config, cron_service, session_manager,
  mcp_servers, routing_config, tool_registry — currently ~11 params) but its body shrinks
  from 150 lines to ~60 lines: construct collaborators and pass to `MessageProcessor`.
- `MessageProcessor.__init__`: ~11 params (all injected from AgentLoop)
- `TurnOrchestrator.__init__`: ~8 params (all injected from MessageProcessor)

---

## Section 8: Migration Steps

### Step 1 — Extract `bus_progress.py` and `make_bus_progress()`
Move `_make_bus_progress` (lines 1504–1559) to a standalone factory function. Low-risk,
self-contained, natural completion of PR #33. Update `loop.py` to call it.

### Step 2 — Extract `MessageProcessor`
Move `_process_message` (~300 lines) and its private helpers (`_save_turn`,
`_pre_turn_memory`, `_ensure_scratchpad`) to `MessageProcessor`. Update `AgentLoop.run()`
and `AgentLoop.process_direct()` to delegate. Add contract test for `MessageProcessor`
before extraction.

The consolidation infrastructure (`_consolidating: set[str]`, `_consolidation_tasks:
set[asyncio.Task]`, `_consolidation_sem: asyncio.Semaphore`, `_run_consolidation_task`,
`_consolidate_memory`) moves with `MessageProcessor` — it is invoked from within
`_process_message` and belongs to the per-message lifecycle, not the runtime. `AgentLoop`
passes `consolidator: ConsolidationOrchestrator` to `MessageProcessor.__init__`;
`MessageProcessor` owns the semaphore and task tracking state.

### Step 3 — Introduce `TurnState`
Add `TurnState` dataclass inside `_run_agent_loop`. Thread it through
`_handle_llm_error`, `_process_tool_results`, and `_evaluate_progress` as a named
container replacing individual parameter passing. No behavior change. No file move.
Commit as a standalone refactor.

### Step 4 — Extract `TurnOrchestrator`
Move `_run_agent_loop` and its internal helpers to `TurnOrchestrator`. The class owns
`TurnState`, the while loop, and all PAOR logic. `MessageProcessor` calls
`orchestrator.run(state, on_progress)`.

### Step 5 — Final validation and `__init__.py` update
Export `TurnResult` from `nanobot.agent`. Verify `loop.py` is ~300 lines.
Run `make check`. Update ADR-002 with final line counts.

---

## Section 9: Test Strategy

Each step ships with tests before the refactor:

| Step | New test file | What it tests |
|------|--------------|---------------|
| 1 | `tests/test_bus_progress.py` | `make_bus_progress()` maps all 6 event types to correct `OutboundMessage` metadata |
| 2 | `tests/test_message_processor.py` | Pipeline: session lookup, slash commands, memory pre-checks, response assembly — using mock `TurnOrchestrator` |
| 3 | (none — naming refactor only) | Existing `test_agent_loop.py` must pass unchanged |
| 4 | `tests/test_turn_orchestrator.py` | PAOR loop: plan phase, tool dispatch, reflect nudges, error handling, verification — using `ScriptedProvider` |
| 5 | `make check` | Full pipeline: lint + typecheck + import-check + tests |

The existing `tests/test_agent_loop.py` must pass unchanged throughout.
No test logic modifications — only import paths may change.

---

## Section 10: Module Boundary Rules (additions to `docs/architecture.md`)

- `turn_orchestrator.py` must **never** import from `channels/`, `bus/`, or `session/`
- `message_processor.py` must **never** import from `channels/`
- `bus_progress.py` must **never** import from `agent/loop`, `agent/turn_orchestrator`,
  or `agent/message_processor`
- `TurnState` is private to `turn_orchestrator.py` — never exported

---

## Out of Scope

- `AgentLoop.run()` extraction (`gateway_loop.py`) — Phase 3, deferred
- Any changes to `delegation.py`, `streaming.py`, `tool_executor.py`, `context.py`
- Memory subsystem changes
- Channel layer changes
- Configuration schema changes
