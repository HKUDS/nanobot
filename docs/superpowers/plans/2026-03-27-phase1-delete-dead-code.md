# Phase 1: Delete Dead Code — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all routing, role-switching, delegation advisor, and plan enforcement code that is dead with multi-role disabled — approximately 1,600 LOC deleted.

**Architecture:** Pure deletion and cleanup. No new features, no behavioral changes. The agent continues to work exactly as it does today (single role, no routing). Every task produces a codebase that passes `make check`.

**Tech Stack:** Python 3.10+, ruff, mypy, pytest

**Spec:** `docs/superpowers/specs/2026-03-27-agent-cognitive-redesign.md`, Phase 1 section

**IMPORTANT:** This is a deletion phase. Do NOT add new code, refactor surviving code, or "improve" anything. Delete only. The surviving code may look incomplete — that's intentional. Phases 2-6 of the redesign will rebuild.

---

## File Map

### Files to DELETE

| File | LOC | Why |
|------|-----|-----|
| `nanobot/coordination/coordinator.py` | ~350 | Routing: LLM-based intent classification |
| `nanobot/coordination/router.py` | ~200 | Routing: message routing logic |
| `nanobot/coordination/role_switching.py` | ~150 | Routing: per-turn role application |
| `nanobot/coordination/registry.py` | ~100 | Routing: role name -> config mapping |
| `nanobot/coordination/delegation_advisor.py` | ~200 | Delegation nudge engine |
| `nanobot/templates/prompts/classify.md` | 14 | Classification prompt |
| `nanobot/templates/prompts/role_code.md` | ~15 | Role prompt |
| `nanobot/templates/prompts/role_pm.md` | ~15 | Role prompt |
| `nanobot/templates/prompts/role_research.md` | ~15 | Role prompt |
| `nanobot/templates/prompts/role_writing.md` | ~15 | Role prompt |
| `nanobot/templates/prompts/role_system.md` | ~15 | Role prompt |
| `nanobot/templates/prompts/nudge_delegation_exhausted.md` | ~5 | Delegation nudge |
| `nanobot/templates/prompts/nudge_post_delegation.md` | ~5 | Delegation nudge |
| `nanobot/templates/prompts/nudge_ungrounded_warning.md` | ~5 | Delegation nudge |
| `nanobot/templates/prompts/nudge_use_parallel.md` | ~5 | Delegation nudge |
| `nanobot/templates/prompts/nudge_parallel_structure.md` | ~5 | Delegation nudge |
| `nanobot/templates/prompts/nudge_plan_enforcement.md` | ~5 | Plan enforcement nudge |
| `tests/test_coordinator.py` | ~300 | Tests for deleted coordinator |
| `tests/test_routing_metrics.py` | ~100 | Tests for routing metrics |
| `tests/test_role_switching.py` | ~100 | Tests for role switching |
| `tests/test_agent_registry.py` | ~100 | Tests for agent registry |
| `tests/test_delegation_advisor.py` | ~200 | Tests for delegation advisor |
| `tests/contract/test_routing_invariant.py` | ~350 | Contract tests for routing |
| `tests/contract/test_reflect_role_name.py` | ~50 | Contract test for ReflectPhase role |
| `tests/test_process_direct_forced_role.py` | ~100 | Tests for forced role routing |
| `tests/test_multiagent_planning.py` | ~150 | Tests for multi-agent planning |

### Files to MODIFY

