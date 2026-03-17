# Agent Intelligence Layers — Planning Document

> Architectural improvements to the agent's capability selection, action validation,
> and failure recovery. Layer 1 (Capability Registry) is tracked in
> [ADR-009](adr/ADR-009-capability-registry.md) and branch `feature/capability-registry`.
> Layers 2–4 are planned for subsequent iterations.

## Overview

| Layer | Name | Purpose | Depends on |
|-------|------|---------|------------|
| 1 | **Capability Registry** | Unified registry with availability checks | — |
| 2 | **Intent-to-Capability Routing** | Deterministic pre-planning capability selection | Layer 1 |
| 3 | **Action Boundary Validation** | Strict runtime validation before every action | Layer 1 |
| 4 | **Failure-Aware Replanning** | Structured recovery after failed actions | Layers 1 + 3 |

---

## Layer 1: Capability Registry ✅ ADR-009

**Status**: In progress — `feature/capability-registry` branch

**Summary**: Replace fragmented tool/skill/role registries with a unified
`CapabilityRegistry` that tracks availability, health, and metadata. The LLM only
sees capabilities that are configured, installed, and healthy. Details in ADR-009.

---

## Layer 2: Intent-to-Capability Routing

**Status**: Planned — next iteration after Layer 1

### Problem

The agent currently receives a flat list of available tools and freely chooses among
them. This causes:

- **Suboptimal tool selection**: The LLM picks `web_search` when `playwright-cli`
  would be better for "open youtube and browse trending videos."
- **No fast-path for common patterns**: Every request goes through full LLM reasoning
  even when the intent is unambiguous ("open X" always means browser navigation).
- **Skill activation misses**: Skills depend on trigger phrase matching or description
  keyword overlap — neither captures user intent semantically.

### Design: Hybrid routing (deterministic fast-path + LLM fallback)

**Phase 1 — Verb-based routing table** (deterministic, no LLM cost):

```python
INTENT_VERBS: dict[str, list[str]] = {
    "browser_nav":    ["open", "go to", "navigate", "visit", "browse", "click", "log in"],
    "browser_read":   ["screenshot", "scrape", "extract from", "read page"],
    "search_web":     ["search for", "look up", "find info", "latest news", "what is"],
    "search_site":    ["search on", "find on youtube", "find on github"],
    "code_impl":      ["code", "implement", "refactor", "write test", "fix bug", "add feature"],
    "file_ops":       ["read file", "write file", "edit", "list dir", "create file"],
    "system_ops":     ["run command", "install", "restart", "deploy", "ssh"],
    "summarize":      ["summarize", "tldr", "recap", "key points"],
    "email":          ["send email", "check email", "reply to"],
    "schedule":       ["schedule", "remind me", "set timer", "every day at"],
}
```

For each detected intent, rank capabilities by `fallback_priority` from the
Capability Registry:

```
Intent: browser_nav
  1. playwright-cli skill (priority 1) — if available
  2. web_fetch tool (priority 5) — degraded, no JS rendering
  3. delegate to research role (priority 10) — last resort
```

**Phase 2 — LLM-based intent classification** (for ambiguous cases):

When verb matching is inconclusive (score below threshold, multiple competing intents),
fall back to a lightweight LLM call similar to the existing `Coordinator.classify()`:

```
Given the user message: "{message}"
Available intents: {intent_list}
Return: {"primary_intent": "...", "secondary_intents": [...], "confidence": float}
```

This replaces the current approach where the full planning LLM call discovers tool
availability through trial and error.

**Phase 3 — Capability ranking for mixed intents**:

Complex messages like "open youtube, find trending woodworking, and summarize the top
results" produce multiple intents. The router should:

1. Decompose into intent sequence: `[browser_nav, search_site, summarize]`
2. For each intent, select the best available capability
3. Pass the ordered plan to the LLM as a hint (not a constraint)

### Integration points

- `CapabilityRegistry.get_available(intent="browser_nav")` — query by intent
- `SkillsLoader.detect_relevant_skills()` — replace with intent-based activation
- `AgentLoop._run_agent_loop()` — insert routing pass before first LLM call
- `Coordinator.classify()` — extend to return intents alongside role classification

### Files to modify

- **NEW** `nanobot/agent/intent.py` — `IntentRouter` class, verb table, scoring
- `nanobot/agent/capability.py` — ensure `get_available(intent=)` filter works
- `nanobot/agent/loop.py` — insert routing pass in `_run_agent_loop()`
- `nanobot/agent/skills.py` — `detect_relevant_skills()` uses intent router
- `nanobot/agent/coordinator.py` — extend `classify()` to return intents
- `nanobot/agent/context.py` — include routing decision in system prompt

