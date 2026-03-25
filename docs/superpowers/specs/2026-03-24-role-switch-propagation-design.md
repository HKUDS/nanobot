# Role-Switch Field Propagation Fix

**Date:** 2026-03-24
**Topic:** Fix stale model/temperature/max_iterations/role_name after role switching
**Status:** Draft

---

## Problem Statement

When the coordinator routes a message to a role (e.g., `pm` with `model=openai/gpt-4o`),
`TurnRoleManager.apply()` updates `AgentLoop.model`. But the extracted components that
actually consume these values — `StreamingLLMCaller`, `TurnOrchestrator`, `AnswerVerifier`,
`MessageProcessor` — cache their own copies at construction time and never read from
`AgentLoop`. Every routed turn uses the **default model** instead of the role's model.

### Affected fields and components

| Field | `AgentLoop` | `StreamingLLMCaller` | `TurnOrchestrator` | `ReflectPhase` | `MessageProcessor` | `AnswerVerifier` |
|-------|:-----------:|:-------------------:|:------------------:|:--------------:|:------------------:|:----------------:|
| model | Updated | STALE | STALE | — | STALE | STALE |
| temperature | Updated | STALE | — | — | — | STALE |
| max_iterations | Updated | — | STALE | — | — | — |
| role_name | Updated | — | STALE | STALE | STALE | — |

### Root cause

The architecture restructuring extracted components from the `AgentLoop` monolith. Before
extraction, the loop's methods read `self.model` directly. After extraction, each component
got its own copy at construction time. `TurnRoleManager` only knows the `_LoopLike` Protocol
and updates `loop.*` fields — it has no reference to the extracted components.

### Why testing missed it

Each component is tested in isolation with mocks. The role switching tests verify that
`loop.model` is updated (correct). The orchestrator tests verify that `llm_caller.call()`
is invoked (correct). But no integration test verifies that the model the **provider
actually receives** matches the role's model after switching.

---

## Design: Per-Turn Parameter Passing (Approach B)

### Approach rationale