| File | Change Summary |
|------|---------------|
| `nanobot/agent/turn_orchestrator.py` | Remove ReflectPhase, plan enforcement, delegation advisor, active_* resolution |
| `nanobot/agent/turn_phases.py` | Delete ReflectPhase class, remove _needs_planning and _PLANNING_SIGNALS |
| `nanobot/agent/message_processor.py` | Remove routing pipeline, role manager, active_* settings |
| `nanobot/agent/agent_factory.py` | Remove Coordinator, Router, RoleManager, DelegationAdvisor construction |
| `nanobot/agent/agent_components.py` | Remove coordinator, role_manager, delegation_advisor from dataclasses |
| `nanobot/agent/turn_types.py` | Remove active_* fields, classification_result, DelegationAction import |
| `nanobot/agent/loop.py` | Remove _wire_coordinator, coordinator state flags |
| `nanobot/coordination/__init__.py` | Remove router re-exports, update __all__ |
| `nanobot/tools/capability.py` | Remove AgentRegistry TYPE_CHECKING import |
| `prompts_manifest.json` | Remove entries for deleted prompt files |

---

## Tasks

### Task 1: Remove ReflectPhase and delegation advisor from the PAOR loop

This is the highest-impact deletion — it removes the 130-line ReflectPhase class and all delegation advisor integration from the turn loop.

**Files:**
- Modify: `nanobot/agent/turn_orchestrator.py`
- Modify: `nanobot/agent/turn_phases.py`
- Modify: `nanobot/agent/turn_types.py`

- [ ] **Step 1: Remove ReflectPhase from turn_orchestrator.py**

In `nanobot/agent/turn_orchestrator.py`, make these edits:

Remove the `ReflectPhase` import (line 33):
```python
# DELETE this import:
from nanobot.agent.turn_phases import (
    _CONTEXT_RESERVE_RATIO,
    _DELEGATION_TOOL_NAMES,
    ActPhase,
    ReflectPhase,
    _dynamic_preserve_recent,
    _needs_planning,
    _safe_int,
)
# REPLACE with:
from nanobot.agent.turn_phases import (
    _CONTEXT_RESERVE_RATIO,
    ActPhase,
    _dynamic_preserve_recent,
    _safe_int,
)
```

Remove the `DelegationAdvisor` TYPE_CHECKING import (line 49):
```python
# DELETE this line:
    from nanobot.coordination.delegation_advisor import DelegationAdvisor
```

Remove the `DelegationAdvisor` constructor parameter and `ReflectPhase` construction (lines 72, 89, 100-105):
```python
# In __init__, DELETE these parameters:
        dispatcher: DelegationDispatcher,
        delegation_advisor: DelegationAdvisor,

# DELETE these lines:
        self._dispatcher = dispatcher
        self._delegation_advisor = delegation_advisor

# DELETE ReflectPhase construction:
        self._reflect = ReflectPhase(
            dispatcher=dispatcher,
            delegation_advisor=delegation_advisor,
            prompts=prompts,
            role_name=role_name,
        )
```

Remove the delegation advisor plan-phase logic (lines 156-186):
```python
# DELETE the entire block starting with:
        from nanobot.coordination.delegation_advisor import DelegationAction
# through:
                    logger.debug("Delegation advisor plan-phase: {}", plan_advice.reason)
```

Remove the `ReflectPhase.evaluate()` call in the main loop (lines 362-369):
```python
# DELETE:
                # --- REFLECT: evaluate progress and inject guidance ---------
                self._reflect.evaluate(
                    state,
                    response,
                    batch.any_failed,
                    batch.failed_this_batch,
                    role_name=effective_role_name,
                )
```

Remove dispatcher wiring in `run()` (lines 128-130):
```python
# DELETE:
        self._dispatcher.on_progress = on_progress
        self._dispatcher.active_messages = state.messages
        self._dispatcher.delegation_count = 0

# DELETE at end of run():
        self._dispatcher.on_progress = None
```

- [ ] **Step 2: Delete ReflectPhase class from turn_phases.py**

In `nanobot/agent/turn_phases.py`, delete the entire ReflectPhase section (lines 341-477):
```python
# DELETE everything from:
# ---------------------------------------------------------------------------
# ReflectPhase
# ---------------------------------------------------------------------------
# through end of file
```