### Success criteria

- "open youtube" activates playwright-cli without trigger phrases in SKILL.md
- "search for woodworking tips" selects web_search (if available) or playwright (fallback)
- "summarize this article" activates summarize skill without hard-coded triggers
- Routing adds < 5ms latency for deterministic path, < 500ms for LLM fallback

---

## Layer 3: Action Boundary Validation

**Status**: Planned — after Layer 2

### Problem

The agent can attempt actions that are guaranteed to fail:

- **Tool calls to unconfigured tools**: Partially solved by Layer 1 (filtered from
  definitions), but edge cases remain with MCP tools and dynamic registration.
- **Delegation to nonexistent roles**: Partially solved by Layer 1 (enum constraint),
  but parallel delegation and nested delegation need validation too.
- **Invalid tool arguments**: Parameter validation exists in `ToolRegistry.execute()`
  but runs at execution time, not at planning time.
- **Skill activation without prerequisites**: A skill's tools might require binaries
  that aren't installed even though the skill passed `_check_requirements()`.

### Design: Pre-execution validation layer

Every action goes through a validation gate before execution:

```python
class ActionValidator:
    async def validate(self, action: PlannedAction) -> ValidationResult:
        """Validate before execution. Returns ok or structured error."""

    @dataclass(slots=True)
    class ValidationResult:
        valid: bool
        error: str | None = None
        error_type: str | None = None
        suggestion: str | None = None  # "Try playwright-cli instead"
```

**Validation rules by action type**:

| Action | Validation |
|--------|-----------|
| Tool call | Tool exists in registry AND `check_available()` passes AND params valid |
| Delegation | Role exists in registry AND is enabled AND delegation depth < max |
| Skill activation | Skill requirements met AND referenced tools available |
| MCP tool call | MCP server connected AND tool registered AND healthy |

**On validation failure**: Return `ValidationResult` with:
- Clear error message (what failed)
- Error type for programmatic handling
- Suggestion for alternative (from capability registry intent mapping)

This replaces the current pattern where tools fail at execution time and the `failure_strategy`
prompt hopes the LLM will figure out an alternative.

### Integration points

