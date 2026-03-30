# Delegation Cleanup Phase 2: Remove Dead Code and Backward Compatibility

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all residual delegation references (dead event types, metrics, config backward-compat validators) left after the Phase 1 deletion (PR #97).

**Architecture:** Pure dead-code removal. No behavioral changes, no new abstractions. Every file touched is strictly subtractive — deleting unreachable code and updating stale docstrings.

**Tech Stack:** Python, Pydantic, pytest

---

## Scope

### Remove backward-compat validators (user requested)
- `config/agent.py` — `_AGENT_REMOVED_FIELDS`, `_strip_removed` validator, `from_raw` stripping
- `config/schema.py` — `_FEATURES_REMOVED_FIELDS`, `_strip_removed` validator
- User's `~/.nanobot/config.json` — remove stale fields manually

### Remove dead event types (I2)
- `agent/callbacks.py` — `DelegateStartEvent`, `DelegateEndEvent`
- `agent/__init__.py` — exports
- `bus/canonical.py` — `delegate_start()`, `delegate_end()` methods
- `observability/bus_progress.py` — delegation match cases
- `cli/progress.py` — delegation imports and match case

### Remove dead metrics (I3, I4)
- `metrics.py` — `delegation_total`, `delegation_latency_seconds`
- `cli/routing.py` — delegation metric rows

### Remove dead tests (I7)
- `tests/test_cli_progress.py` — delegation event tests
- `tests/test_canonical_events.py` — delegation event tests
- `tests/test_bus_progress.py` — delegation event tests
- `tests/contract/test_progress_callbacks.py` — delegation event vectors
- `tests/integration/test_config_factory_wiring.py` — `delegation_enabled` params

### Update stale docstrings (S1, S2)
- `coordination/mission.py` — references to "delegation engine"
- `coordination/task_types.py` — "delegation task"
- `README.md` — `delegation_enabled` feature flag

---

### Task 1: Remove backward-compat config validators

**Files:**
- Modify: `nanobot/config/agent.py`
- Modify: `nanobot/config/schema.py`

- [ ] **Step 1: Remove `_AGENT_REMOVED_FIELDS` and validators from `config/agent.py`**

Remove the module-level constant, the `model_validator`, the `model_validator` import, and the stripping logic in `from_raw`:

In `nanobot/config/agent.py`, replace:
```python
from pydantic import Field, model_validator
```
with:
```python
from pydantic import Field
```

Delete these lines entirely:
```python
# Fields removed in 2026-03-29 (delegation subsystem removal).
# Stripped from raw config dicts so existing config.json files don't break.
_AGENT_REMOVED_FIELDS = frozenset({"delegation_enabled", "max_delegation_depth"})
```

Delete the `_strip_removed` validator:
```python
    @model_validator(mode="before")
    @classmethod
    def _strip_removed(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if k not in _AGENT_REMOVED_FIELDS}
        return data
```

Simplify `from_raw` back to its original form:
```python
    @classmethod
    def from_raw(cls, raw: dict[str, Any], **overrides: Any) -> AgentConfig:
        """Construct from config file data with overrides applied last."""
        data = dict(raw)
        data.update(overrides)
        return cls.model_validate(data)
```

- [ ] **Step 2: Remove `_FEATURES_REMOVED_FIELDS` and validator from `config/schema.py`**

In `nanobot/config/schema.py`, remove `model_validator` from the import:
```python
from pydantic import Field, model_validator
```
→
```python
from pydantic import Field
```

Also remove `Any` from the typing import if no longer used (check first).

Delete the module-level constant:
```python
# Removed 2026-03-29: delegation_enabled (delegation subsystem removed)
_FEATURES_REMOVED_FIELDS = frozenset({"delegation_enabled"})
```

Delete the validator from `FeaturesConfig`:
```python
    @model_validator(mode="before")
    @classmethod
    def _strip_removed(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if k not in _FEATURES_REMOVED_FIELDS}
        return data
```

- [ ] **Step 3: Clean user config file**

Manually edit `~/.nanobot/config.json` to remove:
- `agents.defaults.delegation_enabled`
- `agents.defaults.max_delegation_depth`
- `features.delegation_enabled`

- [ ] **Step 4: Verify**

Run: `make lint && make typecheck`

---

### Task 2: Remove dead delegation event types

**Files:**
- Modify: `nanobot/agent/callbacks.py`
- Modify: `nanobot/agent/__init__.py`
- Modify: `nanobot/bus/canonical.py`
- Modify: `nanobot/observability/bus_progress.py`
- Modify: `nanobot/cli/progress.py`

- [ ] **Step 1: Remove `DelegateStartEvent` and `DelegateEndEvent` from `callbacks.py`**

Delete these two dataclass definitions:
```python
@dataclass(frozen=True, slots=True)
class DelegateStartEvent:
    """Agent is delegating to a child agent."""

    delegation_id: str
    child_role: str
    task_title: str = ""


@dataclass(frozen=True, slots=True)
class DelegateEndEvent:
    """Child agent delegation completed."""

    delegation_id: str
    success: bool
```

Update the `ProgressEvent` union — remove `DelegateStartEvent` and `DelegateEndEvent`:
```python
ProgressEvent = (
    TextChunk
    | ToolCallEvent
    | ToolResultEvent
    | StatusEvent
)
```

Remove from `__all__`:
```python
    "DelegateEndEvent",
    "DelegateStartEvent",
```

- [ ] **Step 2: Remove delegation exports from `agent/__init__.py`**

Remove these lines from the import block:
```python
    DelegateEndEvent,
    DelegateStartEvent,
```

Remove from `__all__`:
```python
    "DelegateEndEvent",
    "DelegateStartEvent",
```

- [ ] **Step 3: Remove `delegate_start()` and `delegate_end()` from `bus/canonical.py`**

Delete the entire "Delegation lifecycle" section:
```python
    # ------------------------------------------------------------------
    # Delegation lifecycle
    # ------------------------------------------------------------------

    def delegate_start(
        self,
        delegation_id: str,
        child_role: str,
        task_title: str = "",
    ) -> dict[str, Any]:
        """Emit when delegating work to a sub-agent."""
        return self._envelope(
            "agent.delegate.start",
            {
                "delegation_id": delegation_id,
                "parent_agent_id": self.actor_id,
                "child_agent_id": child_role,
                "task": {"title": task_title},
            },
        )

    def delegate_end(
        self,
        delegation_id: str,
        *,
        success: bool = True,
    ) -> dict[str, Any]:
        """Emit when a delegated sub-agent finishes."""
        return self._envelope(
            "agent.delegate.end",
            {
                "delegation_id": delegation_id,
                "status": "success" if success else "error",
            },
        )
```

- [ ] **Step 4: Remove delegation match cases from `observability/bus_progress.py`**

Remove delegation imports:
```python
    DelegateEndEvent,
    DelegateStartEvent,
```

Remove delegation match cases from the `_progress` function:
```python
            case DelegateStartEvent(delegation_id=did, child_role=role, task_title=title):
                meta["_canonical"] = canonical_builder.delegate_start(
                    delegation_id=did, child_role=role, task_title=title
                )
            case DelegateEndEvent(delegation_id=did, success=success):
                meta["_canonical"] = canonical_builder.delegate_end(
                    delegation_id=did, success=success
                )
```

- [ ] **Step 5: Remove delegation imports and match case from `cli/progress.py`**

Remove from import block:
```python
    DelegateEndEvent,
    DelegateStartEvent,
```

Update the match case that handles them:
```python
            case StatusEvent() | ToolResultEvent() | DelegateStartEvent() | DelegateEndEvent():
                pass  # CLI does not render these; ignored explicitly
```
→
```python
            case StatusEvent() | ToolResultEvent():
                pass  # CLI does not render these; ignored explicitly
```

- [ ] **Step 6: Verify**

Run: `make lint && make typecheck`

---

### Task 3: Remove dead delegation metrics

**Files:**
- Modify: `nanobot/metrics.py`
- Modify: `nanobot/cli/routing.py`

- [ ] **Step 1: Remove delegation metrics from `metrics.py`**

In the `try` block, delete:
```python
    # Multi-agent delegation and routing metrics (LAN-129)
    delegation_total = Counter(
        "nanobot_delegation_total",
        "Total delegations dispatched",
        ["from_role", "to_role", "success"],
    )
    delegation_latency_seconds = Histogram(
        "nanobot_delegation_latency_seconds",
        "Delegation execution duration in seconds",
        ["to_role"],
    )
```

Update the comment on the remaining metrics:
```python
    # Multi-agent delegation and routing metrics (LAN-129)
    classification_total = Counter(
```
→
```python
    # Routing classification metrics (LAN-129)
    classification_total = Counter(
```

In the `except ImportError` block, delete:
```python
    delegation_total = _NoOp()  # type: ignore[assignment]
    delegation_latency_seconds = _NoOp()  # type: ignore[assignment]
```

Remove from `__all__`:
```python
    "delegation_total",
    "delegation_latency_seconds",
```

- [ ] **Step 2: Remove delegation metric rows from `cli/routing.py`**

Remove `"routing_delegations"` from the core counters loop:
```python
    for key in (
        "routing_classifications",
        "routing_delegations",
        "routing_cycles_blocked",
    ):
```
→
```python
    for key in (
        "routing_classifications",
        "routing_cycles_blocked",
    ):
```

Remove delegation latency variables and rows:
```python
    del_count = int(data.get("routing_delegations", 0) or 0)
    del_sum = float(data.get("delegation_latency_sum_ms", 0) or 0)
    del_max = float(data.get("delegation_latency_max_ms", 0) or 0)
```
and:
```python
    table.add_row("delegation_latency_avg_ms", f"{del_sum / del_count:.0f}" if del_count else "—")
    table.add_row("delegation_latency_max_ms", f"{del_max:.0f}" if del_max else "—")
```

- [ ] **Step 3: Verify**

Run: `make lint && make typecheck`

---

### Task 4: Clean up test files

**Files:**
- Modify: `tests/test_cli_progress.py`
- Modify: `tests/test_canonical_events.py`
- Modify: `tests/test_bus_progress.py`
- Modify: `tests/contract/test_progress_callbacks.py`
- Modify: `tests/integration/test_config_factory_wiring.py`
- Modify: `tests/test_commands_routing_cron.py`

- [ ] **Step 1: Remove delegation tests from `test_cli_progress.py`**

Delete `test_delegate_start_event_silent` and `test_delegate_end_event_silent` tests.
Remove `DelegateStartEvent`, `DelegateEndEvent` imports.

- [ ] **Step 2: Remove delegation tests from `test_canonical_events.py`**

Delete `test_delegate_start`, `test_delegate_end_success`, `test_delegate_end_failure`, and `test_delegate_events_emit_nothing` tests.

- [ ] **Step 3: Remove delegation tests from `test_bus_progress.py`**

Delete `test_delegate_start_sets_canonical` and `test_delegate_end_sets_canonical` tests.
Remove `DelegateStartEvent`, `DelegateEndEvent` imports.

- [ ] **Step 4: Remove delegation event vectors from `tests/contract/test_progress_callbacks.py`**

Remove `DelegateStartEvent` and `DelegateEndEvent` from test vectors and imports.

- [ ] **Step 5: Clean `delegation_enabled` from `test_config_factory_wiring.py`**

Remove `delegation_enabled=True/False` kwargs from AgentConfig constructor calls.
Remove or update tests that specifically test delegation-disabled behavior.

- [ ] **Step 6: Clean delegation metrics from `test_commands_routing_cron.py`**

Update expected metrics assertions to remove `routing_delegations` and delegation latency references.

- [ ] **Step 7: Verify**

Run: `make lint && make typecheck`

---

### Task 5: Update stale docstrings

**Files:**
- Modify: `nanobot/coordination/mission.py`
- Modify: `nanobot/coordination/task_types.py`
- Modify: `README.md`

- [ ] **Step 1: Update `mission.py` docstrings**

Module docstring (line 1):
```python
"""Background mission manager — asynchronous delegated task execution.

A *mission* is an asynchronous task that runs in the background using the
delegation engine's structured contracts, task taxonomy, and grounding
verification.  Results are delivered directly to the user via
``OutboundMessage`` (not re-injected through the agent loop).

Works with or without a coordinator: when ``routing.enabled=True`` the
coordinator classifies the task into a specialist role; otherwise a
``general`` role is used with the same contract quality.
```
→
```python
"""Background mission manager — asynchronous task execution.

A *mission* is an asynchronous task that runs in the background using
structured contracts, task taxonomy, and grounding verification.
Results are delivered directly to the user via ``OutboundMessage``
(not re-injected through the agent loop).
```

Mission dataclass docstring (line ~61):
```python
    """A background task executed through the delegation engine."""
```
→
```python
    """A background task executed asynchronously."""
```

`_execute_mission` docstring (line ~200):
```python
        """Run the mission through the delegation engine."""
```
→
```python
        """Run the mission in a background tool-use loop."""
```

Section comment (line ~367):
```python
    # Prompt construction (reuses delegation contract patterns)
```
→
```python
    # Prompt construction
```

`_build_system_prompt` docstring:
```python
        """Build a structured system prompt using the delegation contract pattern."""
```
→
```python
        """Build a structured system prompt for the mission."""
```

- [ ] **Step 2: Update `task_types.py` docstring**

Line ~110:
```python
    """Classify a delegation task into a task type from the taxonomy.
```
→
```python
    """Classify a task into a task type from the taxonomy.
```

- [ ] **Step 3: Update `README.md`**

Remove the delegation feature flag row from the table:
```markdown
| `delegation_enabled` | `true` | Multi-agent delegation |
```

Remove the delegation example from the JSON block:
```json
    "delegation_enabled": false
```

- [ ] **Step 4: Verify**

Run: `make check`

---

### Task 6: Final validation

- [ ] **Step 1: Run full CI**

Run: `make pre-push`

Expected: All tests pass, coverage ≥ 85%.

- [ ] **Step 2: Grep for any remaining references**

```bash
grep -rn "delegation" nanobot/ tests/ --include="*.py" | grep -v "docs/" | grep -v "__pycache__"
```

Expected: Zero matches (or only in `cli/routing.py` reading legacy JSON keys which is acceptable).

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "refactor: remove residual delegation dead code and backward-compat validators

Complete Phase 2 cleanup of delegation removal (PR #97):
- Remove DelegateStartEvent/DelegateEndEvent event types
- Remove delegation_total/delegation_latency_seconds metrics
- Remove config backward-compat validators (_strip_removed)
- Remove stale delegation_enabled from user config.json
- Update mission.py docstrings to remove delegation references
- Clean up 6 test files with orphaned delegation assertions"
```
