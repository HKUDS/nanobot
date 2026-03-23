# Phase 2: Decompose `delegation.py`

**Date:** 2026-03-23
**Topic:** Extract task taxonomy and contract construction from delegation.py
**Status:** Approved
**Part of:** Comprehensive agent refactoring (Phase 2 of 5)
**Depends on:** Phase 1 (agent_factory.py extraction) — construction of `DelegationDispatcher` moves to the factory, reducing `loop.py` churn when we restructure `delegation.py`

---

## Goal

Break `delegation.py` (1,003 lines) into focused modules by extracting two independent concerns: the task type taxonomy and the delegation contract builder. After this change, `delegation.py` owns only dispatch routing and delegated agent execution — one responsibility.

## Motivation

`delegation.py` currently mixes four concerns:
1. **Task type taxonomy** (lines 88-170, 489-622) — `TASK_TYPES` dict, `classify_task_type()`, `has_parallel_structure()` — pure classification with no dispatch dependency
2. **Contract construction** (lines 628-696) — `build_delegation_contract()` — assembles prompts for delegated agents; depends on task types but not on dispatch
3. **Context helpers** (lines 378-483) — `gather_recent_tool_results()`, `extract_plan_text()`, `extract_user_request()`, `build_execution_context()`, `build_parallel_work_summary()` — message scanning utilities used by contracts and execution
4. **Dispatch routing + execution** (rest) — `DelegationDispatcher`, `DelegationConfig`, `dispatch()`, `execute_delegated_agent()`, cycle detection, tool registry building

Concerns 1 and 2 are independently testable and reused by `mission.py` (which imports `TASK_TYPES`) and `turn_orchestrator.py` (which calls `has_parallel_structure()`). Extracting them:
- Makes the taxonomy editable without touching dispatch logic
- Gives contract construction its own test surface
- Reduces `delegation.py` to ~700 lines focused on dispatch

## Approach

### New file: `nanobot/agent/task_types.py`

Contains everything related to classifying tasks by type:

| Symbol | Current location | Lines |
|--------|-----------------|-------|
| `TASK_TYPES` (dict) | delegation.py:88-170 | ~82 |
| `classify_task_type(role, task)` | delegation.py:489-597 (currently a static method on DelegationDispatcher) | ~108 |
| `has_parallel_structure(text)` | delegation.py:599-622 (currently a static method on DelegationDispatcher) | ~23 |

Total: ~213 lines.

**Dependencies:** None from `agent/` — pure data + keyword matching. Only stdlib imports (`re`).

**Consumers that need updating:**
- `delegation.py` — calls `classify_task_type()` and `has_parallel_structure()` internally; will import from `task_types`
- `mission.py:25` — imports `TASK_TYPES` from `delegation`; changes to import from `task_types`
- `turn_orchestrator.py:774` — calls `DelegationDispatcher.has_parallel_structure()`; changes to import `has_parallel_structure` from `task_types`
- `delegation_advisor.py` — calls `DelegationDispatcher.has_parallel_structure()` via the dispatcher instance; changes to import directly from `task_types`
- Tests: `test_delegation_dispatcher.py` imports `TASK_TYPES`; update import path

**Backward compatibility:** Add re-exports in `delegation.py`:
```python
# Backward compat — moved to task_types.py
from nanobot.agent.task_types import TASK_TYPES, classify_task_type, has_parallel_structure  # noqa: F401
```
These can be removed in a later cleanup pass. `DelegationDispatcher.classify_task_type` and `DelegationDispatcher.has_parallel_structure` become thin static-method wrappers that delegate to the module-level functions, preserving the existing call patterns until callers are updated.

### New file: `nanobot/agent/delegation_contract.py`

Contains contract assembly and the context helpers it depends on:

| Symbol | Current location | Lines |
|--------|-----------------|-------|
| `build_delegation_contract(role, task, context, task_type)` | delegation.py:628-696 | ~68 |
| `gather_recent_tool_results(active_messages, max_results, max_chars)` | delegation.py:378-414 | ~36 |
| `extract_plan_text(active_messages)` | delegation.py:416-433 | ~17 |
| `extract_user_request(active_messages)` | delegation.py:435-444 | ~9 |
| `build_execution_context(workspace, task_type)` | delegation.py:446-469 | ~23 |
| `build_parallel_work_summary(scratchpad, role)` | delegation.py:471-483 | ~12 |
| `_cap_scratchpad_for_injection(content, limit)` | delegation.py:173-180 | ~7 |
| `_SCRATCHPAD_INJECTION_LIMIT` | delegation.py:82 | 1 |

Total: ~173 lines.

