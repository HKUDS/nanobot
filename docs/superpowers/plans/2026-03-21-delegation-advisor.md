# DelegationAdvisor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify three contradictory delegation triggers into a single coherent DelegationAdvisor.

**Architecture:** New `delegation_advisor.py` module with `DelegationAdvisor` class, two-phase API (`advise_plan_phase` + `advise_reflect_phase`), structured `DelegationAdvice` output. Hybrid approach: soft advisory for normal cases, hard gate for budget exhaustion.

**Tech Stack:** Python 3.10+, Pydantic-free dataclasses (frozen, slots), pytest parametrize for tests.

---

## File Structure

| File | Responsibility | Change |
|------|---------------|--------|
| `nanobot/agent/delegation_advisor.py` | DelegationAdvisor, DelegationAdvice, RolePolicy, DelegationAction | **New** |
| `nanobot/agent/delegation.py` | Add `get_delegation_depth()` public function | **Modify** |
| `nanobot/agent/coordinator.py` | Return `ClassificationResult` from `classify()` | **Modify** |
| `nanobot/agent/loop.py` | Replace 3 trigger blocks with advisor calls | **Modify** |
| `nanobot/agent/__init__.py` | Export DelegationAdvisor | **Modify** |
| `nanobot/templates/prompts/plan.md` | Remove DELEGATION paragraph | **Modify** |
| `tests/test_delegation_advisor.py` | Comprehensive parametrized tests | **New** |
| `tests/test_coordinator.py` | Update for ClassificationResult | **Modify** |

---

### Task 1: Add `get_delegation_depth()` to delegation.py

**Files:**
- Modify: `nanobot/agent/delegation.py:60-63`
- Test: `tests/test_delegation_dispatcher.py`

- [ ] **Step 1: Write the failing test**

```python
# In tests/test_delegation_dispatcher.py — add at the end
from nanobot.agent.delegation import get_delegation_depth, _delegation_ancestry

class TestGetDelegationDepth:
    def test_depth_zero_at_top_level(self):
        assert get_delegation_depth() == 0

    def test_depth_reflects_ancestry(self):
        token = _delegation_ancestry.set(("code", "research"))
        try:
            assert get_delegation_depth() == 2
        finally:
            _delegation_ancestry.reset(token)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_delegation_dispatcher.py::TestGetDelegationDepth -v`
Expected: FAIL with `ImportError: cannot import name 'get_delegation_depth'`

- [ ] **Step 3: Write minimal implementation**

In `nanobot/agent/delegation.py`, after line 63 (after `_delegation_ancestry` definition):

```python
def get_delegation_depth() -> int:
    """Return the current delegation ancestry depth (0 = top-level agent)."""
    return len(_delegation_ancestry.get())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_delegation_dispatcher.py::TestGetDelegationDepth -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nanobot/agent/delegation.py tests/test_delegation_dispatcher.py
git commit -m "feat(delegation): add get_delegation_depth() public function"
```

---

### Task 2: Create DelegationAdvisor core module with data types

**Files:**
- Create: `nanobot/agent/delegation_advisor.py`
- Test: `tests/test_delegation_advisor.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_delegation_advisor.py`:

