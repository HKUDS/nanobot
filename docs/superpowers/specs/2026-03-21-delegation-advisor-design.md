# DelegationAdvisor Design Spec

**Date:** 2026-03-21
**Status:** Approved
**Related:** `docs/contradiction-5-delegation-triggers.md`

## Problem

Three independent mechanisms decide whether the agent should delegate, with no
priority ordering or mutual awareness:

1. **Classifier** (pre-turn): emits `needs_orchestration` and `relevant_roles`,
   overrides routing to `pm` role
2. **Planner** (start-of-turn): always says "prefer delegation" via `plan.md`
3. **Runtime counter** (mid-turn): fires "STOP, delegate NOW" after 5 solo tool
   calls regardless of task complexity

These contradict each other, produce false-positive delegation pressure on simple
tasks, and can conflict with the delegation budget exhaustion nudge.

## Solution

Replace all three triggers with a single `DelegationAdvisor` class that receives
all available signals and produces one coherent decision.

**Approach:** Hybrid — soft advisory for normal cases (the LLM decides whether to
delegate based on coherent advice), hard gate for boundary conditions (budget
exhausted = tools removed, delegation impossible).

## Architecture

### Module

New file: `nanobot/agent/delegation_advisor.py`

Follows the established extraction pattern (TurnRoleManager, AnswerVerifier,
ToolRegistrationService) — a focused single-responsibility module constructed in
`AgentLoop.__init__` and called from the loop.

### Data Types

```python
class DelegationAction(str, Enum):
    NONE = "none"               # No injection needed
    SOFT_NUDGE = "soft_nudge"   # "Consider delegating..."
    HARD_NUDGE = "hard_nudge"   # "You should delegate now..."
    HARD_GATE = "hard_gate"     # Remove delegate tools entirely
    SYNTHESIZE = "synthesize"   # "Stop delegating, synthesize results"

@dataclass(slots=True, frozen=True)
class DelegationAdvice:
    action: DelegationAction
    reason: str                              # For logging/tracing
    suggested_mode: str | None = None        # "delegate_parallel" | "delegate" | None
    remove_delegate_tools: bool = False      # Hard gate flag
    suggested_roles: list[str] | None = None # Which roles to suggest
    warn_ungrounded: bool = False            # Suggest cross-checking results

@dataclass(slots=True, frozen=True)
class RolePolicy:
    solo_tool_threshold: int = 5       # Tool calls before solo-work nudge fires
    delegation_affinity: float = 0.5   # 0.0 = never suggest, 1.0 = always suggest
    can_sub_delegate: bool = True      # False for leaf specialists
    exempt_from_nudge: bool = False    # True = never inject delegation nudges
```

### DelegationAdvisor API

```python
class DelegationAdvisor:
    def __init__(
        self,
        *,
        role_policies: dict[str, RolePolicy] | None = None,
        default_policy: RolePolicy | None = None,
    ) -> None:
        ...

    def advise_plan_phase(
        self,
        *,
        role_name: str,
        needs_orchestration: bool,
        relevant_roles: list[str],
        user_text: str,
        delegate_tools_available: bool,
    ) -> DelegationAdvice:
        """Called once before the agent loop starts.

        Determines whether the planning prompt should mention delegation
        and whether to inject the parallel-structure nudge. Replaces the
        unconditional plan.md delegation text and the duplicated
        has_parallel_structure() calls in loop.py.
        """

    def advise_reflect_phase(
        self,
        *,
        role_name: str,
        turn_tool_calls: int,
        delegation_count: int,
        max_delegations: int,
        had_delegations_this_batch: bool,
        any_failed: bool,
        iteration: int,
        delegation_depth: int,
        previous_advice: DelegationAction | None = None,
    ) -> DelegationAdvice:
        """Called after each tool batch in the reflect phase.

        Evaluates all runtime signals and returns a single coherent
        advisory. Replaces the runtime counter nudge (loop.py:899-917),
        the budget exhaustion nudge (loop.py:835-849), and the
        delegation-complete synthesis nudge.
        """
```

### Two-Phase Design Rationale

The plan phase and reflect phase have fundamentally different inputs:

- **Plan phase** has: user text, classifier output, role name — no runtime state
- **Reflect phase** has: tool call counts, delegation counts, failures, iteration —
  no user text needed

A single `advise()` method would force callers to pass zeros/None for signals that
don't exist yet at the plan phase, which is a code smell indicating mismatched
abstraction.

## Decision Logic

### Plan Phase

```
if not delegate_tools_available:
    return NONE

if delegation_depth > 0:
    return NONE  # sub-agents don't get delegation advice

if needs_orchestration or len(relevant_roles) >= 2:
    if has_parallel_structure(user_text):
        return SOFT_NUDGE(suggested_mode="delegate_parallel", suggested_roles=relevant_roles)
    else:
        return SOFT_NUDGE(suggested_mode="delegate")

return NONE  # single-domain task, no delegation suggestion
```

### Reflect Phase

```
if delegation_count >= max_delegations:
    return HARD_GATE(remove_delegate_tools=True, reason="budget exhausted")

if delegation_depth > 0:
    return NONE  # delegated agents never get nudges

if any_failed:
    return NONE  # let failure handling take priority

if had_delegations_this_batch:
    if delegation_count >= max_delegations:
        return SYNTHESIZE(remove_delegate_tools=True)
    else:
        return NONE  # delegation happening, don't interfere

policy = get_policy(role_name)
if policy.exempt_from_nudge:
    return NONE

if turn_tool_calls >= policy.solo_tool_threshold:
    if previous_advice == SOFT_NUDGE:
        return HARD_NUDGE(reason="escalation: soft nudge was ignored")
    else:
        return SOFT_NUDGE(reason=f"{turn_tool_calls} solo calls, consider delegating")

return NONE
```