Also remove the TYPE_CHECKING imports it used (lines 28-31):
```python
# DELETE these lines from TYPE_CHECKING block:
    from nanobot.context.prompt_loader import PromptLoader
    from nanobot.coordination.delegation import DelegationDispatcher
    from nanobot.coordination.delegation_advisor import DelegationAdvisor
```

Also remove unused constants (lines 44-46):
```python
# DELETE:
_DELEGATION_TOOL_NAMES: frozenset[str] = frozenset({"delegate", "delegate_parallel"})
```

Also remove the `DelegationAction` runtime import in the deleted code and the `has_parallel_structure` import (line 22):
```python
# DELETE:
from nanobot.coordination.task_types import has_parallel_structure
```

- [ ] **Step 3: Remove DelegationAction and last_delegation_advice from turn_types.py**

In `nanobot/agent/turn_types.py`, remove the TYPE_CHECKING import (line 24):
```python
# DELETE:
    from nanobot.coordination.delegation_advisor import DelegationAction
```

Remove the `last_delegation_advice` field from `TurnState`:
```python
# DELETE:
    last_delegation_advice: DelegationAction | None = None
```

- [ ] **Step 4: Run tests**

Run: `make lint && make typecheck`
Expected: PASS (no references to deleted code remain in modified files)

Run: `make test`
Expected: Some test failures from tests that import deleted code (will be cleaned in Task 9)

- [ ] **Step 5: Commit**

```bash
git add nanobot/agent/turn_orchestrator.py nanobot/agent/turn_phases.py nanobot/agent/turn_types.py
git commit -m "refactor(agent): remove ReflectPhase and delegation advisor from PAOR loop

Remove the 130-line ReflectPhase class and all delegation advisor
integration from TurnOrchestrator. With routing disabled and single-agent
design, delegation nudges serve no purpose.

Part of Phase 1: agent cognitive core redesign (delete dead code)."
```

---

### Task 2: Remove plan enforcement from the loop

**Files:**
- Modify: `nanobot/agent/turn_phases.py`
- Modify: `nanobot/agent/turn_orchestrator.py`

- [ ] **Step 1: Remove _needs_planning and _PLANNING_SIGNALS from turn_phases.py**

Delete `_PLANNING_SIGNALS` constant (lines 55-80):
```python
# DELETE the entire tuple definition from:
_PLANNING_SIGNALS: tuple[str, ...] = (
# through the closing )
```

Delete `_GREETING_MAX_LEN` constant (line 48):
```python
# DELETE:
_GREETING_MAX_LEN: int = 20
```

Delete `_needs_planning` function (lines 94-108):
```python
# DELETE the entire function
```

- [ ] **Step 2: Remove plan enforcement from turn_orchestrator.py**

