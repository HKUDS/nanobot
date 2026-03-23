# Phase 1: Extract `agent_factory.py` from `loop.py`

**Date:** 2026-03-23
**Topic:** Extract construction/wiring logic from AgentLoop into a factory function
**Status:** Approved
**Part of:** Comprehensive agent refactoring (Phase 1 of 5)

---

## Goal

Reduce `loop.py`'s coupling by moving all subsystem construction and wiring into a dedicated `agent_factory.py` module. After this change, `AgentLoop.__init__` stores pre-built references and `loop.py` is a pure runtime class with no construction responsibility.

This is Phase 1 of a 5-phase refactoring:
1. **Extract `agent_factory.py`** (this spec) — unblocks all subsequent phases
2. `delegation.py` decomposition — task types, contracts, dispatch
3. `context.py` — separate compression from prompt assembly
4. Break circular dep + unify tool execution paths
5. Complete CapabilityRegistry adoption + memory subsystem cleanup

## Motivation

`loop.py` is currently 1,025 lines with ~28 internal imports — the highest fan-out in the codebase. Its `__init__` method (~220 lines) constructs and wires 15+ subsystems: MemoryStore, ContextBuilder, SessionManager, ToolExecutor, CapabilityRegistry, MissionManager, DelegationDispatcher, DelegationAdvisor, StreamingLLMCaller, AnswerVerifier, TurnOrchestrator, MessageProcessor, TurnRoleManager, ConsolidationOrchestrator, and ToolResultCache.

This makes `loop.py` the hardest file to modify and the bottleneck for every subsequent refactoring phase. Extracting construction into a factory:
- Drops `loop.py` from ~28 imports to ~12
- Reduces `loop.py` from ~1,025 to ~750 lines
- Makes subsystem wiring explicitly testable in isolation
- Unblocks phases 2-5 by reducing the surface area of the file they all touch

## Approach

### New file: `nanobot/agent/agent_factory.py`

Contains:
- `_AgentComponents` — a `@dataclass(slots=True)` holding all pre-built subsystems
- `build_agent()` — factory function that constructs all subsystems and returns `AgentLoop`
- `_build_rollout_overrides()` — extracts the memory rollout config dict construction
- `_build_tools()` — moved from `loop.py`, builds ToolExecutor + CapabilityRegistry + MissionManager + ToolResultCache
- `_wire_memory()` — moved from `loop.py`, builds ConsolidationOrchestrator with archive callback

### `_AgentComponents` dataclass

```python
@dataclass(slots=True)
class _AgentComponents:
    bus: MessageBus
    provider: LLMProvider
    config: AgentConfig
    workspace: Path
    model: str
    temperature: float
    max_iterations: int
    role_config: AgentRoleConfig | None
    role_name: str
    routing_config: RoutingConfig | None
    channels_config: ChannelsConfig | None
    mcp_servers: dict
    brave_api_key: str | None
    exec_config: ExecToolConfig
    cron_service: CronService | None
    memory_rollout_overrides: dict

    # Subsystems
    memory: MemoryStore
    context: ContextBuilder
    sessions: SessionManager
    tools: ToolExecutor
    capabilities: CapabilityRegistry
    result_cache: ToolResultCache
    missions: MissionManager
    consolidator: ConsolidationOrchestrator
    dispatcher: DelegationDispatcher
    delegation_advisor: DelegationAdvisor
    llm_caller: StreamingLLMCaller
    verifier: AnswerVerifier
    orchestrator: TurnOrchestrator
    processor: MessageProcessor
    role_manager: TurnRoleManager

    # Cached tool references for per-turn context updates
    ctx_message_tool: MessageTool | None
    ctx_feedback_tool: FeedbackTool | None
    ctx_mission_tool: MissionStartTool | None
    ctx_cron_tool: CronTool | None
```

### `build_agent()` signature

```python
def build_agent(
    bus: MessageBus,
    provider: LLMProvider,
    config: AgentConfig,
    *,
    brave_api_key: str | None = None,
    exec_config: ExecToolConfig | None = None,
    cron_service: CronService | None = None,
    session_manager: SessionManager | None = None,
    mcp_servers: dict | None = None,
    channels_config: ChannelsConfig | None = None,
    role_config: AgentRoleConfig | None = None,
    routing_config: RoutingConfig | None = None,
    tool_registry: ToolRegistry | None = None,
) -> AgentLoop:
```

Identical parameters to today's `AgentLoop.__init__`. The function:
1. Resolves model/temperature/max_iterations from role_config and config
2. Builds `_build_rollout_overrides(config)` dict
3. Constructs MemoryStore, ContextBuilder, SessionManager
4. Calls `_build_tools(...)` to create ToolExecutor, CapabilityRegistry, MissionManager, ToolResultCache
5. Calls `_wire_memory(...)` to create ConsolidationOrchestrator
6. Constructs DelegationDispatcher, DelegationAdvisor, StreamingLLMCaller, AnswerVerifier
7. Constructs TurnRoleManager (passing the not-yet-created AgentLoop — see wiring note below)
8. Constructs TurnOrchestrator, MessageProcessor
9. Packs everything into `_AgentComponents`
10. Constructs `AgentLoop(components=components)`
11. Wires back-references that require the AgentLoop instance (token source, span module, role manager loop ref)
12. Returns the AgentLoop

### Changes to `AgentLoop.__init__`

The constructor becomes a pure attribute-assignment method:

```python
def __init__(self, *, components: _AgentComponents) -> None:
    self.bus = components.bus
    self.provider = components.provider
    self.config = components.config
    self.workspace = components.workspace
    self.model = components.model
    self.temperature = components.temperature
    self.max_iterations = components.max_iterations
    self.role_config = components.role_config
    self.role_name = components.role_name
    self.channels_config = components.channels_config
    self.memory = components.memory
    self.context = components.context
    self.sessions = components.sessions
    self.tools = components.tools
    self._capabilities = components.capabilities
    self.result_cache = components.result_cache
    self.missions = components.missions
    self._consolidator = components.consolidator
    self._dispatcher = components.dispatcher
    self._delegation_advisor = components.delegation_advisor
    self._llm_caller = components.llm_caller
    self._verifier = components.verifier
    self._orchestrator = components.orchestrator
    self._processor = components.processor
    self._role_manager = components.role_manager
    self._routing_config = components.routing_config
    self._mcp_servers = components.mcp_servers
    self.brave_api_key = components.brave_api_key
    self.exec_config = components.exec_config
    self.cron_service = components.cron_service
    self.memory_rollout_overrides = components.memory_rollout_overrides

    # Cached tool references
    self._ctx_message_tool = components.ctx_message_tool
    self._ctx_feedback_tool = components.ctx_feedback_tool
    self._ctx_mission_tool = components.ctx_mission_tool
    self._ctx_cron_tool = components.ctx_cron_tool

    # Runtime state (not constructed)
    self._running = False
    self._stop_event: asyncio.Event | None = None
    self._mcp_stack: AsyncExitStack | None = None
    self._mcp_connected = False
    self._mcp_connecting = False
    self._coordinator: Coordinator | None = None
    self._last_classification_result: ClassificationResult | None = None
    self._scratchpad: Scratchpad | None = None
    self._delegation_stack: list[str] = []
    self._turn_tokens_prompt = 0
    self._turn_tokens_completion = 0
    self._turn_llm_calls = 0

    # Named seam for future extension (currently empty)
    self._register_handlers()
```

Note: `_injected_tool_registry` is intentionally NOT stored on the AgentLoop instance. It is only used during construction inside `_build_tools()` in the factory. No post-construction code reads this attribute.

### Wiring note: TurnRoleManager circular reference

`TurnRoleManager.__init__` takes a `_LoopLike` Protocol reference (the AgentLoop) and reads `loop.model`, `loop.temperature`, etc. in `apply()`. The factory must use post-construction wiring:

1. Pack `_AgentComponents` with `role_manager=None` (or a sentinel)
2. Construct `AgentLoop(components=components)`
3. Create `TurnRoleManager(loop)` with the real AgentLoop instance
4. Assign `loop._role_manager = role_manager`
5. Also update `loop._processor._role_manager = role_manager` since MessageProcessor holds a reference

This is safe because `TurnRoleManager.apply()` is only called during message processing (inside `run()`), never during construction. The `_LoopLike` Protocol guarantees the interface contract.

### What stays in `loop.py`

All runtime methods remain:
- `run()`, `stop()` — bus consumption loop
- `process_direct()` — CLI/cron entry point
- `handle_reaction()` — reaction handling
- `set_deliver_callback()`, `set_contacts_provider()`, `set_email_fetch()` — channel wiring callbacks
- `_connect_mcp()` — lazy MCP connection
- `_set_tool_context()`, `_ensure_scratchpad()` — per-turn context setup
- `_ensure_coordinator()` — lazy coordinator init
- `_run_agent_loop()` — thin wrapper calling orchestrator
- `_process_message()` — thin delegate to processor
- Backward-compat re-exports at module level

### What moves to `agent_factory.py`

- All of current `__init__` construction logic (~190 lines)
- `_build_tools()` method (~55 lines)
- `_wire_memory()` method (~30 lines)
- `memory_rollout_overrides` dict construction (~30 lines)
- `_register_default_tools()` call (delegation to `tool_setup.py`)

### Impact on callers

**Production callers** (5 call sites, all in `nanobot/cli/`):
- `cli/agent.py:190` — `AgentLoop(...)` → `build_agent(...)`
- `cli/gateway.py:72` and `cli/gateway.py:327` — same change
- `cli/routing.py:316` — same change
- `cli/cron.py:199` — same change
- `cli/_shared.py:189` — same change (if AgentLoop is constructed here)

All use the same parameter signature — the change is mechanical.

**Tests** — tests that construct or patch AgentLoop:
- Tests using `ScriptedProvider` + injected `tool_registry`: use `build_agent()` or construct `_AgentComponents` manually with mocks
- `tests/test_commands_gateway_agent.py` (lines ~144, 173, 228) patches `nanobot.agent.loop.AgentLoop` → must patch `build_agent` at the caller's import path instead
- `tests/test_commands_routing_cron.py` (line ~130) — same pattern
- The backward-compat re-exports in `loop.py` are preserved so existing test imports for `FailureClass`, `ToolCallTracker`, etc. don't break

### `__init__.py` exports

Add to `nanobot/agent/__init__.py`:
- `build_agent` — the factory function (added to `__all__`)

`_AgentComponents` is NOT added to `__all__` — it is an internal implementation detail. Tests that need it import directly from `nanobot.agent.agent_factory`. This follows the project convention that `__all__` lists only public exports.

## Constraints

- No behavioral change — the factory produces an identical AgentLoop to today's constructor
- All existing tests must pass without modification (except import path changes for direct AgentLoop construction)
- `loop.py` backward-compat re-exports are preserved
- The `_LoopLike` Protocol in `role_switching.py` is not changed
- The `_ChatProvider` Protocol in `context.py` is not changed

## Success criteria

- `loop.py` has zero subsystem construction logic in `__init__`
- `loop.py` import count drops from ~28 to ~12
- `make check` passes
- All existing tests pass
- `agent_factory.py` has unit tests for `build_agent()` covering: default construction, injected tool registry, disabled features (memory_enabled=False, delegation_enabled=False)