CLAUDE.md requires strict import direction: `agent/` (orchestration, outer) may import
from `coordination/` (domain, inner), never the reverse. A shared mutable `TurnSettings`
object would either live in `agent/` (coordination can't import it) or `coordination/`
(semantically wrong — it's orchestration state). Per-turn parameter passing avoids new
cross-package types entirely.

### Principle

**Role-switched values flow explicitly through the call chain.** Components keep
construction-time values as fallback defaults, but per-turn values override them.
No shared mutable state. No new cross-package types.

---

## Section 1: TurnState carries active settings

Add optional per-turn override fields to `TurnState` in `agent/turn_types.py`:

```python
@dataclass(slots=True)
class TurnState:
    messages: list[dict[str, Any]]
    user_text: str
    classification_result: ClassificationResult | None = None
    # ... existing fields ...

    # Per-turn role overrides (None = use component defaults)
    active_model: str | None = None
    active_temperature: float | None = None
    active_max_iterations: int | None = None
    active_role_name: str | None = None
```

**Why `active_` prefix:** Distinguishes per-turn overrides from any future config fields.
`None` means "no override, use the component's construction-time default."

**Null-safety:** All fallback expressions must use explicit `is not None` checks, not
truthiness, because `0` (max_iterations), `""` (model), and `0.0` (temperature) are
falsy but potentially valid values:

```python
# WRONG: state.active_max_iterations or self._max_iterations  (0 is falsy)
# RIGHT:
(state.active_max_iterations if state.active_max_iterations is not None
 else self._max_iterations)
```

### Two-hop data flow and why both are needed

Active settings flow through `MessageProcessor` via two paths:

1. **Instance fields** (`self._active_model`, etc.) — used by `MessageProcessor` itself
   for audit logging (Section 5), consolidation calls (Section 5), and
   `attempt_recovery()` (Section 4). These are set once per turn by `set_active_settings()`.

2. **`TurnState.active_*` fields** — used by `TurnOrchestrator`, `StreamingLLMCaller`,
   `AnswerVerifier.verify()`, and `ReflectPhase`. Populated by `_run_orchestrator()`
   reading from the instance fields.

`_run_orchestrator()` does **not** gain keyword parameters — it reads `self._active_*`
directly. The instance fields are the single source of truth within the processor:

```python
async def _run_orchestrator(self, messages, on_progress):
    # ... existing user_text extraction ...
    state = TurnState(
        messages=messages,
        user_text=user_text,
        classification_result=self.classification_result,
        active_model=self._active_model,
        active_temperature=self._active_temperature,
        active_max_iterations=self._active_max_iterations,
        active_role_name=self._active_role_name,
        tools_def_cache=list(self.tools.get_definitions()),
    )
    ...
```

### Who sets the instance fields: `AgentLoop`

`AgentLoop` reads its own (role-switched) fields and forwards them to the processor
via `set_active_settings()`. This must happen at **every call site**:

**Call site 1: `AgentLoop.run()` — bus-based message processing** (`loop.py:~290`):

```python
# After _classify_and_route() updates loop.model etc.
turn_ctx = await self._classify_and_route(msg)
# Sync active settings to processor for this turn
self._processor.set_active_settings(
    model=self.model, temperature=self.temperature,
    max_iterations=self.max_iterations, role_name=self.role_name,
)
response = await self._process_message(msg)
```

**Call site 2: `AgentLoop.process_direct()` — CLI/cron path** (`loop.py:~477`):

```python
turn_ctx = self._role_manager.apply(role)
# Sync active settings for forced-role path
self._processor.set_active_settings(
    model=self.model, temperature=self.temperature,
    max_iterations=self.max_iterations, role_name=self.role_name,
)
```

**Call site 3: No role switching (default path)** — when no coordinator is configured
or classification is skipped, the processor uses its construction-time defaults (the
`active_*` fields on `TurnState` remain `None`). `set_active_settings()` is called
with the loop's default values so that logging/consolidation are consistent.

### `set_active_settings()` on MessageProcessor

Exposes the active values for use by `_run_orchestrator()`, audit logging, and
consolidation calls:

```python
def set_active_settings(
    self, *, model: str, temperature: float,
    max_iterations: int, role_name: str,
) -> None:
    """Forward role-switched settings for the upcoming turn."""
    self._active_model = model
    self._active_temperature = temperature
    self._active_max_iterations = max_iterations
    self._active_role_name = role_name
```

**Protocol update:** Add `set_active_settings` to the `Processor` Protocol in
`turn_types.py` so test mocks and future implementations honor the contract:

```python
class Processor(Protocol):
    def set_active_settings(
        self, *, model: str, temperature: float,
        max_iterations: int, role_name: str,
    ) -> None: ...
    # ... existing methods ...
```

`MessageProcessor._run_orchestrator()` passes `self._active_*` into `TurnState`.

---

## Section 2: StreamingLLMCaller accepts per-call overrides

Add optional `model` and `temperature` parameters to `StreamingLLMCaller.call()`:

```python
async def call(
    self,
    messages: list[dict],
    tools: list[dict[str, Any]] | None,
    on_progress: ProgressCallback | None,
    *,
    model: str | None = None,
    temperature: float | None = None,
) -> LLMResponse:
    effective_model = model if model is not None else self.model
    effective_temperature = temperature if temperature is not None else self.temperature
    # Use effective_model and effective_temperature in chat() / stream_chat()
```

Construction-time values remain as defaults. Per-call values win when provided.

**Logging must use effective values.** Both the non-streaming and streaming paths log
`self.model` in trace output. After the fix, all log lines must use `effective_model`
and `effective_temperature` so diagnostics reflect the actual values sent to the provider:

```python
bind_trace().debug(
    "LLM stream model={} latency_ms={:.0f} ...",
    effective_model,  # not self.model
    latency_ms,
    ...
)
```

**Caller change in `TurnOrchestrator.run()`:**

```python
raw_response = await self._llm_caller.call(
    state.messages,
    active_tools,
    on_progress,
    model=state.active_model,
    temperature=state.active_temperature,
)
```

---

## Section 3: TurnOrchestrator reads from TurnState

Three fields in `TurnOrchestrator` become stale after role switching:

1. **`self._model`** — used as fallback for `summary_model` in context compression.
   ```python
   effective_model = (state.active_model if state.active_model is not None
                      else self._model)
   summary_model = (_raw_sm if isinstance(_raw_sm, str) else None) or effective_model
   ```

2. **`self._max_iterations`** — controls the PAOR loop bound.
   At the top of `run()`:
   ```python
   max_iterations = (state.active_max_iterations
                     if state.active_max_iterations is not None
                     else self._max_iterations)
   ```
   Use `max_iterations` in the `while` condition instead of `self._max_iterations`.

3. **`self._role_name`** — passed to delegation advisor in plan and reflect phases.
   ```python
   effective_role_name = (state.active_role_name if state.active_role_name is not None
                          else self._role_name)
   ```
   Use `effective_role_name` when calling `advise_plan_phase()` and when passing to
   `ReflectPhase`.

**ReflectPhase** also caches `role_name`. The actual method is `evaluate()` (not
`reflect()`). Fix: the orchestrator passes `role_name` as a parameter to `evaluate()`
each invocation, since `TurnState` is already available. `ReflectPhase.evaluate()`
gains a `role_name: str | None = None` parameter and uses it over `self._role_name`
when provided:

```python
# In ReflectPhase.evaluate():
effective_role = role_name if role_name is not None else self._role_name

# In TurnOrchestrator.run(), calling reflect:
self._reflect.evaluate(state, response, ..., role_name=effective_role_name)
```

---

## Section 4: AnswerVerifier per-call overrides

`AnswerVerifier.verify()` and `attempt_recovery()` use `self.model` and
`self.temperature`.

**Call sites (two different callers):**

1. `verify()` is called from `TurnOrchestrator.run()` (`turn_orchestrator.py:~393`),
   which has access to `state.active_model` / `state.active_temperature`:
   ```python
   final_content, state.messages = await self._verifier.verify(
       user_text=state.user_text,
       content=final_content,
       messages=state.messages,
       model=state.active_model,
       temperature=state.active_temperature,
   )
   ```

2. `attempt_recovery()` is called from `MessageProcessor._process_message()`
   (`message_processor.py:~271`), **not** from TurnOrchestrator. The processor must
   pass its `_active_*` values:
   ```python
   _recovered = await self.verifier.attempt_recovery(
       channel=msg.channel,
       chat_id=msg.chat_id,
       all_msgs=all_msgs,
       model=self._active_model,
       temperature=self._active_temperature,
   )
   ```

Add optional `model`/`temperature` params to both verifier methods:

```python
async def verify(
    self, *, user_text: str, content: str, messages: list,
    model: str | None = None, temperature: float | None = None,
) -> tuple[str, list]:
    effective_model = model if model is not None else self.model
    effective_temperature = temperature if temperature is not None else self.temperature
    ...

async def attempt_recovery(
    self, *, channel: str, chat_id: str, all_msgs: list,
    model: str | None = None, temperature: float | None = None,
) -> str | None:
    effective_model = model if model is not None else self.model
    ...
```

---

## Section 5: MessageProcessor logging and consolidation fix

### Audit logging

`MessageProcessor` logs `model=self.model` in the `request_complete` audit line
(`message_processor.py:325`) and Langfuse span metadata (`message_processor.py:307`).
After the fix, use `self._active_model` with explicit `is not None` fallback:

```python
effective_model = (self._active_model if self._active_model is not None
                   else self.model)
effective_role = (self._active_role_name if self._active_role_name is not None
                  else self.role_name)
```

Use `effective_model` and `effective_role` in both the span metadata and the audit line.

### Consolidation calls

`MessageProcessor` passes `self.model` to the consolidation orchestrator at three call
sites (`message_processor.py:206, 490, 493`):

```python
# BEFORE (stale):
self._consolidator.submit(session.key, session, self.provider, self.model)

# AFTER:
self._consolidator.submit(session.key, session, self.provider, effective_model)
```

Same fix for `consolidate_and_wait()` in `_consolidate_memory()`.

---

## Section 6: CLAUDE.md rule addition

Add a new entry under **Prohibited Patterns > Wiring violations**:

```markdown
- Construction-time caching of role-switched fields (`model`, `temperature`,
  `max_iterations`, `role_name`) in extracted components without a per-turn
  override mechanism. Components must accept per-turn values via `TurnState`
  or method parameters; construction-time values serve only as fallback defaults.
```

Add a new entry under **Before any structural refactoring**:

```markdown
6. **Check role-switched field propagation** — if the extracted component receives
   `model`, `temperature`, `max_iterations`, or `role_name` at construction time,
   verify that per-turn overrides from role switching reach the component. Add an
   integration test (see `tests/contract/test_role_propagation.py`) that wires real
   components via `build_agent()`, applies a role, runs a turn, and asserts the
   provider received the role's values.
```

---

## Section 7: Integration tests

### 7a: Seam contract tests (`tests/contract/test_role_propagation.py`)

Parametrized tests covering each field × component pair:

```python
@pytest.mark.parametrize("field,role_value,default_value", [
    ("model", "role-specific-model", "default-model"),
    ("temperature", 0.1, 0.7),
])
async def test_role_switch_propagates_to_llm_call(
    tmp_path, field, role_value, default_value
):
    """After role switching, the provider receives the role's values."""
    provider = ScriptedProvider([LLMResponse(content="ok")])
    loop = _make_loop(tmp_path, provider)

    role = AgentRoleConfig(name="test-role", description="", **{field: role_value})
    loop._role_manager.apply(role)
    # Propagate active settings
    loop._sync_active_settings()

    await loop.process_direct("hello")

    assert provider.call_log[0][field] == role_value
```

Test cases needed:

| Test | Asserts |
|------|---------|
| `test_role_model_reaches_provider` | `call_log[0]["model"] == role.model` |
| `test_role_temperature_reaches_provider` | `call_log[0]["temperature"] == role.temperature` |
| `test_role_max_iterations_respected` | Turn stops within role's `max_iterations` |
| `test_role_name_reaches_delegation_advisor` | Advisor receives role's name, not default |
| `test_role_reset_restores_defaults` | After `reset()`, next turn uses default model |
| `test_no_role_override_uses_defaults` | Without role switching, construction-time values used |
| `test_forced_role_propagates_to_provider` | `process_direct(forced_role=...)` propagates model/temperature |

### 7b: End-to-end smoke test

One test that wires everything via `build_agent()`, applies a role with distinct
model + temperature + max_iterations, runs a full turn through `ScriptedProvider`,
and asserts all three values reach the provider. This catches wiring regressions that
parametrized tests might miss.

---

## Section 8: Files changed

| File | Change |
|------|--------|
| `nanobot/agent/turn_types.py` | Add `active_model`, `active_temperature`, `active_max_iterations`, `active_role_name` to `TurnState`; add `set_active_settings` to `Processor` Protocol |
| `nanobot/agent/streaming.py` | Add optional `model`, `temperature` params to `call()`; update logging to use effective values |
| `nanobot/agent/turn_orchestrator.py` | Read active values from `TurnState`; pass to `llm_caller.call()`, verifier, reflect phase |
| `nanobot/agent/turn_phases.py` | `ReflectPhase.evaluate()` gains `role_name` param |
| `nanobot/agent/verifier.py` | Add optional `model`, `temperature` params to `verify()` and `attempt_recovery()` |
| `nanobot/agent/message_processor.py` | Add `set_active_settings()`; pass active values to `_run_orchestrator()`; fix audit logging and consolidation calls |
| `nanobot/agent/loop.py` | Call `processor.set_active_settings()` at both `run()` and `process_direct()` call sites, after role switching |
| `CLAUDE.md` | Add prohibited pattern + refactoring gate rule |
| `tests/contract/test_role_propagation.py` | New: seam contract tests |
| `tests/test_turn_orchestrator.py` | Update mocks to include active settings |
| `tests/test_message_processor.py` | Update mocks to include active settings |

## Section 9: What this does NOT change

- `DelegationDispatcher` — already handles `role.model or self.model` at `delegation.py:508`.
  Delegation has its own code path via `run_tool_loop()` and correctly resolves per-role models.
  No change needed.
- `ConsolidationOrchestrator` — receives `provider` and `model` as arguments to
  `submit()`/`consolidate_and_wait()`. No change to the consolidator itself; the fix
  is in `MessageProcessor` which passes `effective_model` instead of `self.model`
  (covered in Section 5).
- `TurnRoleManager` — no change. It continues to update `loop.*` fields. The difference
  is that downstream code now propagates those values explicitly rather than ignoring them.
- `agent_factory.py` — no structural change. Construction-time wiring remains the same;
  components still receive default values at construction.

---

## Out of scope

- Replacing `TurnRoleManager`'s `_LoopLike` Protocol with a richer interface. The Protocol
  is correct — it updates the loop's fields. The bug is in propagation, not in switching.
- Adding a static analysis check (AST scanner) for stale-field detection. The CLAUDE.md
  rule + integration tests provide sufficient coverage without exotic tooling.
- Changing `DelegationConfig` from frozen to mutable. Delegation already works correctly.