Remove `_needs_planning` from imports (already partially done in Task 1, verify it's clean).

Remove the entire plan-phase block in `run()`. After Task 1 removed the delegation advisor part, what remains is the `_needs_planning` check and plan prompt injection. Find and delete:
```python
# DELETE the planning block (approximately lines 158-169 after Task 1 edits):
        _raw_pe = getattr(self._config, "planning_enabled", False)
        planning_enabled = _raw_pe if isinstance(_raw_pe, bool) else False
        if planning_enabled:
            if _needs_planning(state.user_text):
                state.messages.append(
                    {
                        "role": "system",
                        "content": self._prompts.get("plan"),
                    }
                )
                state.has_plan = True
                logger.debug("Planning prompt injected for: {}...", state.user_text[:60])
```

Also remove the plan enforcement nudge in the tool-call handling (approximately lines 278-294 after Task 1 edits):
```python
# DELETE the plan enforcement block:
                is_delegation = all(tc.name in _DELEGATION_TOOL_NAMES for tc in response.tool_calls)
                if (
                    state.has_plan
                    and not state.plan_enforced
                    and state.turn_tool_calls == 0
                    and not response.content
                    and not is_delegation
                ):
                    state.plan_enforced = True
                    state.messages.append(
                        {
                            "role": "system",
                            "content": self._prompts.get("nudge_plan_enforcement"),
                        }
                    )
                    logger.debug("Plan enforcement: nudging model to produce plan first")
                    continue
```

Also remove the `_DELEGATION_TOOL_NAMES` import if it was kept in Task 1.

- [ ] **Step 3: Remove plan-related fields from TurnState**

In `nanobot/agent/turn_types.py`, remove:
```python
# DELETE:
    has_plan: bool = False
    plan_enforced: bool = False
```

- [ ] **Step 4: Run lint and typecheck**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nanobot/agent/turn_phases.py nanobot/agent/turn_orchestrator.py nanobot/agent/turn_types.py
git commit -m "refactor(agent): remove plan enforcement heuristic from loop

Remove _needs_planning() keyword matching, _PLANNING_SIGNALS, and plan
enforcement nudge logic. Planning will be handled by the reasoning
protocol in the system prompt, not by code-level keyword detection.

Part of Phase 1: agent cognitive core redesign (delete dead code)."
```

---

### Task 3: Remove routing pipeline from MessageProcessor

**Files:**
- Modify: `nanobot/agent/message_processor.py`

- [ ] **Step 1: Remove routing imports and attributes**

Remove TYPE_CHECKING imports:
```python
# DELETE these lines from TYPE_CHECKING block:
    from nanobot.coordination.coordinator import ClassificationResult
    from nanobot.coordination.router import MessageRouter
    from nanobot.coordination.role_switching import TurnContext, TurnRoleManager
```

Remove constructor parameters related to routing. In `__init__`, delete:
```python
# DELETE parameters:
        router: MessageRouter | None = None,

# DELETE attribute assignments:
        self._router = router
        self._role_manager: TurnRoleManager | None = None
        self._active_model: str | None = None
        self._active_temperature: float | None = None
        self._active_max_iterations: int | None = None
        self._active_role_name: str | None = None
        self.classification_result: ClassificationResult | None = None
```

- [ ] **Step 2: Remove routing methods**

Delete these methods entirely:
```python
# DELETE set_role_manager():
    def set_role_manager(self, role_manager: TurnRoleManager) -> None: ...

# DELETE set_classification_result():
    def set_classification_result(self, result: ClassificationResult | None) -> None: ...

# DELETE set_active_settings():
    def set_active_settings(self, *, model, temperature, max_iterations, role_name) -> None: ...
```

- [ ] **Step 3: Remove routing pipeline from _process_message()**

In `_process_message()`, find and delete the routing block (approximately lines 152-179):
```python
# DELETE the routing block starting with:
        if self._router:
            ...
# through the end of the role application logic
```

Also delete the `try/finally` that resets the role at the end of `_process_message()` — find the `finally` block that calls `self._role_manager.reset()` and remove it, keeping the code that was inside the `try`.

Also remove the runtime import of `UnknownRoleError`:
```python
# DELETE (inside _process_message):
            from nanobot.coordination.router import UnknownRoleError
```

- [ ] **Step 4: Remove active_* from _run_orchestrator()**

In `_run_orchestrator()`, remove the lines that set active settings on TurnState:
```python
# DELETE lines like:
        state = TurnState(
            ...
            active_model=self._active_model,
            active_temperature=self._active_temperature,
            active_max_iterations=self._active_max_iterations,
            active_role_name=self._active_role_name,
            classification_result=self.classification_result,
            ...
        )
```

Replace with TurnState construction without those fields.

- [ ] **Step 5: Run lint and typecheck**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nanobot/agent/message_processor.py
git commit -m "refactor(agent): remove routing pipeline from MessageProcessor

Remove router, role manager, classification result tracking, and
active_* settings from the message processing pipeline. The processor
now runs every message through the orchestrator directly without
classification or role switching.

Part of Phase 1: agent cognitive core redesign (delete dead code)."
```

---

### Task 4: Remove routing from agent_factory and components

**Files:**
- Modify: `nanobot/agent/agent_factory.py`
- Modify: `nanobot/agent/agent_components.py`
- Modify: `nanobot/agent/loop.py`

- [ ] **Step 1: Remove routing construction from agent_factory.py**

Remove imports:
```python
# DELETE:
from nanobot.coordination.coordinator import DEFAULT_ROLES, Coordinator
from nanobot.coordination.delegation_advisor import DelegationAdvisor
from nanobot.coordination.registry import AgentRegistry as _AgentRegistry
from nanobot.coordination.role_switching import TurnRoleManager
# DELETE (conditional import):
from nanobot.coordination.router import MessageRouter
```

Remove the Coordinator/Router/RoleManager construction blocks in `build_agent()`. Find and delete:
- The `_AgentRegistry` construction and DEFAULT_ROLES registration
- The `Coordinator` construction block (approximately lines 316-336)
- The `MessageRouter` construction block (approximately lines 338-347)
- The `DelegationAdvisor` construction (approximately line 350)
- The `TurnRoleManager` post-construction wiring (approximately lines 486-489)

Remove `delegation_advisor` from `TurnOrchestrator` construction:
```python
# In the TurnOrchestrator() call, DELETE these parameters:
        dispatcher=dispatcher,
        delegation_advisor=delegation_advisor,
```

Remove `router` from `MessageProcessor` construction:
```python
# In the MessageProcessor() call, DELETE:
        router=router,
```

Remove `coordinator` and `role_manager` from `_AgentComponents` construction.

- [ ] **Step 2: Clean agent_components.py**

Remove routing-related fields from dataclasses:
```python
# In _AgentComponents, DELETE:
    coordinator: Coordinator | None
    role_manager: TurnRoleManager | None

# Remove corresponding TYPE_CHECKING imports:
    from nanobot.coordination.coordinator import Coordinator
    from nanobot.coordination.delegation_advisor import DelegationAdvisor
    from nanobot.coordination.role_switching import TurnRoleManager
```

Remove `delegation_advisor` from `_Subsystems` if present.

- [ ] **Step 3: Remove coordinator wiring from loop.py**

In `nanobot/agent/loop.py`, find and delete:
```python
# DELETE attribute:
        self._coordinator_wired: bool = False

# DELETE the entire _wire_coordinator() method

# DELETE the call to _wire_coordinator() in run() or _process_message()
```

- [ ] **Step 4: Remove dispatcher and delegation_advisor from TurnOrchestrator constructor**

Verify that Task 1 already removed these from `turn_orchestrator.py`. If the `dispatcher` parameter is still there (used for `on_progress` wiring), check if it's still needed. If the only usage was `self._dispatcher.on_progress = on_progress` and `self._dispatcher.delegation_count = 0` (which were deleted in Task 1), remove the parameter entirely.

- [ ] **Step 5: Run lint and typecheck**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nanobot/agent/agent_factory.py nanobot/agent/agent_components.py nanobot/agent/loop.py
git commit -m "refactor(agent): remove routing wiring from factory and loop

Remove Coordinator, MessageRouter, TurnRoleManager, DelegationAdvisor,
and AgentRegistry construction from build_agent(). Remove coordinator
wiring from AgentLoop. Remove routing fields from _AgentComponents.

Part of Phase 1: agent cognitive core redesign (delete dead code)."
```

---

### Task 5: Remove active_* fields from TurnState and orchestrator resolution

**Files:**
- Modify: `nanobot/agent/turn_types.py`
- Modify: `nanobot/agent/turn_orchestrator.py`

- [ ] **Step 1: Remove active_* fields from TurnState**

In `nanobot/agent/turn_types.py`, delete:
```python
# DELETE from TurnState:
    classification_result: ClassificationResult | None = None
    active_model: str | None = None
    active_temperature: float | None = None
    active_max_iterations: int | None = None
    active_role_name: str | None = None
```

Remove the `ClassificationResult` TYPE_CHECKING import:
```python
# DELETE:
    from nanobot.coordination.coordinator import ClassificationResult
```

Remove role-related methods from the `Processor` protocol:
```python
# DELETE these methods from the Processor protocol:
    def set_role_manager(self, role_manager: ...) -> None: ...
    def set_classification_result(self, result: ...) -> None: ...
    def set_active_settings(self, ...) -> None: ...
```

- [ ] **Step 2: Remove effective_* resolution from turn_orchestrator.py**

In `TurnOrchestrator.run()`, simplify the effective settings resolution (approximately lines 139-148):
```python
# DELETE:
        effective_model = state.active_model if state.active_model is not None else self._model
        effective_role_name = (
            state.active_role_name if state.active_role_name is not None else self._role_name
        )
        max_iterations = (
            state.active_max_iterations
            if state.active_max_iterations is not None
            else self._max_iterations
        )

# REPLACE with direct usage:
        max_iterations = self._max_iterations
```

Update all references to `effective_model` and `effective_role_name` in the method to use `self._model` and `self._role_name` directly.

Update the LLM call to not pass `state.active_model` or `state.active_temperature`:
```python
# Find and simplify the call to self._llm_caller.call():
# Remove model= and temperature= overrides that referenced state.active_*
```

- [ ] **Step 3: Run lint and typecheck**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add nanobot/agent/turn_types.py nanobot/agent/turn_orchestrator.py
git commit -m "refactor(agent): remove active_* role-switch fields from TurnState

Remove classification_result, active_model, active_temperature,
active_max_iterations, active_role_name from TurnState. Remove
effective_* resolution logic from TurnOrchestrator. The orchestrator
now uses construction-time settings directly.

Part of Phase 1: agent cognitive core redesign (delete dead code)."
```

---

### Task 6: Delete routing source files

Now that no production code references them, delete the files.

**Files:**
- Delete: `nanobot/coordination/coordinator.py`
- Delete: `nanobot/coordination/router.py`
- Delete: `nanobot/coordination/role_switching.py`
- Delete: `nanobot/coordination/registry.py`
- Delete: `nanobot/coordination/delegation_advisor.py`
- Modify: `nanobot/coordination/__init__.py`
- Modify: `nanobot/tools/capability.py`

- [ ] **Step 1: Delete the five source files**

```bash
rm nanobot/coordination/coordinator.py
rm nanobot/coordination/router.py
rm nanobot/coordination/role_switching.py
rm nanobot/coordination/registry.py
rm nanobot/coordination/delegation_advisor.py
```

- [ ] **Step 2: Update coordination/__init__.py**

Replace the entire file:
```python
"""Multi-agent coordination: delegation and mission management."""

from __future__ import annotations

__all__: list[str] = []
```

The routing exports (`MessageRouter`, `RoutingDecision`, `UnknownRoleError`) are removed. The package still exists for delegation.py, mission.py, scratchpad.py, task_types.py, and delegation_contract.py.

- [ ] **Step 3: Remove AgentRegistry from capability.py**

In `nanobot/tools/capability.py`, remove the TYPE_CHECKING import:
```python
# DELETE:
    from nanobot.coordination.registry import AgentRegistry
```

Find any methods or type annotations that reference `AgentRegistry` and update them. The `register_role()` and `merge_register_role()` methods may reference `AgentRoleConfig` (from config schema, which stays) but not `AgentRegistry`. Verify and clean.

- [ ] **Step 4: Run lint and typecheck**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A nanobot/coordination/ nanobot/tools/capability.py
git commit -m "refactor(coordination): delete routing source files

Delete coordinator.py, router.py, role_switching.py, registry.py,
delegation_advisor.py. Update coordination/__init__.py to empty exports.
Remove AgentRegistry reference from capability.py.

Coordination package now contains only: delegation, mission, scratchpad,
task_types, delegation_contract.

Part of Phase 1: agent cognitive core redesign (delete dead code)."
```

---

### Task 7: Delete prompt templates and update manifest

**Files:**
- Delete: 12 prompt template files
- Modify: `prompts_manifest.json`

- [ ] **Step 1: Delete routing and delegation prompt files**

```bash
rm nanobot/templates/prompts/classify.md
rm nanobot/templates/prompts/role_code.md
rm nanobot/templates/prompts/role_pm.md
rm nanobot/templates/prompts/role_research.md
rm nanobot/templates/prompts/role_writing.md
rm nanobot/templates/prompts/role_system.md
rm nanobot/templates/prompts/nudge_delegation_exhausted.md
rm nanobot/templates/prompts/nudge_post_delegation.md
rm nanobot/templates/prompts/nudge_ungrounded_warning.md
rm nanobot/templates/prompts/nudge_use_parallel.md
rm nanobot/templates/prompts/nudge_parallel_structure.md
rm nanobot/templates/prompts/nudge_plan_enforcement.md
```

- [ ] **Step 2: Update prompts_manifest.json**

Remove entries for all 12 deleted files. The following keys must be removed:
- `classify.md`
- `role_code.md`
- `role_pm.md`
- `role_research.md`
- `role_writing.md`
- `role_system.md`
- `nudge_delegation_exhausted.md`
- `nudge_post_delegation.md`
- `nudge_ungrounded_warning.md`
- `nudge_use_parallel.md`
- `nudge_parallel_structure.md`
- `nudge_plan_enforcement.md`

- [ ] **Step 3: Verify prompt manifest**

Run: `python scripts/check_prompt_manifest.py`
Expected: PASS (manifest matches remaining files)

- [ ] **Step 4: Commit**

```bash
git add -A nanobot/templates/prompts/ prompts_manifest.json
git commit -m "chore: delete routing and delegation prompt templates

Remove 12 prompt template files no longer referenced by any code:
classify.md, 5 role_*.md files, 6 nudge_*.md files.
Update prompts_manifest.json to match.

Part of Phase 1: agent cognitive core redesign (delete dead code)."
```

---

### Task 8: Delete routing test files

**Files:**
- Delete: 8 test files
- Modify: 3-5 test files (remove dead imports)

- [ ] **Step 1: Delete test files for deleted modules**

```bash
rm tests/test_coordinator.py
rm tests/test_routing_metrics.py
rm tests/test_role_switching.py
rm tests/test_agent_registry.py
rm tests/test_delegation_advisor.py
rm tests/contract/test_routing_invariant.py
rm tests/contract/test_reflect_role_name.py
rm tests/test_process_direct_forced_role.py
rm tests/test_multiagent_planning.py
```

- [ ] **Step 2: Clean surviving test files**

Check each of these test files for imports from deleted modules and remove them:

`tests/test_delegate.py` — may import `Coordinator`, `build_default_registry`. Remove those imports and any test functions that depend on them. Keep delegation-related tests that test `DelegationDispatcher` directly.

`tests/test_parallel_delegation.py` — may import `Coordinator`, `build_default_registry`. Same cleanup.

`tests/test_delegation_dispatcher.py` — may import `Coordinator` inside test functions. Remove those test functions or replace with direct construction.

`tests/test_delegation_security.py` — may import `Coordinator`, `AgentRegistry`. Remove those imports and dependent tests.

`tests/test_capability_registry.py` — may import `AgentRegistry`. Remove that import and tests that use it.

`tests/test_capability_wiring.py` — may import `AgentRegistry` inside test functions. Remove those specific tests.

`tests/test_turn_phases.py` — remove all tests for `ReflectPhase`, `_needs_planning`, `_PLANNING_SIGNALS`. Keep tests for `ActPhase` and other surviving code.

`tests/test_agent_loop.py` — check for references to routing, classification, role switching. Remove any such tests.

`tests/test_loop_helper_paths.py` — check for references to deleted code.

`tests/test_coverage_push_wave6.py` — check for references to deleted code.

For each file: search for imports from `nanobot.coordination.coordinator`, `nanobot.coordination.router`, `nanobot.coordination.role_switching`, `nanobot.coordination.registry`, `nanobot.coordination.delegation_advisor`. Remove those imports and any code that depends on them.

- [ ] **Step 3: Run full test suite**

Run: `make test`
Expected: PASS (all surviving tests pass, no import errors)

- [ ] **Step 4: Commit**

```bash
git add -A tests/
git commit -m "test: remove routing and delegation advisor test files

Delete 9 test files for deleted modules. Clean surviving test files
by removing imports from coordinator, router, role_switching, registry,
and delegation_advisor.

Part of Phase 1: agent cognitive core redesign (delete dead code)."
```

---

### Task 9: Update boundary check scripts

**Files:**
- Modify: `scripts/check_imports.py` (if it has routing-specific rules)

- [ ] **Step 1: Check if import boundary rules reference deleted modules**

Read `scripts/check_imports.py` and check for any rules that specifically mention:
- `coordination.coordinator`
- `coordination.router`
- `coordination.role_switching`
- `coordination.registry`
- `coordination.delegation_advisor`

If found, remove those specific rules. Keep the general coordination/ boundary rules (coordination must not import from channels, etc.).

- [ ] **Step 2: Run all boundary checks**

Run: `make import-check`
Expected: PASS

Run: `make structure-check`
Expected: PASS

- [ ] **Step 3: Commit (if changes were made)**

```bash
git add scripts/check_imports.py
git commit -m "chore: update import boundary rules for deleted modules

Remove boundary rules that referenced deleted coordination modules.
Keep general package-level boundary rules.

Part of Phase 1: agent cognitive core redesign (delete dead code)."
```

---

### Task 10: Final validation

- [ ] **Step 1: Run full validation suite**

Run: `make check`
Expected: PASS (lint + typecheck + import-check + structure-check + prompt-check + test + integration)

- [ ] **Step 2: Verify file counts**

Check that the coordination package is within limits:
```bash
find nanobot/coordination -maxdepth 1 -name '*.py' ! -name '__init__.py' | wc -l
```
Expected: 5 files (delegation.py, delegation_contract.py, mission.py, scratchpad.py, task_types.py)

Check agent package:
```bash
find nanobot/agent -maxdepth 1 -name '*.py' ! -name '__init__.py' | wc -l
```
Expected: fewer files than before (turn_phases.py should be smaller, same count)

- [ ] **Step 3: Verify LOC reduction**

```bash
find nanobot/agent nanobot/coordination -name '*.py' -exec cat {} + | wc -l
```
Compare with pre-Phase-1 count. Expected reduction: ~1,400-1,600 LOC.

- [ ] **Step 4: Smoke test the agent**

If the agent can be run locally:
```bash
nanobot agent -m "What is 2+2?"
```
Expected: Agent responds normally. No routing, no role classification, no delegation nudges.

- [ ] **Step 5: Final commit (if any remaining cleanup)**

```bash
git status
# If any unstaged changes remain, review and commit
```

---

## Summary

| Task | Files Changed | Estimated Effort |
|------|--------------|-----------------|
| 1. Remove ReflectPhase + delegation advisor | 3 modified | 15 min |
| 2. Remove plan enforcement | 3 modified | 10 min |
| 3. Remove routing from MessageProcessor | 1 modified | 15 min |
| 4. Remove routing from factory + components | 3 modified | 15 min |
| 5. Remove active_* from TurnState | 2 modified | 10 min |
| 6. Delete routing source files | 5 deleted, 2 modified | 10 min |
| 7. Delete prompt templates + manifest | 12 deleted, 1 modified | 5 min |
| 8. Delete routing test files | 9 deleted, 5-8 modified | 20 min |
| 9. Update boundary check scripts | 1 modified | 5 min |
| 10. Final validation | 0 | 10 min |
| **Total** | **~35 deleted, ~15 modified** | **~2 hours** |