```python
"""Tests for DelegationAdvisor — unified delegation decision point."""
from __future__ import annotations

import pytest

from nanobot.agent.delegation_advisor import (
    DelegationAction,
    DelegationAdvice,
    DelegationAdvisor,
    RolePolicy,
)


class TestDataTypes:
    def test_delegation_action_values(self):
        assert DelegationAction.NONE == "none"
        assert DelegationAction.SOFT_NUDGE == "soft_nudge"
        assert DelegationAction.HARD_NUDGE == "hard_nudge"
        assert DelegationAction.HARD_GATE == "hard_gate"
        assert DelegationAction.SYNTHESIZE == "synthesize"

    def test_delegation_advice_defaults(self):
        advice = DelegationAdvice(action=DelegationAction.NONE, reason="test")
        assert advice.suggested_mode is None
        assert advice.remove_delegate_tools is False
        assert advice.suggested_roles is None
        assert advice.warn_ungrounded is False

    def test_role_policy_defaults(self):
        policy = RolePolicy()
        assert policy.solo_tool_threshold == 5
        assert policy.exempt_from_nudge is False

    def test_advisor_default_policies(self):
        advisor = DelegationAdvisor()
        # Known roles should have non-default thresholds
        assert advisor._get_policy("code").solo_tool_threshold == 10
        assert advisor._get_policy("pm").solo_tool_threshold == 3
        assert advisor._get_policy("unknown").solo_tool_threshold == 5  # default
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_delegation_advisor.py::TestDataTypes -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

Create `nanobot/agent/delegation_advisor.py`:

```python
"""Unified delegation decision point replacing three independent triggers.

Replaces:
- Classifier orchestration override (coordinator.py)
- Planning prompt delegation text (plan.md)
- Runtime counter nudge (loop.py:878-897)
- Budget exhaustion nudge (loop.py:835-844)

See docs/superpowers/specs/2026-03-21-delegation-advisor-design.md
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from loguru import logger

from nanobot.agent.delegation import get_delegation_depth


class DelegationAction(str, Enum):
    """Possible delegation advisory actions."""
    NONE = "none"
    SOFT_NUDGE = "soft_nudge"
    HARD_NUDGE = "hard_nudge"
    HARD_GATE = "hard_gate"
    SYNTHESIZE = "synthesize"


@dataclass(slots=True, frozen=True)
class DelegationAdvice:
    """Single coherent delegation signal for one evaluation point."""
    action: DelegationAction
    reason: str
    suggested_mode: str | None = None
    remove_delegate_tools: bool = False
    suggested_roles: list[str] | None = None
    warn_ungrounded: bool = False


@dataclass(slots=True, frozen=True)
class RolePolicy:
    """Per-role delegation behavior configuration."""
    solo_tool_threshold: int = 5
    exempt_from_nudge: bool = False


_DEFAULT_POLICIES: dict[str, RolePolicy] = {
    "pm": RolePolicy(solo_tool_threshold=3),
    "general": RolePolicy(solo_tool_threshold=5),
    "code": RolePolicy(solo_tool_threshold=10),
    "research": RolePolicy(solo_tool_threshold=8),
    "writing": RolePolicy(solo_tool_threshold=6),
}

_NONE_ADVICE = DelegationAdvice(action=DelegationAction.NONE, reason="no action needed")


class DelegationAdvisor:
    """Unified delegation decision point.

    Two-phase API:
    - advise_plan_phase: called once before the agent loop
    - advise_reflect_phase: called after each tool batch
    """

    def __init__(
        self,
        *,
        role_policies: dict[str, RolePolicy] | None = None,
        default_policy: RolePolicy | None = None,
    ) -> None:
        self._policies = {**_DEFAULT_POLICIES, **(role_policies or {})}
        self._default_policy = default_policy or RolePolicy()

    def _get_policy(self, role_name: str) -> RolePolicy:
        return self._policies.get(role_name, self._default_policy)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_delegation_advisor.py::TestDataTypes -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nanobot/agent/delegation_advisor.py tests/test_delegation_advisor.py
git commit -m "feat(delegation): add DelegationAdvisor core data types and constructor"
```

---

### Task 3: Implement `advise_plan_phase()`

**Files:**
- Modify: `nanobot/agent/delegation_advisor.py`
- Test: `tests/test_delegation_advisor.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_delegation_advisor.py`:

```python
from unittest.mock import patch


class TestAdvisePlanPhase:
    def _advise(self, advisor=None, **overrides):
        defaults = dict(
            role_name="general",
            needs_orchestration=False,
            relevant_roles=[],
            user_text="do something",
            delegate_tools_available=True,
        )
        defaults.update(overrides)
        return (advisor or DelegationAdvisor()).advise_plan_phase(**defaults)

    @patch("nanobot.agent.delegation_advisor.get_delegation_depth", return_value=0)
    def test_single_domain_returns_none(self, _mock):
        advice = self._advise(needs_orchestration=False, relevant_roles=["code"])
        assert advice.action == DelegationAction.NONE

    @patch("nanobot.agent.delegation_advisor.get_delegation_depth", return_value=0)
    def test_orchestration_needed_returns_soft_nudge(self, _mock):
        advice = self._advise(needs_orchestration=True, relevant_roles=["code", "research"])
        assert advice.action == DelegationAction.SOFT_NUDGE
        assert advice.suggested_roles == ["code", "research"]

    @patch("nanobot.agent.delegation_advisor.get_delegation_depth", return_value=0)
    def test_parallel_structure_suggests_parallel_mode(self, _mock):
        advice = self._advise(
            needs_orchestration=True,
            relevant_roles=["code", "research"],
            user_text="1. analyze code\n2. research alternatives\n3. write report",
        )
        assert advice.suggested_mode == "delegate_parallel"

    @patch("nanobot.agent.delegation_advisor.get_delegation_depth", return_value=1)
    def test_sub_agent_always_none(self, _mock):
        advice = self._advise(needs_orchestration=True, relevant_roles=["code", "pm"])
        assert advice.action == DelegationAction.NONE

    @patch("nanobot.agent.delegation_advisor.get_delegation_depth", return_value=0)
    def test_tools_unavailable_returns_none(self, _mock):
        advice = self._advise(delegate_tools_available=False, needs_orchestration=True)
        assert advice.action == DelegationAction.NONE

    @patch("nanobot.agent.delegation_advisor.get_delegation_depth", return_value=0)
    def test_two_relevant_roles_triggers_nudge(self, _mock):
        advice = self._advise(relevant_roles=["code", "research"])
        assert advice.action == DelegationAction.SOFT_NUDGE
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_delegation_advisor.py::TestAdvisePlanPhase -v`
Expected: FAIL with `AttributeError: 'DelegationAdvisor' object has no attribute 'advise_plan_phase'`

- [ ] **Step 3: Implement advise_plan_phase**

Add to `DelegationAdvisor` in `delegation_advisor.py`:

```python
    def advise_plan_phase(
        self,
        *,
        role_name: str,
        needs_orchestration: bool,
        relevant_roles: list[str],
        user_text: str,
        delegate_tools_available: bool,
    ) -> DelegationAdvice:
        """Called once before the agent loop starts."""
        if not delegate_tools_available:
            return _NONE_ADVICE

        if get_delegation_depth() > 0:
            return _NONE_ADVICE

        if needs_orchestration or len(relevant_roles) >= 2:
            from nanobot.agent.delegation import DelegationDispatcher

            if DelegationDispatcher.has_parallel_structure(user_text):
                return DelegationAdvice(
                    action=DelegationAction.SOFT_NUDGE,
                    reason="orchestration needed with parallel structure",
                    suggested_mode="delegate_parallel",
                    suggested_roles=relevant_roles or None,
                )
            return DelegationAdvice(
                action=DelegationAction.SOFT_NUDGE,
                reason="orchestration needed",
                suggested_mode="delegate",
                suggested_roles=relevant_roles or None,
            )

        return _NONE_ADVICE
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_delegation_advisor.py::TestAdvisePlanPhase -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add nanobot/agent/delegation_advisor.py tests/test_delegation_advisor.py
git commit -m "feat(delegation): implement advise_plan_phase() on DelegationAdvisor"
```

---

### Task 4: Implement `advise_reflect_phase()`

**Files:**
- Modify: `nanobot/agent/delegation_advisor.py`
- Test: `tests/test_delegation_advisor.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_delegation_advisor.py`:

```python
class TestAdviseReflectPhase:
    def _advise(self, advisor=None, **overrides):
        defaults = dict(
            role_name="general",
            turn_tool_calls=0,
            delegation_count=0,
            max_delegations=8,
            had_delegations_this_batch=False,
            used_sequential_delegate=False,
            has_parallel_structure=False,
            any_ungrounded=False,
            any_failed=False,
            iteration=1,
            previous_advice=None,
        )
        defaults.update(overrides)
        return (advisor or DelegationAdvisor()).advise_reflect_phase(**defaults)

    @patch("nanobot.agent.delegation_advisor.get_delegation_depth", return_value=1)
    def test_delegated_agent_always_none(self, _mock):
        advice = self._advise(turn_tool_calls=20)
        assert advice.action == DelegationAction.NONE

    @patch("nanobot.agent.delegation_advisor.get_delegation_depth", return_value=0)
    def test_budget_exhausted_hard_gate(self, _mock):
        advice = self._advise(delegation_count=8, max_delegations=8)
        assert advice.action == DelegationAction.HARD_GATE
        assert advice.remove_delegate_tools is True

    @patch("nanobot.agent.delegation_advisor.get_delegation_depth", return_value=0)
    def test_failures_take_priority(self, _mock):
        advice = self._advise(any_failed=True, turn_tool_calls=10)
        assert advice.action == DelegationAction.NONE

    @patch("nanobot.agent.delegation_advisor.get_delegation_depth", return_value=0)
    def test_had_delegations_ungrounded_warns(self, _mock):
        advice = self._advise(had_delegations_this_batch=True, any_ungrounded=True)
        assert advice.action == DelegationAction.SYNTHESIZE
        assert advice.warn_ungrounded is True

    @patch("nanobot.agent.delegation_advisor.get_delegation_depth", return_value=0)
    def test_had_delegations_budget_full_synthesize(self, _mock):
        advice = self._advise(
            had_delegations_this_batch=True, delegation_count=8, max_delegations=8
        )
        assert advice.action == DelegationAction.SYNTHESIZE
        assert advice.remove_delegate_tools is True

    @patch("nanobot.agent.delegation_advisor.get_delegation_depth", return_value=0)
    def test_sequential_with_parallel_structure_nudges(self, _mock):
        advice = self._advise(
            had_delegations_this_batch=True,
            used_sequential_delegate=True,
            has_parallel_structure=True,
        )
        assert advice.action == DelegationAction.SOFT_NUDGE
        assert advice.suggested_mode == "delegate_parallel"

    @patch("nanobot.agent.delegation_advisor.get_delegation_depth", return_value=0)
    def test_code_role_high_threshold(self, _mock):
        advice = self._advise(role_name="code", turn_tool_calls=7)
        assert advice.action == DelegationAction.NONE  # threshold is 10

    @patch("nanobot.agent.delegation_advisor.get_delegation_depth", return_value=0)
    def test_general_role_threshold_soft_nudge(self, _mock):
        advice = self._advise(role_name="general", turn_tool_calls=6)
        assert advice.action == DelegationAction.SOFT_NUDGE

    @patch("nanobot.agent.delegation_advisor.get_delegation_depth", return_value=0)
    def test_escalation_soft_to_hard(self, _mock):
        advice = self._advise(
            role_name="general",
            turn_tool_calls=6,
            previous_advice=DelegationAction.SOFT_NUDGE,
        )
        assert advice.action == DelegationAction.HARD_NUDGE

    @patch("nanobot.agent.delegation_advisor.get_delegation_depth", return_value=0)
    def test_exempt_role_never_nudged(self, _mock):
        advisor = DelegationAdvisor(
            role_policies={"specialist": RolePolicy(exempt_from_nudge=True)}
        )
        advice = self._advise(advisor=advisor, role_name="specialist", turn_tool_calls=20)
        assert advice.action == DelegationAction.NONE
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_delegation_advisor.py::TestAdviseReflectPhase -v`
Expected: FAIL

- [ ] **Step 3: Implement advise_reflect_phase**

Add to `DelegationAdvisor` in `delegation_advisor.py`:

```python
    def advise_reflect_phase(
        self,
        *,
        role_name: str,
        turn_tool_calls: int,
        delegation_count: int,
        max_delegations: int,
        had_delegations_this_batch: bool,
        used_sequential_delegate: bool,
        has_parallel_structure: bool,
        any_ungrounded: bool,
        any_failed: bool,
        iteration: int,
        previous_advice: DelegationAction | None = None,
    ) -> DelegationAdvice:
        """Called after each tool batch in the reflect phase."""
        if get_delegation_depth() > 0:
            return _NONE_ADVICE

        if any_failed:
            return _NONE_ADVICE

        if had_delegations_this_batch:
            advice: DelegationAdvice
            if any_ungrounded:
                advice = DelegationAdvice(
                    action=DelegationAction.SYNTHESIZE,
                    warn_ungrounded=True,
                    reason="delegation complete, ungrounded results detected",
                )
            elif delegation_count >= max_delegations:
                advice = DelegationAdvice(
                    action=DelegationAction.SYNTHESIZE,
                    remove_delegate_tools=True,
                    reason="budget exhausted after delegation batch",
                )
            else:
                advice = _NONE_ADVICE

            if used_sequential_delegate and has_parallel_structure:
                advice = DelegationAdvice(
                    action=DelegationAction.SOFT_NUDGE,
                    suggested_mode="delegate_parallel",
                    reason="parallel structure detected, switch to delegate_parallel",
                )

            return advice

        if delegation_count >= max_delegations:
            return DelegationAdvice(
                action=DelegationAction.HARD_GATE,
                remove_delegate_tools=True,
                reason="delegation budget exhausted",
            )

        policy = self._get_policy(role_name)
        if policy.exempt_from_nudge:
            return _NONE_ADVICE

        if turn_tool_calls >= policy.solo_tool_threshold:
            if previous_advice == DelegationAction.SOFT_NUDGE:
                return DelegationAdvice(
                    action=DelegationAction.HARD_NUDGE,
                    reason=f"escalation: {turn_tool_calls} solo calls, soft nudge was ignored",
                )
            return DelegationAdvice(
                action=DelegationAction.SOFT_NUDGE,
                reason=f"{turn_tool_calls} solo calls without delegation",
            )

        return _NONE_ADVICE
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_delegation_advisor.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run lint + typecheck**

Run: `make lint && make typecheck`

- [ ] **Step 6: Commit**

```bash
git add nanobot/agent/delegation_advisor.py tests/test_delegation_advisor.py
git commit -m "feat(delegation): implement advise_reflect_phase() with escalation + budget gating"
```

---

### Task 5: Update coordinator.py to return ClassificationResult

**Files:**
- Modify: `nanobot/agent/coordinator.py`
- Test: `tests/test_coordinator.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_coordinator.py`:

```python
from nanobot.agent.coordinator import ClassificationResult

class TestClassificationResult:
    def test_result_has_orchestration_fields(self):
        result = ClassificationResult(
            role_name="code", confidence=0.9,
            needs_orchestration=True, relevant_roles=["code", "research"],
        )
        assert result.role_name == "code"
        assert result.needs_orchestration is True
        assert result.relevant_roles == ["code", "research"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_coordinator.py::TestClassificationResult -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement ClassificationResult and update classify()**

In `coordinator.py`, add the dataclass and change `classify()` return type:

```python
@dataclass(slots=True, frozen=True)
class ClassificationResult:
    """Result from intent classification with orchestration signals."""
    role_name: str
    confidence: float
    needs_orchestration: bool = False
    relevant_roles: list[str] = field(default_factory=list)
```

Update `classify()`:
- Change return type from `tuple[str, float]` to `ClassificationResult`
- Change all `return role_name, confidence` to `return ClassificationResult(role_name=role_name, confidence=confidence, needs_orchestration=needs_orchestration, relevant_roles=relevant_roles)`
- Update the cache to store/return `ClassificationResult`

- [ ] **Step 4: Update ALL callers of classify()**

Search the codebase for `classify(` calls. Each caller currently unpacks `(role_name, confidence)`. Update to use `.role_name` and `.confidence` attributes.

**Production callers:**
- `loop.py` in `run()`: `role_name, confidence = await self._coordinator.classify(...)` → `result = await self._coordinator.classify(...)` then `result.role_name`, `result.confidence`
- `loop.py` in `process_direct()`: same pattern
- `coordinator.py` in `route()` (~line 322): `role_name, _confidence = await self.classify(message)` → `result = await self.classify(message)` then `result.role_name`

**Cache update in coordinator.py:**
- Cache-hit early return: update to store/return `ClassificationResult` instead of `(role_name, confidence)` tuple
- Cache-store: `self._classify_cache[cache_key] = result` (the full ClassificationResult)

**Test callers (~20 sites in `tests/test_coordinator.py`):**
- Every `role, conf = await coordinator.classify(...)` must become `result = await coordinator.classify(...)` then `result.role_name`, `result.confidence`
- Grep: `grep -n "classify(" tests/test_coordinator.py` to find all sites

- [ ] **Step 5: Run all tests**

Run: `make check`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add nanobot/agent/coordinator.py nanobot/agent/loop.py tests/test_coordinator.py
git commit -m "refactor(coordinator): return ClassificationResult with orchestration signals"
```

---

### Task 6: Wire DelegationAdvisor into loop.py

**Files:**
- Modify: `nanobot/agent/loop.py`
- Modify: `nanobot/agent/__init__.py`

This is the largest task — it replaces 3 trigger blocks with advisor calls.

- [ ] **Step 1: Construct advisor in `__init__`**

In `loop.py` `__init__`, after the dispatcher construction:

```python
from nanobot.agent.delegation_advisor import DelegationAdvisor
self._delegation_advisor = DelegationAdvisor()
self._last_classification_result: ClassificationResult | None = None
```

Import `ClassificationResult` from coordinator at the top of the file.

- [ ] **Step 2: Store classification result in `run()` and `process_direct()`**

In `run()`, after calling `classify()`:
```python
result = await self._coordinator.classify(msg.content)
self._last_classification_result = result
role_name = result.role_name
confidence = result.confidence
```

In `process_direct()`, set `self._last_classification_result = None` (no classification for direct calls).

- [ ] **Step 3: Replace plan-phase delegation injection**

In `_run_agent_loop()`, find the planning block (~lines 970-990). Replace the parallel structure nudge with advisor call:

```python
if has_plan:
    cr = self._last_classification_result
    plan_advice = self._delegation_advisor.advise_plan_phase(
        role_name=self.role_name,
        needs_orchestration=cr.needs_orchestration if cr else False,
        relevant_roles=cr.relevant_roles if cr else [],
        user_text=user_text,
        delegate_tools_available=bool(self.tools.get("delegate_parallel")),
    )
    if plan_advice.action != DelegationAction.NONE:
        messages.append({"role": "system", "content": prompts.get("nudge_parallel_structure")})
        logger.debug("Delegation advisor plan-phase: {}", plan_advice.reason)
```

Remove the existing `DelegationDispatcher.has_parallel_structure(user_text)` call and its nudge injection (the advisor handles this internally).

- [ ] **Step 4: Replace COMPLETE `_evaluate_progress()` delegation chain**

The current if-elif chain in `_evaluate_progress()` mixes delegation logic with failure handling and progress nudges. Replace the delegation branches but PRESERVE the non-delegation branches.

**Complete replacement structure:**

```python
had_delegations = any(tc.name in _DELEGATION_TOOL_NAMES for tc in response.tool_calls)

# --- Delegation advisor (replaces 3 independent triggers) ---
delegation_advice = self._delegation_advisor.advise_reflect_phase(
    role_name=self.role_name,
    turn_tool_calls=turn_tool_calls,
    delegation_count=self._dispatcher.delegation_count,
    max_delegations=self._dispatcher.max_delegations,
    had_delegations_this_batch=had_delegations,
    used_sequential_delegate=had_delegations and not any(
        tc.name == "delegate_parallel" for tc in response.tool_calls
    ),
    has_parallel_structure=DelegationDispatcher.has_parallel_structure(user_text),
    any_ungrounded=any(
        "grounded=False" in (m.get("content") or "")
        for m in messages[-len(response.tool_calls):]
        if m.get("role") == "tool"
    ),
    any_failed=any_failed,
    iteration=iteration,
    previous_advice=_last_delegation_advice,
)
_last_delegation_advice = delegation_advice.action

# --- Render delegation advice OR fall through to other nudges ---
if delegation_advice.action == DelegationAction.HARD_GATE:
    messages.append({"role": "system", "content": prompts.get("nudge_delegation_exhausted")})
elif delegation_advice.action == DelegationAction.SYNTHESIZE:
    nudge = prompts.get("nudge_post_delegation")
    if delegation_advice.warn_ungrounded:
        nudge += "\n\n" + prompts.get("nudge_ungrounded_warning")
    messages.append({"role": "system", "content": nudge})
elif delegation_advice.action in (DelegationAction.SOFT_NUDGE, DelegationAction.HARD_NUDGE):
    if delegation_advice.suggested_mode == "delegate_parallel":
        messages.append({"role": "system", "content": prompts.get("nudge_use_parallel")})
    else:
        messages.append({"role": "system", "content": delegation_advice.reason})
elif any_failed:
    # PRESERVED: failure handling (advisor returns NONE when any_failed=True)
    _permanent = tracker.permanent_failures
    _available = [
        t["function"]["name"]
        for t in _tools_def_cache
        if t["function"]["name"] not in _permanent
    ]
    messages.append(
        {"role": "system", "content": _build_failure_prompt(failed_this_batch, _permanent, _available)}
    )
elif has_plan and len(response.tool_calls) >= 1:
    # PRESERVED: progress nudge (not delegation-related)
    messages.append({"role": "system", "content": prompts.get("progress")})
elif len(response.tool_calls) >= 3:
    # PRESERVED: reflect nudge (not delegation-related)
    messages.append({"role": "system", "content": prompts.get("reflect")})
```

**What was removed:** The old budget-exhaustion block, post-delegation block, and runtime-counter block. These are now handled by the advisor.

**What was preserved:** Failure handling, progress nudge, reflect nudge — all non-delegation branches.

**Behavioral note:** When `any_failed=True` AND budget is exhausted, the advisor returns NONE (failures take priority), so the failure branch fires. Previously, budget exhaustion would take priority. This is an improvement — tool failures should always be addressed first.

- [ ] **Step 5: Track `_last_delegation_advice` as loop state**

Initialize `_last_delegation_advice = None` alongside other loop state (near `nudged_for_final`).

- [ ] **Step 6: Handle `remove_delegate_tools` flag**

When `delegation_advice.remove_delegate_tools is True`, filter delegate tools from `_tools_def_cache` for the next iteration:

```python
if delegation_advice.remove_delegate_tools:
    active_tools = [t for t in _tools_def_cache if t["function"]["name"] not in _DELEGATION_TOOL_NAMES]
```

- [ ] **Step 6: Update `__init__.py` exports**

In `nanobot/agent/__init__.py`, add `DelegationAdvisor` to imports and `__all__`.

- [ ] **Step 7: Run all tests**

Run: `make check`
Expected: ALL PASS

- [ ] **Step 8: Commit**

```bash
git add nanobot/agent/loop.py nanobot/agent/__init__.py nanobot/agent/delegation_advisor.py
git commit -m "refactor(loop): wire DelegationAdvisor, replace 3 trigger blocks"
```

---

### Task 7: Remove delegation paragraph from plan.md

**Files:**
- Modify: `nanobot/templates/prompts/plan.md`

- [ ] **Step 1: Remove the DELEGATION paragraph**

Remove lines 3-8 from `plan.md` (the DELEGATION and TWO-PHASE RULE paragraphs). Keep line 1 (the planning instruction).

The advisor now controls when delegation advice is injected. The TWO-PHASE RULE content is already in the `pm` role's system prompt.

- [ ] **Step 2: Run prompt manifest check**

Run: `make prompt-check`
If it fails, run: `python3 scripts/check_prompt_manifest.py --update`

- [ ] **Step 3: Run all tests**

Run: `make check`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add nanobot/templates/prompts/plan.md prompts_manifest.json
git commit -m "refactor(prompts): remove delegation paragraph from plan.md — advisor controls injection"
```

---

### Task 8: Add missing test cases

**Files:**
- Modify: `tests/test_delegation_advisor.py`

- [ ] **Step 1: Add test for delegation-in-progress NONE branch**

```python
    @patch("nanobot.agent.delegation_advisor.get_delegation_depth", return_value=0)
    def test_had_delegations_no_special_conditions_none(self, _mock):
        """Delegation in progress, no budget/ungrounded/parallel issues → NONE."""
        advice = self._advise(had_delegations_this_batch=True)
        assert advice.action == DelegationAction.NONE
```

- [ ] **Step 2: Add test for orchestration without relevant_roles**

```python
    @patch("nanobot.agent.delegation_advisor.get_delegation_depth", return_value=0)
    def test_orchestration_true_empty_roles_still_nudges(self, _mock):
        advice = self._advise(needs_orchestration=True, relevant_roles=[])
        assert advice.action == DelegationAction.SOFT_NUDGE
```

- [ ] **Step 3: Run all tests**

Run: `pytest tests/test_delegation_advisor.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_delegation_advisor.py
git commit -m "test: add missing delegation advisor test cases for NONE and empty-roles branches"
```

---

### Task 9: Final validation and cleanup

**Files:**
- All changed files

- [ ] **Step 1: Run full check suite**

```bash
make check
```

Expected: ALL PASS (lint, typecheck, import-check, prompt-check, tests)

- [ ] **Step 2: Verify no remaining hardcoded delegation nudges in loop.py**

```bash
grep -n "STOP doing the work\|delegate_parallel.*NOW\|solo without delegating" nanobot/agent/loop.py
```

Expected: No matches

- [ ] **Step 3: Verify advisor is the single delegation decision point**

```bash
grep -n "turn_tool_calls >= 5\|turn_tool_calls >= [0-9]" nanobot/agent/loop.py
```

Expected: No matches (thresholds are now in RolePolicy)

- [ ] **Step 4: Commit any final cleanup**

```bash
git add -A
git commit -m "chore: final cleanup after DelegationAdvisor integration"
```
