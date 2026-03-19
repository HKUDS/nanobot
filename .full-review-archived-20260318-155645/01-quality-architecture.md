# Phase 1: Code Quality & Architecture Review

## Code Quality Findings

### High Severity

**[CQ-H1] God Class — AgentLoop has ~1,900 lines and 15+ responsibilities**
- Location: Lines 280–2173
- `AgentLoop.__init__` (170 lines) manually wires: `ToolExecutor`, `CapabilityRegistry`, `DelegationDispatcher`, `StreamingLLMCaller`, `AnswerVerifier`, `ConsolidationOrchestrator`, `MissionManager`, `ContextBuilder`, `SessionManager`, `ToolResultCache`, `Scratchpad`, MCP state, plus slash command routing, memory conflict resolution, consolidation scheduling, canonical event building, and session persistence.
- Fix: Continue the extraction trajectory already started. Next high-value targets: `SlashCommandHandler`, `ToolRegistrationBuilder`, and `MessageProcessor` wrapping `_process_message`.

**[CQ-H2] `_run_agent_loop` — ~500 lines, cyclomatic complexity >40**
- Location: Lines 792–1287
- REFLECT phase alone is 7 `elif` branches with sub-conditions (lines 1138–1243). Manages 11 local state variables simultaneously. Deepest nesting is 6+ levels.
- Fix: Extract `_evaluate_progress()` for the REFLECT phase, `_process_tool_results()` for the batch loop (lines 1055–1122), and `_handle_llm_error()` for the error response path (lines 898–943).

**[CQ-H3] Tools removed by failure tracker are permanently lost across turns**
- Location: Lines 1121–1122 (`self.tools.unregister(name)`)
- `unregister()` is unconditional and permanent for the `AgentLoop` instance lifetime. If `web_search` fails 3 times in one turn, it is gone for all subsequent turns until process restart. `_reset_role_after_turn` only restores the tool set when routing is active — in the common no-routing case, nothing restores removed tools.
- Fix: Save/restore the tool set at the start/end of `_run_agent_loop`, or suppress tools from LLM definitions via a per-turn `disabled_tools: set[str]` rather than mutating the live registry.

### Medium Severity

**[CQ-M1] `classify_failure` uses brittle string matching as primary fallback**
- Location: Lines 236–247
- `error_type="auth_failure"` or `error_type="config"` (non-standard values) fall through to substring scanning. `"not found"` triggers `PERMANENT_CONFIG` but would also match a legitimate "file not found" that is actually `LOGICAL_ERROR`. `"forbidden"` matches resource-level 403s that are not permanent auth failures.
- Fix: Audit all `ToolResult.fail(error_type=...)` call sites, build a canonical `error_type → FailureClass` mapping that covers all values in use. Narrow the keyword fallback to a true last resort with a warning log.

**[CQ-M2] `_process_message` is 330 lines with 12 distinct phases**
- Location: Lines 1776–2109
- Inline `_bus_progress` closure (~55 lines, 1953–2008) is untestable in isolation. Slash commands, memory conflicts, consolidation, canonical events, loop execution, recovery, and response formatting are all inline.
- Fix: Extract `_bus_progress` into a `ProgressReporter` class. Move slash command handling to an early-return guard.

**[CQ-M3] `_reset_role_after_turn` uses fragile `getattr` fallback and bypasses ToolExecutor invariants**
- Location: Lines 1638–1645
- `getattr(self, "_saved_model", self.model)` silently returns current (modified) value if apply was never called. `self.tools._tools = self._saved_tools` bypasses any registry invariants. If `_apply_role_for_turn` crashes mid-way, the tool set is not restored.
- Fix: Initialize `_saved_*` fields as `None` in `__init__`, check `is not None`. Add `ToolExecutor.snapshot()`/`restore()` public API.

**[CQ-M4] `_ensure_coordinator` mutates `_capabilities._capabilities` directly**
- Location: Lines 1519–1533
- Bypasses `register_role()` API — future validation or side effects added there will be silently skipped. Violates encapsulation of `CapabilityRegistry`.
- Fix: Use `self._capabilities.register_role(role)`.

**[CQ-M5] Bare `except Exception` without traceback in `_attempt_recovery`**
- Location: Line 1724
- `logger.warning("Recovery LLM call failed with exception")` captures no traceback, making production debugging significantly harder.
- Fix: `logger.warning("Recovery LLM call failed", exc_info=True)`

**[CQ-M6] `__init__` copies 20+ config fields into instance attributes**
- Location: Lines 309–370
- Every new config field requires changes in schema, constructor, and the `memory_rollout_overrides` dict literal. Maintenance trap.
- Fix: Access `self.config.field` directly rather than copying. Define a `MemoryRolloutConfig` sub-model on `AgentConfig`.

### Low Severity

**[CQ-L1] Nine one-liner proxy methods forwarding to `self._dispatcher`** (Lines 1554–1596)

**[CQ-L2] `FailureClass(str, Enum)` allows implicit raw-string comparisons** — defeats enum type safety. Change to `class FailureClass(Enum)`.

**[CQ-L3] `_delegation_names` / `_del_names` defined twice in the same method** (Lines 951, 1140) — extract as `_DELEGATION_TOOL_NAMES = frozenset({"delegate", "delegate_parallel"})` module constant.

**[CQ-L4] 11 inline system message strings embedded in Python code** (Lines 961–1258) — move to the prompt template system (`prompts.get(...)`) for tunability without code changes.

