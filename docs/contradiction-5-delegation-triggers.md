# Contradiction 5: Three Independent Delegation Triggers

**Date:** 2026-03-21
**Status:** Open — needs further analysis
**Related:** Prompt consolidation work (2026-03-21)

## Problem

Three separate mechanisms independently decide whether the agent should delegate,
with no priority ordering or mutual awareness:

### Trigger 1: Classifier (pre-turn)

- **Where:** `classify.md` prompt, consumed by `Coordinator.classify()`
- **When:** Before the turn starts, during intent routing
- **What it does:** Emits `needs_orchestration: true/false` and `relevant_roles`.
  When true, routes to the `pm` role whose system prompt contains the full
  orchestration pattern (gather → synthesize via `delegate_parallel`).
- **Signal strength:** Advisory — low-confidence classifications fall back to
  `default_role` via `confidence_threshold`.

### Trigger 2: Planner (start-of-turn)

- **Where:** `plan.md` prompt, injected by `_run_agent_loop()` when
  `planning_enabled=True`
- **When:** First iteration of each turn
- **What it says:** "Prefer delegation over doing everything yourself when the
  request spans multiple domains."
- **Signal strength:** Suggestive ("prefer") but always present when planning is on,
  regardless of what the classifier decided.

### Trigger 3: Runtime counter (mid-turn)

- **Where:** Inline nudge in `loop.py:912-918`
- **When:** After ≥5 solo tool calls without any delegation
- **What it says:** "STOP doing the work yourself. Use `delegate_parallel` NOW ...
  This is required for multi-part tasks."
- **Signal strength:** Imperative ("STOP", "NOW", "required"). No qualifying
  conditions beyond the raw call count.

## Observed Problems

### 1. False-positive delegation pressure

A simple task like "read this file and summarize it" doesn't need delegation.
But if the agent makes 5 tool calls (read_file, list_dir, read_file, exec,
read_file), the runtime counter fires and demands delegation for a task the
agent was handling fine solo.

### 2. Contradictory signals within a single turn

If the classifier routes to the `code` role (not `pm`), the agent doesn't get
the orchestration pattern prompt. But `plan.md` still says "prefer delegation."
And the runtime counter can still force it. A `code` agent doing focused
single-domain engineering work gets interrupted mid-flow.

### 3. No escape hatch

None of the three mechanisms has a "this task is simple, don't delegate"
override. The runtime counter is purely mechanical — ≥5 calls triggers it
regardless of whether delegation would help.

### 4. Conflict with delegation budget exhaustion

When the delegation budget is exhausted, the budget-exhausted nudge says
"Do NOT delegate any more work." But the runtime counter can fire simultaneously,
saying "Use `delegate_parallel` NOW ... This is required." The agent receives
both absolute instructions in the same context window.

## Potential Solutions (Not Yet Evaluated)

### A. Prompt-only: Soften absolute language

Add qualifying clauses to `plan.md` and the runtime counter nudge:
"Prefer delegation when the request involves multiple independent sub-tasks
across different domains. For focused single-domain work, solo execution is fine."

- **Pro:** Minimal change, no code modifications
- **Con:** Doesn't fix the architectural layering issue

### B. Make runtime counter context-aware

Only fire the solo-call nudge if the plan contains multiple independent steps
or the classifier flagged orchestration. Skip it for single-domain tasks.

- **Pro:** Eliminates false positives
- **Con:** Requires passing classifier/plan state into the counter logic

### C. Raise the threshold or make it configurable

Change the ≥5 threshold to ≥8-10, or make it a config parameter
(`delegation_nudge_threshold` in `AgentConfig`).

- **Pro:** Simple code change, reduces false positives
- **Con:** Doesn't eliminate them entirely, just makes them less frequent

### D. Unify into a single delegation decision point

Replace the three triggers with a single `DelegationAdvisor` that receives
the classifier output, the plan, and the runtime tool-call count, and makes
one coherent decision.

- **Pro:** Clean architecture, eliminates contradictions entirely
- **Con:** Largest engineering effort, needs careful design

## Next Steps

- [ ] Analyze agent traces to quantify how often false-positive delegation occurs
- [ ] Evaluate which solution (A-D) best fits the project's complexity budget
- [ ] If solution D, write a separate spec for `DelegationAdvisor`
