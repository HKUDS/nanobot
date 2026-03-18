# Agent Intelligence Layers — Planning Document

> Architectural improvements to the agent's capability selection, action validation,
> and failure recovery. All four layers are now complete.

## Overview

| Layer | Name | Purpose | Status |
|-------|------|---------|--------|
| 1 | **Capability Registry** | Unified registry with availability checks | ✅ Complete |
| 2 | **Intent-to-Capability Routing** | Semantic skill activation + role classification | ✅ Complete |
| 3 | **Action Boundary Validation** | Pre-dispatch role validation | ✅ Complete |
| 4 | **Failure-Aware Replanning** | Structured recovery after failed actions | ✅ Complete |

---

## Layer 1: Capability Registry ✅

**ADR**: [ADR-009](adr/ADR-009-capability-registry.md)

`CapabilityRegistry` (`nanobot/agent/capability.py`) composes `ToolRegistry`,
`SkillsLoader`, and `AgentRegistry` behind a single facade that tracks availability,
health, and metadata. The LLM only sees capabilities that are configured, installed,
and healthy.

**Key APIs**:
- `register_tool/skill/role()` — unified registration with intent tags and fallback priority
- `get_available(kind=, intent=)` — filter by health, kind, and/or intent
- `refresh_health()` — re-checks availability and returns structured `HealthRefreshResult`
- `get_unavailable_summary()` — human-readable list of what is missing and why

---

## Layer 2: Intent-to-Capability Routing ✅

**Original plan**: Build an `IntentRouter` with a verb-based routing table, a separate
LLM intent classification pass, and a pre-planning routing step before every LLM call.

**What was built instead**: The same goal was achieved with less complexity.

- **Skill activation** (`nanobot/agent/skills.py` — `detect_relevant_skills()`): Two-pass
  matching — exact trigger phrases first, then stemmed description-keyword scoring with
  `max(precision, recall)` to avoid bias against long descriptions. Activated before every
  LLM call and loaded into the system prompt.
- **Role classification** (`nanobot/agent/coordinator.py` — `Coordinator.classify()`):
  LLM-based routing to specialised roles with multi-agent orchestration detection
  (`needs_orchestration` / `relevant_roles` ≥ 2 → auto-route to PM role).
- **Delegation validation** (Phase D, `nanobot/agent/tools/delegate.py`): Both
  `DelegateTool` and `DelegateParallelTool` validate `target_role` upfront against
  `CapabilityRegistry.role_names()` and return a structured error listing available roles.

**Dropped**: `intent.py` (verb routing table), pre-planning routing pass, and extending
`Coordinator.classify()` to return intent labels. The description-based skill matching
covers the semantic routing need without a rigid verb table.

---

## Layer 3: Action Boundary Validation ✅

**Original plan**: A full `ActionValidator` class with a pre-execution validation gate
for all tool calls.

**What was built**: Targeted validation at the two highest-value intercept points.

- **Delegation pre-validation** (Phase D): Unknown roles are caught before dispatch,
  not after a wasted tool turn. Error includes the list of configured roles.
- **`UnknownRoleError`** (`nanobot/errors.py`): Typed exception for programmatic
  handling, with `error_type="unknown_role"` — picked up by `FailureClass.classify_failure()`
  in Layer 4 as `PERMANENT_CONFIG`.

**Dropped**: `validator.py`, pre-execution validation for every tool call, and
`ActionValidationError`. The existing `ToolRegistry` parameter validation at execution
time plus Layer 4 failure classification handles the remaining cases without a dedicated
pre-execution gate.

---

## Layer 4: Failure-Aware Replanning ✅

**Original plan**: A `ReplanningPolicy` class in `replanner.py` with `FailureClass`,
`ReplanBudget`, and `FailureTracker` replacing `ToolCallTracker`.

**What was built**: The same semantics integrated directly into `ToolCallTracker`
(`nanobot/agent/loop.py`).

### `FailureClass` enum

```python
class FailureClass(str, Enum):
    PERMANENT_CONFIG = "permanent_config"   # missing API key, binary not installed
    PERMANENT_AUTH   = "permanent_auth"     # invalid credentials
    TRANSIENT_TIMEOUT = "transient_timeout" # network timeout, rate limit
    TRANSIENT_ERROR  = "transient_error"    # server 500, temporary failure
    LOGICAL_ERROR    = "logical_error"      # wrong arguments, bad input
    UNKNOWN          = "unknown"

    @property
    def is_permanent(self) -> bool: ...
```

### Classification (`ToolCallTracker.classify_failure()`)

Checks `ToolResult.metadata["error_type"]` first, then keyword-scans the error message
as fallback:
- `error_type="validation"` → `LOGICAL_ERROR`
- `error_type` in `("not_found", "permission", "unknown_role")` → `PERMANENT_CONFIG`
- `error_type="timeout"` → `TRANSIENT_TIMEOUT`
- Keywords: "api key" / "not configured" → `PERMANENT_CONFIG`; "unauthorized" / "forbidden"
  → `PERMANENT_AUTH`; "timeout" / "rate limit" / "429" → `TRANSIENT_TIMEOUT`; "500" /
  "server error" → `TRANSIENT_ERROR`

### Candidate elimination

Permanent failures (`is_permanent=True`) are added to `_permanent_failures` and the
tool is removed from the registry immediately on the **first occurrence** — not after
the standard 3-strike threshold. Transient and logical failures still escalate normally.

### Structured failure prompt (`_build_failure_prompt()`)

Replaces the generic 3-line `failure_strategy.md` injection. The prompt injected after
each failed batch now includes:
- Each failed tool with its `FailureClass` label and recovery guidance
- The list of permanently removed tools (do not retry)
- The list of remaining available tools as explicit alternatives

`failure_strategy.md` is retained as documentation of the recovery rules.

### Files changed

- `nanobot/agent/loop.py` — `FailureClass`, `ToolCallTracker.classify_failure()`,
  `_build_failure_prompt()`, updated batch-failure handling
- `nanobot/templates/prompts/failure_strategy.md` — updated to document new approach
- `prompts_manifest.json` — hash updated

---

## Implementation decisions

| Original plan item | Decision | Reason |
|--------------------|----------|--------|
| `intent.py` — verb routing table | Dropped | Stemmed description matching in `detect_relevant_skills()` covers the same need without a rigid verb list |
| Pre-planning routing pass | Dropped | Skills are already loaded into the system prompt before the first LLM call |
| `coordinator.classify()` returning intents | Dropped | Role classification is sufficient; intent labels add complexity without clear benefit |
| `validator.py` — `ActionValidator` | Dropped | Phase D delegation validation + Layer 4 classification handles the high-value cases |
| `replanner.py` — `ReplanningPolicy` | Absorbed into `ToolCallTracker` | Same semantics, less indirection |
| `FailureClass` enum | ✅ Built | In `loop.py` alongside `ToolCallTracker` |
| Structured failure prompt | ✅ Built | `_build_failure_prompt()` in `loop.py` |
| Permanent failure immediate removal | ✅ Built | `is_permanent` triggers removal at count=1 |