**Key change:** These are currently instance methods on `DelegationDispatcher` that read `self.active_messages`, `self.workspace`, `self.scratchpad`. They become module-level functions that take these as explicit parameters. This makes them pure functions — easier to test, no class coupling.

**Dependencies:** `prompt_loader` (for `prompts.render()`), `task_types` (for `TASK_TYPES`). No dependency on `DelegationDispatcher`.

**Consumers that need updating:**
- `DelegationDispatcher.dispatch()` and `execute_delegated_agent()` — currently call `self.build_delegation_contract(...)`, `self.gather_recent_tool_results(...)`, etc. Will import from `delegation_contract` and pass `self.active_messages`, `self.workspace`, `self.scratchpad` as arguments
- Tests: `test_delegation_dispatcher.py` imports `_SCRATCHPAD_INJECTION_LIMIT`, `_cap_scratchpad_for_injection`; update import paths

**Backward compatibility:** Add re-exports in `delegation.py` for `_SCRATCHPAD_INJECTION_LIMIT` and `_cap_scratchpad_for_injection` (used by tests).

### What stays in `delegation.py`

After extraction, `delegation.py` contains:

| Symbol | Lines (approx) |
|--------|----------------|
| `_delegation_ancestry` ContextVar | ~3 |
| `MAX_DELEGATION_DEPTH` | 1 |
| `get_delegation_depth()` | ~3 |
| `DelegationConfig` dataclass | ~20 |
| `DelegationDispatcher.__init__` | ~95 |
| `DelegationDispatcher.wire_delegate_tools()` | ~20 |
| `DelegationDispatcher.record_route_trace()` / `get_routing_trace()` | ~40 |
| `DelegationDispatcher.dispatch()` | ~133 |
| `DelegationDispatcher.execute_delegated_agent()` | ~161 |
| Backward-compat re-exports | ~5 |
| Imports + module docstring | ~70 |

**Total: ~550 lines** (down from 1,003).

Responsibilities: dispatch routing, cycle/depth detection, tool registry building for delegated agents, trace recording, delegated agent execution.

### Import changes summary

**`task_types.py`** (new) — zero agent/ imports, only `re` and `AgentRoleConfig` from config
**`delegation_contract.py`** (new) — imports `prompt_loader`, `task_types`, `tracing`; TYPE_CHECKING: `Scratchpad`
**`delegation.py`** (modified) — drops ~8 lines of imports (task type keywords, contract helpers); adds imports from `task_types` and `delegation_contract`
**`mission.py`** — changes `from nanobot.agent.delegation import TASK_TYPES` to `from nanobot.agent.task_types import TASK_TYPES`
**`turn_orchestrator.py`** — changes `DelegationDispatcher.has_parallel_structure(...)` to `has_parallel_structure(...)` imported from `task_types`
**`delegation_advisor.py`** — same pattern as turn_orchestrator

### `__init__.py` exports

No changes needed. `DelegationDispatcher` remains the only publicly exported symbol from the delegation layer. `TASK_TYPES`, `classify_task_type`, `has_parallel_structure` are internal — consumers import them directly from their modules.

### Static methods → module functions

`classify_task_type` and `has_parallel_structure` are currently `@staticmethod` on `DelegationDispatcher`. They don't use `self` — they are pure functions that happen to live on the class. Moving them to module-level functions in `task_types.py` is a pure refactor.

To maintain backward compatibility during the transition:
```python
# In delegation.py, after the extraction:
class DelegationDispatcher:
    # Thin wrappers — delegate to module functions
    @staticmethod
    def classify_task_type(role: AgentRoleConfig, task: str) -> str:
        return classify_task_type(role, task)

    @staticmethod
    def has_parallel_structure(text: str) -> bool:
        return has_parallel_structure(text)
```

These wrappers can be removed once all callers are updated to use the module-level functions directly.

## Constraints

- No behavioral change — dispatch routing, cycle detection, contract format all remain identical
- All existing tests must pass (backward-compat re-exports preserve import paths)
- Phase 1 (agent_factory) should be completed first so that `DelegationDispatcher` construction lives in the factory, not in `loop.py.__init__`
- The `DelegationConfig` dataclass stays in `delegation.py` — it's a construction-time concern closely tied to the dispatcher

## Success criteria

- `delegation.py` is under 600 lines
- `task_types.py` has no imports from `delegation.py` (no reverse dependency)
- `delegation_contract.py` has no imports from `delegation.py` (no reverse dependency)
- `make check` passes
- All existing tests pass
- New test files: `test_task_types.py` (classify + parallel structure), `test_delegation_contract.py` (contract assembly + context helpers)