- `ToolExecutor.execute_batch()` — insert validation before execution
- `DelegationDispatcher.dispatch()` — reject invalid delegations pre-dispatch
- `ToolCallTracker` — validation failures don't count toward the failure budget
  (they're caught before wasting a tool turn)
- `nanobot/errors.py` — add `ActionValidationError`, `UnknownRoleError`

### Files to modify

- **NEW** `nanobot/agent/validator.py` — `ActionValidator` class
- `nanobot/agent/tool_executor.py` — call validator before execution
- `nanobot/agent/delegation.py` — call validator before dispatch
- `nanobot/agent/loop.py` — wire validator into tool execution path
- `nanobot/errors.py` — new error types

### Success criteria

- Delegation to `role="web"` returns immediate structured error with available roles
- Tool call to unconfigured `web_search` returns error with suggestion to use `web_fetch`
- Validation errors don't consume `ToolCallTracker` failure budget
- All validation happens synchronously (no LLM cost)

---

## Layer 4: Failure-Aware Replanning

**Status**: Planned — after Layer 3

### Problem

When an action fails, the agent's recovery is unstructured:

- **`failure_strategy` prompt** tells the LLM to "analyze what went wrong" — a
  3-line generic hint with no context about what alternatives exist.
- **`ToolCallTracker`** removes tools after 3 identical failures — reactive, not
  proactive. Doesn't guide the agent toward working alternatives.
- **No candidate elimination**: After `web_search` fails, the agent might try
  `delegate(role="web")` — another doomed approach — instead of `playwright-cli`.
- **No failure classification**: A missing API key (permanent) and a timeout (transient)
  get the same treatment.

### Design: Structured replanning policy

```python
class ReplanningPolicy:
    async def handle_failure(
        self,
        failed_action: ToolCallRequest,
        error: ToolResult,
        context: ReplanContext,
    ) -> ReplanDecision:
        """Classify failure, update candidate set, choose next action."""
```

**Step 1 — Classify failure**:

```python
class FailureClass(Enum):
    PERMANENT_CONFIG = "permanent_config"     # missing API key, no binary
    PERMANENT_AUTH = "permanent_auth"          # invalid credentials
    TRANSIENT_TIMEOUT = "transient_timeout"   # network timeout, rate limit
    TRANSIENT_ERROR = "transient_error"       # server 500, temporary failure
    LOGICAL_ERROR = "logical_error"           # wrong arguments, bad input
    UNKNOWN = "unknown"
```

Classification uses error type metadata from `ToolResult`:
- `error_type="validation"` → `LOGICAL_ERROR`
- `error_type="not_found"` → `PERMANENT_CONFIG`
- Error message contains "API key" / "not configured" → `PERMANENT_CONFIG`
- Error message contains "timeout" / "429" / "rate limit" → `TRANSIENT_TIMEOUT`

**Step 2 — Update candidate set**:

Based on failure class:
- `PERMANENT_*` → remove capability from candidate set for the entire session
- `TRANSIENT_*` → keep in candidate set but with lowered priority and backoff
- `LOGICAL_ERROR` → keep but inject corrective context

**Step 3 — Select next-best capability**:

Query `CapabilityRegistry.get_available(intent=failed_intent)` for alternatives,
excluding eliminated candidates. Provide the LLM with a constrained prompt:

```
The previous action failed: {error_summary}
Failure type: {failure_class} (will not retry)
Removed from candidates: {removed_list}
Remaining options for this intent:
  1. playwright-cli (browser automation, priority 1) — available
  2. delegate to research role (priority 10) — available
Choose the best alternative or explain why the task cannot be completed.
```

**Step 4 — Budget enforcement**:

```python
@dataclass
class ReplanBudget:
    max_retries_per_intent: int = 3        # per intent, not per tool
    max_total_replans: int = 5             # across all intents in a turn
    max_permanent_failures: int = 3        # give up after N permanent failures
```

When budget exhausted: force final answer with a clear explanation of what was tried
and why it failed, not a generic apology.

### Example: YouTube woodworking scenario

```
User: "open youtube and find trending woodworking"

Intent detected: [browser_nav, search_site]
Candidates: [web_search(p=1), playwright-cli(p=2), web_fetch(p=5), delegate-research(p=10)]

Action 1: web_search("trending woodworking youtube")
  → FAIL: PERMANENT_CONFIG (missing API key)
  → Remove web_search from candidates
  → Replan: next-best for search_site = playwright-cli

Action 2: exec("playwright-cli open https://youtube.com")
  → OK
Action 3: exec("playwright-cli snapshot")
  → OK: page loaded, search box visible at e5
Action 4: exec("playwright-cli fill e5 'trending woodworking'")
  → OK
Action 5: exec("playwright-cli press Enter")
  → OK
Action 6: exec("playwright-cli snapshot")
  → OK: results visible

Result: Successfully browsed YouTube and found trending woodworking content.
```

### Integration points

- `ToolCallTracker` — enhanced with failure classification, becomes `FailureTracker`
- `failure_strategy` prompt — replaced by structured replanning context
- `CapabilityRegistry` — queried for alternatives by intent
- `IntentRouter` (Layer 2) — provides intent context for alternative ranking
- `ActionValidator` (Layer 3) — pre-validates alternative before attempt

### Files to modify

- **NEW** `nanobot/agent/replanner.py` — `ReplanningPolicy`, `FailureClass`, `ReplanBudget`
- `nanobot/agent/loop.py` — replace `ToolCallTracker` with `FailureTracker`, wire replanning
- `nanobot/agent/capability.py` — `get_available(intent=, exclude=)` filter
- `nanobot/templates/prompts/failure_strategy.md` — replace with structured template
- `nanobot/agent/tool_executor.py` — return failure class metadata in `ToolResult`

### Success criteria

- Missing API key classified as `PERMANENT_CONFIG`, never retried in same session
- After web_search fails, agent automatically tries playwright-cli for same intent
- Timeout errors get exponential backoff, not immediate removal
- Final answer after budget exhaustion lists what was tried and why each failed
- Replanning adds < 1ms for candidate selection (no LLM cost for the routing itself)

---

## Dependencies

```
Layer 1: Capability Registry (ADR-009)
    ↓
Layer 2: Intent Routing (depends on Layer 1 for get_available(intent=))
    ↓
Layer 3: Action Validation (depends on Layer 1 for availability checks)
    ↓
Layer 4: Replanning (depends on Layers 1 + 2 + 3 for alternatives + validation)
```

Layers 2 and 3 can be developed in parallel after Layer 1 is complete.
Layer 4 benefits from all three but can be partially implemented with Layer 1 alone
(using `ToolCallTracker` enhancement without full intent routing).
