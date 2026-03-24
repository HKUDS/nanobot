# Hardening: Clean Ownership Contracts

**Date:** 2026-03-24
**Topic:** Fix cross-boundary violations between AgentLoop, MessageProcessor, and TurnOrchestrator
**Status:** Draft

---

## Problem Statement

The Phase 1-5 refactoring reduced file sizes and extracted modules, but did not fix the underlying coupling between the three core runtime classes. The interaction map shows:

- **17 private attribute accesses** across object boundaries
- **7 two-level tunnels** (reaching through one object into another's internals)
- **1 circular back-pointer** (`_token_source`)
- **5 post-construction attribute pokes** from the factory
- **4 dead methods** in `AgentLoop` (orphaned after MessageProcessor extraction)
- **1 broken data flow** (`_last_classification_result` never reaches orchestrator on bus path)

## Three Interface Contracts

### Contract 1: `TurnOrchestrator.run()` returns everything

**Before:** Callers read `_turn_tokens_prompt`, `_turn_tokens_completion`, `_turn_llm_calls` from the orchestrator after `run()`. `_last_classification_result` is injected onto the orchestrator before `run()`.

**After:**
- Add `tokens_prompt: int`, `tokens_completion: int`, `llm_calls: int` to `TurnResult`
- Add `classification_result: ClassificationResult | None` to `TurnState`
- Remove `_last_classification_result` from `Orchestrator` Protocol — the Protocol becomes zero-attribute, one-method
- `TurnOrchestrator.run()` populates `TurnResult` with token counts, reads `state.classification_result` instead of `self._last_classification_result`

**Eliminates:**
- 6 private attribute reads on orchestrator (3 in `AgentLoop._run_agent_loop`, 3 in `MessageProcessor._sync_token_counters`)
- 2 private attribute writes (`_last_classification_result` poke in `loop.py:320` and `message_processor.py:498`)
- The `_token_source` circular back-pointer (tokens returned in `TurnResult` instead)
- The broken classification forwarding bug (value now travels in `TurnState`, not as a side-channel)

**Changes to `orchestrator_protocol.py`:**
```python
@dataclass(slots=True)
class TurnState:
    messages: list[dict[str, Any]]
    user_text: str
    classification_result: ClassificationResult | None = None  # NEW
    # ... rest unchanged ...

@dataclass(frozen=True, slots=True)
class TurnResult:
    content: str
    tools_used: list[str]
    messages: list[dict[str, Any]]
    tokens_prompt: int = 0       # NEW
    tokens_completion: int = 0   # NEW
    llm_calls: int = 0           # NEW

class Orchestrator(Protocol):
    # ZERO attributes — pure behavioral contract
    async def run(
        self, state: TurnState, on_progress: ProgressCallback | None,
    ) -> TurnResult: ...
```

**Changes to `turn_orchestrator.py`:**
- `run()` reads `state.classification_result` instead of `self._last_classification_result`
- `run()` returns `TurnResult(tokens_prompt=..., tokens_completion=..., llm_calls=...)` with the accumulated counters
- Delete `self._last_classification_result` attribute

**Changes to `message_processor.py`:**
- Add `classification_result: ClassificationResult | None` attribute (default `None`)
- Add `set_classification_result(result)` public method
- `_run_orchestrator()` sets `state.classification_result = self.classification_result` on the TurnState before calling `run()`, then resets `self.classification_result = None`
- `_sync_token_counters()` reads from `TurnResult` return value instead of `getattr(orch, "_turn_tokens_*")`
- Delete `_token_source` attribute — no longer needed

**Changes to `loop.py`:**
- `run()` forwards classification result to processor before calling `_process_message()`: `self._processor.set_classification_result(cls_result)`
- `_run_agent_loop()` sets `state.classification_result = self._last_classification_result` (kept as shim for test callers)
- Token counters read from `TurnResult` return value

### Contract 2: `MessageProcessor` gets `dispatcher` directly

**Before:** MessageProcessor reaches through `self.orchestrator._dispatcher` 7 times, guarded by `hasattr`. Accesses: `on_progress` (set/clear), `scratchpad`, `_trace_path`.

**After:**
- Add `dispatcher: DelegationDispatcher` as a constructor parameter to `MessageProcessor`
- The processor wires `self._dispatcher.scratchpad` and `self._dispatcher._trace_path` directly in `_ensure_scratchpad()`
- `on_progress` wiring moves into `TurnOrchestrator.run()` — the orchestrator already receives `on_progress` as a parameter and can wire `self._dispatcher.on_progress = on_progress` at the start of each turn, clearing it in `finally`

**Eliminates:**
- All 7 `hasattr(self.orchestrator, "_dispatcher")` checks
- All two-level tunnels through the orchestrator
- The Protocol leakage (Protocol no longer needs to expose dispatcher access)

**Changes to `message_processor.py`:**
```python
def __init__(self, *, orchestrator, dispatcher, missions, ...):
    self._dispatcher = dispatcher
    self._missions = missions
```
- `_ensure_scratchpad()` uses `self._dispatcher` directly AND also sets `self._missions.scratchpad = self._scratchpad` (was missing — only AgentLoop's version did this)
- Remove all `hasattr(self.orchestrator, "_dispatcher")` blocks for `on_progress` — that wiring moves to the orchestrator

**Changes to `turn_orchestrator.py`:**
- `run()` wires `self._dispatcher.on_progress = on_progress` at method start, clears in `finally`
- This is natural — the orchestrator owns the dispatcher and the PAOR loop that invokes delegation

**Changes to `agent_factory.py`:**
- Pass `dispatcher` and `missions` to `MessageProcessor()` constructor

### Contract 3: Factory wires through public methods only

**Before:** Factory pokes at `loop._processor._role_manager`, `loop._processor._token_source`, `loop._processor._span_module`, `loop._dispatcher.tools`.

**After:**
- `_token_source` is deleted (Contract 1 eliminates it)
- `_span_module` becomes a constructor parameter on `MessageProcessor` — pass `sys.modules["nanobot.agent.loop"]` at construction time in the factory. (Direct import is NOT safe — `test_observability_plumbing.py:312` patches `nanobot.agent.loop.update_current_span` and expects the processor to call through that binding.)
- Add `MessageProcessor.set_role_manager(rm: TurnRoleManager)` public method — the factory calls this instead of poking at `_role_manager`
- `loop._dispatcher.tools = loop.tools` moves to `_build_tools()` — wire dispatcher's tool reference during construction, not post-construction

**Eliminates:**
- All 5 post-construction private attribute pokes from the factory
- The `sys.modules` hack

## Dead Code Deletion

After the three contracts are in place:

| Method | File | Action |
|--------|------|--------|
| `AgentLoop._save_turn` | `loop.py:648-668` | Delete — zero callers (processor owns this) |
| `AgentLoop._set_tool_context` | `loop.py:245-259` | Delete — zero callers (processor owns this) |
| `AgentLoop._ensure_scratchpad` | `loop.py:261-279` | Delete — zero callers (processor owns this) |
| `AgentLoop._run_agent_loop` | `loop.py:285-330` | **Keep as thin shim** — has 4 test callers in `test_coverage_push_wave6.py` (lines 471, 497, 517, 742). Rewrite the shim to construct `TurnState` with `classification_result` and call `self._orchestrator.run()`, then unpack `TurnResult` into the legacy 3-tuple. Delete only after tests are migrated. |
| `AgentLoop._refresh_contacts` | `loop.py:240-243` | **Keep** — has 4 test callers in `test_pass2_smoke.py` (lines 159, 173, 177, 452). These test contact context propagation. Keep as a thin delegate to `self.context.set_contacts_context(self._contacts_provider())`. |
| Cached tool refs `_ctx_*` | `loop.py:160-164` | Delete — only used by dead `_set_tool_context` |

Also delete from `_AgentComponents`: `ctx_message_tool`, `ctx_feedback_tool`, `ctx_mission_tool`, `ctx_cron_tool` — these are only used by the dead `_set_tool_context` on AgentLoop. MessageProcessor does its own tool lookups.

## `_AgentComponents` Grouping

Replace the 36-field flat dataclass with nested groups:

```python
@dataclass(slots=True)
class _CoreConfig:
    model: str
    temperature: float
    max_iterations: int
    workspace: Path
    role_config: AgentRoleConfig | None
    role_name: str

@dataclass(slots=True)
class _InfraConfig:
    routing_config: RoutingConfig | None
    channels_config: ChannelsConfig | None
    mcp_servers: dict
    brave_api_key: str | None
    exec_config: ExecToolConfig
    cron_service: CronService | None
    memory_rollout_overrides: dict

@dataclass(slots=True)
class _Subsystems:
    memory: MemoryStore
    context: ContextBuilder
    sessions: SessionManager
    tools: ToolExecutor
    tool_registry: ToolRegistry
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

@dataclass(slots=True)
class _AgentComponents:
    bus: MessageBus
    provider: LLMProvider
    config: AgentConfig
    core: _CoreConfig
    infra: _InfraConfig
    subsystems: _Subsystems
    role_manager: TurnRoleManager | None = None
```

`AgentLoop.__init__` unpacks from these groups:
```python
self.model = components.core.model
self.tools = components.subsystems.tools
self._mcp_servers = components.infra.mcp_servers
```

## `_build_tools` Return Type

Replace the 8-tuple with a named dataclass:

```python
@dataclass(slots=True)
class _ToolBuildResult:
    tools: ToolExecutor
    tool_registry: ToolRegistry
    capabilities: CapabilityRegistry
    result_cache: ToolResultCache
    missions: MissionManager
```

## Bug Fixes Included

1. `loop.py:603` — `self.memory_store` → `self.memory` (graph driver cleanup)
2. Classification result forwarding — now travels through `TurnState`, always reaches orchestrator
3. `_ensure_scratchpad` in `MessageProcessor` — will also update `missions.scratchpad` (was missing, only `AgentLoop`'s version did it)

## Additional Cleanup

1. Remove `| Any` from `MessageProcessor.__init__` parameter types — use concrete types
2. Rename `orchestrator_protocol.py` → `turn_types.py` (it holds TurnState, TurnResult, and the Protocol)
3. Update `__init__.py` to import `TurnResult` from `turn_types` directly (not through re-export chain)
4. Remove `AgentLoop._process_message` shim — callers should use `_processor._process_message` if they need the internal path, or better yet use `process_direct()`

## Success Criteria

- Zero private attribute access across object boundaries (no `obj._attr` from outside the class)
- Zero `hasattr` guards for duck-typed internal access
- Zero circular references between objects
- Zero post-construction private attribute pokes from the factory (only public method calls)
- `Orchestrator` Protocol has zero attributes — pure method contract
- All dead methods deleted from `AgentLoop`
- `_AgentComponents` uses nested groups
- `_build_tools` returns a named struct
- `make check` passes
- All tests pass