### Escalation

The `previous_advice` parameter enables escalation:
- First time threshold is hit: `SOFT_NUDGE` ("Consider delegating...")
- Threshold hit again after soft nudge was ignored: `HARD_NUDGE` ("You should delegate now...")
- Hard nudge is the maximum escalation — the advisor never forces delegation in normal operation

The caller tracks `previous_advice` as loop state (same pattern as existing
`nudged_for_final` at loop.py:951).

## Default Role Policies

| Role | solo_tool_threshold | delegation_affinity | can_sub_delegate | exempt_from_nudge |
|------|--------------------:|--------------------:|-----------------:|------------------:|
| pm | 3 | 0.8 | true | false |
| general | 5 | 0.5 | true | false |
| code | 10 | 0.2 | false | false |
| research | 8 | 0.3 | false | false |
| writing | 6 | 0.3 | false | false |

These are defaults. Users can override via `AgentRoleConfig` in their config file.

## Integration with loop.py

### What gets removed from loop.py

1. **Lines 899-917**: Runtime counter nudge (`turn_tool_calls >= 5` block) — replaced
   by `advise_reflect_phase()`
2. **Lines 835-849**: Budget exhaustion nudge — replaced by `advise_reflect_phase()`
   returning `HARD_GATE`
3. **Lines 991-1016**: Plan phase delegation injection (plan.md delegation text +
   parallel structure nudge) — replaced by `advise_plan_phase()`
4. **Two calls to `DelegationDispatcher.has_parallel_structure()`** — moved inside
   the advisor

### What stays in loop.py

- `_evaluate_progress()` calls `advisor.advise_reflect_phase()` and renders the
  returned `DelegationAdvice` into a system message
- `_run_agent_loop()` calls `advisor.advise_plan_phase()` before the loop and
  conditionally injects the advice
- The delegation budget hard cap in `DelegationDispatcher.dispatch()` stays as
  defense-in-depth (raises `_CycleError`)

### What changes in coordinator.py

The classifier override logic (lines 264-282) stays in `coordinator.py`. But
`classify()` must now return `needs_orchestration` and `relevant_roles` to the
caller (loop.py) instead of consuming them internally. Currently loop.py only
receives `(role_name, confidence)` — it needs the full classifier output to pass
to the advisor.

Update `classify()` return type:
```python
# Before:
async def classify(self, message: str) -> tuple[str, float]:

# After:
@dataclass(slots=True, frozen=True)
class ClassificationResult:
    role_name: str
    confidence: float
    needs_orchestration: bool = False
    relevant_roles: list[str] = field(default_factory=list)

async def classify(self, message: str) -> ClassificationResult:
```

### What changes in prompts

- `plan.md`: Remove the "DELEGATION: ..." paragraph. The advisor now controls
  whether delegation advice is injected, and produces its own text.
- `classify.md`: No changes — the classifier still produces the same fields.

## Testing Strategy

### Unit tests (no AgentLoop needed)

```python
class TestPlanPhase:
    # Single-domain task → NONE
    # needs_orchestration=True → SOFT_NUDGE
    # parallel structure detected → suggested_mode="delegate_parallel"
    # delegation_depth > 0 → always NONE
    # delegate_tools_available=False → always NONE

class TestReflectPhase:
    # Budget exhausted → HARD_GATE + remove_delegate_tools
    # Delegated agent → always NONE regardless of tool count
    # Code role, 7 tool calls → NONE (threshold is 10)
    # General role, 6 tool calls → SOFT_NUDGE
    # Previous soft nudge ignored → escalate to HARD_NUDGE
    # Tools failing → NONE (let failure handling take priority)
    # Had delegations this batch → NONE (delegation in progress)

class TestRolePolicy:
    # Default policies match table above
    # Custom policy overrides defaults
    # Unknown role gets default policy
```

Use `@pytest.mark.parametrize` tables consistent with existing test patterns.

## Migration

- Existing behavior is preserved at the decision level — the same conditions that
  triggered delegation still trigger it, but through one coherent path
- The `plan.md` delegation text removal is the only user-visible change — the plan
  prompt becomes shorter and more focused on planning, not delegation
- No config file changes required — `RolePolicy` defaults match current hardcoded
  thresholds
- The classifier return type change is internal — no external API affected

## Risks

- **Regression in delegation frequency**: The advisor may produce different
  delegation rates than the three independent triggers combined. Monitor via
  routing traces and delegation metrics.
- **Classifier output threading**: Passing `needs_orchestration` and
  `relevant_roles` through loop.py to the advisor requires changing the
  `classify()` return type. This is a clean change but touches coordinator.py.
- **Role policy tuning**: The default thresholds are estimates. May need adjustment
  based on real-world agent traces.

## Files Affected

| File | Change |
|------|--------|
| `nanobot/agent/delegation_advisor.py` | New — DelegationAdvisor, DelegationAdvice, RolePolicy |
| `nanobot/agent/loop.py` | Remove 3 trigger blocks, add advisor calls |
| `nanobot/agent/coordinator.py` | Return ClassificationResult instead of tuple |
| `nanobot/templates/prompts/plan.md` | Remove delegation paragraph |
| `nanobot/config/schema.py` | Add RolePolicy to AgentRoleConfig (optional) |
| `tests/test_delegation_advisor.py` | New — comprehensive parametrized tests |
| `tests/test_coordinator.py` | Update for ClassificationResult return type |