**[CQ-L5] `role_applied = False` assigned twice 14 lines apart** (Lines 1359, 1373) — remove duplicate.

**[CQ-L6] Magic numbers without named constants** — `20` (short message threshold, line 757), `0.80` (context budget ratio, line 820), `5` (delegation nudge threshold, line 1192), `0.6` (confidence threshold, line 1398).

**[CQ-L7] `_needs_planning` heuristic — 22 hardcoded substring signals** (Lines 746–786) — `"and"` triggers for "supply and demand". Not configurable, not testable against real data.

**[CQ-L8] `_build_failure_prompt` comment missing** — Add a comment at line 1162 noting that `tool_names` is read intentionally *after* removals at lines 1121–1122.

---

## Architecture Findings

### High Severity

**[AR-H1] AgentLoop God Object — 15+ composed collaborators wired in `__init__`**
- Same root cause as CQ-H1 but from an architectural perspective: every subsystem change risks touching this file. Merge conflicts are structural at team scale.
- Recommended extraction priority: `TurnContext` value object → `TurnProcessor`/`MessageProcessor` → `FailureClass`+`ToolCallTracker` to `nanobot/agent/failure.py`.

**[AR-H2] Mutable save/restore pattern for role switching is not concurrency-safe**
- Location: Lines 1602–1645 (`_apply_role_for_turn`, `_reset_role_after_turn`)
- Saves state to `self._saved_model`, `self._saved_temperature`, `self._saved_tools` (shallow dict copy). A second concurrent message via `process_direct()` during an active `run()` loop would trample saved state. Tool objects with internal mutable state (`MessageTool._sent_in_turn`, `FeedbackTool` context) are not correctly restored by dict copy.
- Fix: Introduce a `TurnContext` dataclass carrying all per-turn overrides (model, temperature, max_iterations, tool set). Pass it through the call chain; eliminate save/restore entirely.

### Medium Severity

**[AR-M1] `classify_failure` re-implements what `errors.py` already provides structurally**
- `nanobot/errors.py` defines `ToolTimeoutError`, `ToolPermissionError`, `ToolValidationError`, `ToolNotFoundError`, `ProviderAuthError` with structured `error_type` and `recoverable` fields — but these are collapsed to flat strings before reaching `classify_failure`. The keyword fallback is not a last resort; it's a primary path.
- Fix: Ensure all tool execution paths consistently populate `ToolResult.metadata["error_type"]` from the exception type. Map `NanobotError` subclasses directly to `FailureClass` values in a registry.

**[AR-M2] Direct access to internal registry fields breaks encapsulation**
- Line 1609: `self.tools._tools` (AgentLoop → ToolExecutor internals)
- Line 1645: `self.tools._tools = self._saved_tools`
- Line 1519: `self._capabilities._agents = registry`
- Line 1526: `self._capabilities._capabilities[role.name] = ...`
- Fix: `ToolExecutor.snapshot()` / `restore()` public methods. `CapabilityRegistry.register_role()` for line 1526.

**[AR-M3] `_process_message` has 12 sequential phases in one method**
- Same as CQ-M2 from an architectural perspective. The inline `_bus_progress` closure is a hidden dependency of the agent loop execution.

**[AR-M4] Tool unregistration mid-turn has latent concurrency risk**
- Location: Lines 1121–1122
- Currently safe because unregistration happens after `execute_batch` completes. But the pattern is fragile — any future refactoring that interleaves batch execution with failure processing could introduce a race where a tool's definition was already submitted to `asyncio.gather` but is unregistered before the result is returned.
- Fix: Per-turn `disabled_tools: set[str]` checked at definition-generation time (line 880) rather than mutating the live registry.

### Low Severity

**[AR-L1] `FailureClass` / `ToolCallTracker` / `_build_failure_prompt` should live in `nanobot/agent/failure.py`**
- They depend only on `ToolResult` and have no dependency on `AgentLoop`. Placing them in `loop.py` means failure classification enhancements force changes to a 2,173-line file.
- Follow the extraction pattern of `streaming.py`, `verifier.py`, `delegation.py`.

**[AR-L2] `_build_failure_prompt` prompt logic coupled to `FailureClass` internals**
- Switches on specific enum members. Adding a new class requires updating both the enum and this function in two places.
- Fix: `FailureClass.guidance` property that returns recovery text — adding a new member forces the developer to provide guidance at the same location (Open/Closed Principle).

**[AR-L3] `_register_default_tools` is a 110-line procedural block**
- Lines 503–610. Adding a tool requires understanding its filtering logic. Allow/deny filtering is duplicated in `_filter_tools_for_role`.
- Fix: Declarative tool manifest + loop registration. Unify allow/deny filtering via `CapabilityRegistry`.

**[AR-L4] Backward-compatibility proxies accumulating**
- Lines 98–100, 442–444, 469–501: 8+ shims that make `AgentLoop` appear to own delegation state it doesn't.

---

## Critical Issues for Phase 2 Context

1. **[CQ-H3 / AR-M4] Tool removal is permanent across turns** — the most immediately actionable production risk. A transient failure can silently disable a capability for all subsequent turns.
2. **[AR-H2] Mutable save/restore for role switching** — concurrent access risk, and tool object internal state (e.g., `MessageTool._sent_in_turn`) is not correctly restored.
3. **[CQ-M1 / AR-M1] `classify_failure` keyword fallback** — misclassifications cause permanent removal of tools that should only have transient failures, or vice versa.
