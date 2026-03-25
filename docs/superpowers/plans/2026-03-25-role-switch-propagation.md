# Role-Switch Field Propagation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix stale model/temperature/max_iterations/role_name in extracted components after role switching, using per-turn parameter passing.

**Architecture:** `TurnState` gains optional `active_*` fields populated by `MessageProcessor` from instance fields set by `AgentLoop`. Components read per-turn values with `is not None` fallback to construction-time defaults. Integration tests verify end-to-end propagation via `ScriptedProvider.call_log`.

**Tech Stack:** Python 3.10+, pytest, pytest-asyncio, dataclasses

**Spec:** `docs/superpowers/specs/2026-03-24-role-switch-propagation-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `nanobot/agent/turn_types.py` | Modify | Add `active_*` fields to `TurnState`; add `set_active_settings` to `Processor` Protocol |
| `nanobot/agent/streaming.py` | Modify | Add optional `model`/`temperature` params to `call()`; fix logging |
| `nanobot/agent/verifier.py` | Modify | Add optional `model`/`temperature` params to `verify()` and `attempt_recovery()` |
| `nanobot/agent/turn_phases.py` | Modify | Add `role_name` param to `ReflectPhase.evaluate()` |
| `nanobot/agent/turn_orchestrator.py` | Modify | Read active values from `TurnState`; pass to LLM caller, verifier, reflect phase |
| `nanobot/agent/message_processor.py` | Modify | Add `set_active_settings()`; populate `TurnState`; fix logging and consolidation |
| `nanobot/agent/loop.py` | Modify | Call `set_active_settings()` at both `run()` and `process_direct()` call sites |
| `CLAUDE.md` | Modify | Add prohibited pattern + refactoring gate rule |
| `tests/contract/test_role_propagation.py` | Create | Seam contract tests for field propagation |
| `tests/test_turn_orchestrator.py` | Modify | Update TurnState in test fixtures to include active fields |
| `tests/test_message_processor.py` | Modify | Update test fixtures for `set_active_settings()` |

---

### Task 1: Add `active_*` fields to `TurnState` and update `Processor` Protocol

**Files:**
- Modify: `nanobot/agent/turn_types.py:28-46` (TurnState dataclass)
- Modify: `nanobot/agent/turn_types.py:76-105` (Processor Protocol)
- Test: `tests/contract/test_role_propagation.py` (new)

- [ ] **Step 1: Write the failing test — TurnState accepts active fields**

Create `tests/contract/test_role_propagation.py`:

```python
"""Seam contract tests: role-switched values propagate to LLM provider."""

from __future__ import annotations

from nanobot.agent.turn_types import TurnState


def test_turn_state_accepts_active_fields():
    """TurnState dataclass has active_* fields with None defaults."""
    state = TurnState(messages=[], user_text="hello")
    assert state.active_model is None
    assert state.active_temperature is None
    assert state.active_max_iterations is None
    assert state.active_role_name is None

    state2 = TurnState(
        messages=[],
        user_text="hello",
        active_model="gpt-4o",
        active_temperature=0.1,
        active_max_iterations=3,
        active_role_name="code",
    )
    assert state2.active_model == "gpt-4o"
    assert state2.active_temperature == 0.1
    assert state2.active_max_iterations == 3
    assert state2.active_role_name == "code"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/contract/test_role_propagation.py::test_turn_state_accepts_active_fields -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'active_model'`

- [ ] **Step 3: Add active fields to TurnState**

In `nanobot/agent/turn_types.py`, add after `tools_def_snapshot` (line 45):

```python
    # Per-turn role overrides (None = use component construction-time defaults).
    # Set by MessageProcessor.set_active_settings() before each turn.
    active_model: str | None = None
    active_temperature: float | None = None
    active_max_iterations: int | None = None
    active_role_name: str | None = None
```

- [ ] **Step 4: Add `set_active_settings` to Processor Protocol**

In `nanobot/agent/turn_types.py`, add to the `Processor` Protocol after `set_classification_result`:

```python
    def set_active_settings(
        self,
        *,
        model: str,
        temperature: float,
        max_iterations: int,
        role_name: str,
    ) -> None: ...
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/contract/test_role_propagation.py::test_turn_state_accepts_active_fields -v`
Expected: PASS

- [ ] **Step 6: Run lint + typecheck**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add nanobot/agent/turn_types.py tests/contract/test_role_propagation.py
git commit -m "feat: add active_* fields to TurnState and Processor Protocol

Support per-turn role-switched overrides for model, temperature,
max_iterations, and role_name. None means use component defaults."
```

---

### Task 2: Add per-call overrides to `StreamingLLMCaller.call()`

**Files:**
- Modify: `nanobot/agent/streaming.py:72-179` (call method)
- Test: `tests/contract/test_role_propagation.py`

- [ ] **Step 1: Write the failing test — LLM caller uses override model**

Append to `tests/contract/test_role_propagation.py`:

```python
import pytest

from nanobot.providers.base import LLMResponse
from tests.helpers import ScriptedProvider


@pytest.mark.asyncio
async def test_llm_caller_uses_override_model():
    """StreamingLLMCaller.call() uses per-call model when provided."""
    from nanobot.agent.streaming import StreamingLLMCaller

    provider = ScriptedProvider([LLMResponse(content="ok")])
    caller = StreamingLLMCaller(
        provider=provider, model="default-model", temperature=0.7, max_tokens=4096
    )
    await caller.call([], None, None, model="override-model", temperature=0.1)
    assert provider.call_log[0]["model"] == "override-model"
    assert provider.call_log[0]["temperature"] == 0.1


@pytest.mark.asyncio
async def test_llm_caller_uses_defaults_when_no_override():
    """StreamingLLMCaller.call() uses construction-time defaults when no override."""
    from nanobot.agent.streaming import StreamingLLMCaller

    provider = ScriptedProvider([LLMResponse(content="ok")])
    caller = StreamingLLMCaller(
        provider=provider, model="default-model", temperature=0.7, max_tokens=4096
    )
    await caller.call([], None, None)
    assert provider.call_log[0]["model"] == "default-model"
    assert provider.call_log[0]["temperature"] == 0.7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/contract/test_role_propagation.py::test_llm_caller_uses_override_model -v`
Expected: FAIL with `TypeError: call() got an unexpected keyword argument 'model'`

- [ ] **Step 3: Add per-call overrides to `call()`**

Modify `nanobot/agent/streaming.py` — change `call()` signature (line 72) to:

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
```

Add at the top of the method body (after `t0 = time.monotonic()`):

```python
        effective_model = model if model is not None else self.model
        effective_temperature = (
            temperature if temperature is not None else self.temperature
        )
```

Replace all occurrences of `self.model` with `effective_model` and `self.temperature` with `effective_temperature` in:
- Non-streaming path: `self.provider.chat(...)` call (line 88-94) and log (line 100)
- Streaming path: `self.provider.stream_chat(...)` call (line 115-121) and log (line 165)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/contract/test_role_propagation.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run lint + typecheck**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nanobot/agent/streaming.py tests/contract/test_role_propagation.py
git commit -m "feat: add per-call model/temperature overrides to StreamingLLMCaller"
```

---

### Task 3: Add per-call overrides to `AnswerVerifier`

**Files:**
- Modify: `nanobot/agent/verifier.py:58-63` (verify signature)
- Modify: `nanobot/agent/verifier.py:205-211` (attempt_recovery signature)
- Test: `tests/contract/test_role_propagation.py`

- [ ] **Step 1: Write the failing test — verifier uses override model**

Append to `tests/contract/test_role_propagation.py`:

```python
@pytest.mark.asyncio
async def test_verifier_verify_uses_override_model():
    """AnswerVerifier.verify() passes override model to provider."""
    from nanobot.agent.verifier import AnswerVerifier

    provider = ScriptedProvider([
        LLMResponse(content='{"confidence": 5, "issues": []}'),
    ])
    verifier = AnswerVerifier(
        provider=provider, model="default-model", temperature=0.7,
        max_tokens=4096, verification_mode="always",
        memory_uncertainty_threshold=0.5,
    )
    await verifier.verify(
        "question?", "answer", [],
        model="override-model", temperature=0.2,
    )
    assert provider.call_log[0]["model"] == "override-model"


@pytest.mark.asyncio
async def test_verifier_recovery_uses_override_model():
    """AnswerVerifier.attempt_recovery() passes override model to provider."""
    from nanobot.agent.verifier import AnswerVerifier

    provider = ScriptedProvider([LLMResponse(content="recovered")])
    verifier = AnswerVerifier(
        provider=provider, model="default-model", temperature=0.7,
        max_tokens=4096, verification_mode="off",
        memory_uncertainty_threshold=0.5,
    )
    await verifier.attempt_recovery(
        channel="test", chat_id="test",
        all_msgs=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "question?"},
        ],
        model="override-model", temperature=0.2,
    )
    assert provider.call_log[0]["model"] == "override-model"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/contract/test_role_propagation.py::test_verifier_verify_uses_override_model -v`
Expected: FAIL with `TypeError: verify() got an unexpected keyword argument 'model'`

- [ ] **Step 3: Add overrides to `verify()` and `attempt_recovery()`**

Modify `verify()` signature in `nanobot/agent/verifier.py:58`:

```python
    async def verify(
        self,
        user_text: str,
        candidate: str,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float | None = None,
    ) -> tuple[str, list[dict]]:
```

Add at top of method (after the early returns for mode checks):

```python
        effective_model = model if model is not None else self.model
        effective_temperature = temperature if temperature is not None else self.temperature
```

Replace `self.model` with `effective_model` and `self.temperature` with `effective_temperature` in:
- Langfuse span metadata (line 89): `"model": effective_model`
- Critique `provider.chat()` call (line 95): `model=effective_model`
- Revision `provider.chat()` call (lines 131-132): `model=effective_model, temperature=effective_temperature`

Modify `attempt_recovery()` signature in `nanobot/agent/verifier.py:205`:

```python
    async def attempt_recovery(
        self,
        *,
        channel: str,
        chat_id: str,
        all_msgs: list[dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
    ) -> str | None:
```

Add after the message extraction:

```python
        effective_model = model if model is not None else self.model
        effective_temperature = temperature if temperature is not None else self.temperature
```

Replace `self.model` with `effective_model` and `self.temperature` with `effective_temperature` in the `provider.chat()` call (lines 242-244).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/contract/test_role_propagation.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run lint + typecheck**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nanobot/agent/verifier.py tests/contract/test_role_propagation.py
git commit -m "feat: add per-call model/temperature overrides to AnswerVerifier"
```

---

### Task 4: Add `role_name` parameter to `ReflectPhase.evaluate()`

**Files:**
- Modify: `nanobot/agent/turn_phases.py:325-331` (evaluate signature)
- Test: `tests/contract/test_role_propagation.py`

- [ ] **Step 1: Write the failing test — role_name reaches delegation advisor**

Append to `tests/contract/test_role_propagation.py`:

```python
from unittest.mock import MagicMock, patch


def test_reflect_phase_passes_role_name_to_advisor():
    """ReflectPhase.evaluate() passes per-call role_name to delegation advisor."""
    from nanobot.agent.turn_phases import ReflectPhase
    from nanobot.agent.turn_types import TurnState

    advisor = MagicMock()
    advisor.advise_reflect_phase.return_value = MagicMock(action="NONE")
    reflect = ReflectPhase(
        dispatcher=MagicMock(delegation_count=0, max_delegations=8),
        delegation_advisor=advisor,
        prompts=MagicMock(),
        role_name="default-role",
    )
    state = TurnState(messages=[], user_text="hello")
    response = MagicMock(tool_calls=[])

    reflect.evaluate(state, response, False, [], role_name="override-role")

    call_kwargs = advisor.advise_reflect_phase.call_args
    assert call_kwargs.kwargs.get("role_name") == "override-role"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/contract/test_role_propagation.py::test_reflect_phase_passes_role_name_to_advisor -v`
Expected: FAIL with `TypeError: evaluate() got an unexpected keyword argument 'role_name'`

- [ ] **Step 3: Add `role_name` parameter to `evaluate()`**

In `nanobot/agent/turn_phases.py`, modify the `evaluate()` signature (line 325):

```python
    def evaluate(
        self,
        state: TurnState,
        response: LLMResponse,
        any_failed: bool,
        failed_this_batch: list[tuple[str, FailureClass]],
        *,
        role_name: str | None = None,
    ) -> None:
```

Add at the top of the method body:

```python
        effective_role = role_name if role_name is not None else self._role_name
```

Replace `self._role_name` with `effective_role` in:
- `advise_reflect_phase()` call (line 343): `role_name=effective_role`

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/contract/test_role_propagation.py::test_reflect_phase_passes_role_name_to_advisor -v`
Expected: PASS

- [ ] **Step 5: Run lint + typecheck**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nanobot/agent/turn_phases.py tests/contract/test_role_propagation.py
git commit -m "feat: add per-call role_name to ReflectPhase.evaluate()"
```

---

### Task 5: Wire `TurnOrchestrator` to read from `TurnState` active fields

**Files:**
- Modify: `nanobot/agent/turn_orchestrator.py:118-409` (run method)
- Test: `tests/contract/test_role_propagation.py`

- [ ] **Step 1: Write the failing integration test**

Append to `tests/contract/test_role_propagation.py`:

```python
@pytest.mark.asyncio
async def test_orchestrator_passes_active_model_to_llm_caller(tmp_path):
    """TurnOrchestrator reads active_model from TurnState and passes to LLM caller."""
    from tests.helpers import ScriptedProvider, _make_loop

    provider = ScriptedProvider([LLMResponse(content="response")])
    loop = _make_loop(tmp_path, provider)

    state = TurnState(
        messages=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ],
        user_text="hello",
        active_model="role-specific-model",
        active_temperature=0.1,
        tools_def_cache=[],
    )
    await loop._processor.orchestrator.run(state, None)
    assert provider.call_log[0]["model"] == "role-specific-model"
    assert provider.call_log[0]["temperature"] == 0.1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/contract/test_role_propagation.py::test_orchestrator_passes_active_model_to_llm_caller -v`
Expected: FAIL (LLM caller receives `"test-model"` instead of `"role-specific-model"`)

- [ ] **Step 3: Wire TurnOrchestrator.run() to read from TurnState**

In `nanobot/agent/turn_orchestrator.py`, add at the top of `run()` (after the reset of per-turn accumulators, line 137):

```python
        # Resolve per-turn active settings (role-switched overrides).
        effective_model = (
            state.active_model if state.active_model is not None else self._model
        )
        effective_role_name = (
            state.active_role_name if state.active_role_name is not None
            else self._role_name
        )
        max_iterations = (
            state.active_max_iterations if state.active_max_iterations is not None
            else self._max_iterations
        )
```

Replace in `run()`:
- Line 162: `role_name=self._role_name` → `role_name=effective_role_name`
- Line 181: `state.iteration < self._max_iterations` → `state.iteration < max_iterations`
- Line 204: `or self._model` → `or effective_model`
- Lines 232-236: Pass model/temperature overrides to `self._llm_caller.call()`:

```python
            raw_response = await self._llm_caller.call(
                state.messages,
                active_tools,
                on_progress,
                model=state.active_model,
                temperature=state.active_temperature,
            )
```

- Line 350-355: Pass role_name to `self._reflect.evaluate()`:

```python
                self._reflect.evaluate(
                    state,
                    response,
                    batch.any_failed,
                    batch.failed_this_batch,
                    role_name=effective_role_name,
                )
```

- Lines 383-388: Replace `self._max_iterations` with `max_iterations` in the warning and message.

- Lines 392-397: Pass model/temperature to `self._verifier.verify()`:

```python
            final_content, state.messages = await self._verifier.verify(
                state.user_text,
                final_content,
                state.messages,
                model=state.active_model,
                temperature=state.active_temperature,
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/contract/test_role_propagation.py::test_orchestrator_passes_active_model_to_llm_caller -v`
Expected: PASS

- [ ] **Step 5: Run lint + typecheck**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add nanobot/agent/turn_orchestrator.py tests/contract/test_role_propagation.py
git commit -m "feat: TurnOrchestrator reads active_* from TurnState for LLM calls"
```

---

### Task 6: Add `set_active_settings()` to `MessageProcessor` and populate `TurnState`

**Files:**
- Modify: `nanobot/agent/message_processor.py:37-77` (add method + instance fields)
- Modify: `nanobot/agent/message_processor.py:370-411` (_run_orchestrator)
- Modify: `nanobot/agent/message_processor.py:264-274` (attempt_recovery call)
- Modify: `nanobot/agent/message_processor.py:206` (consolidation submit)
- Modify: `nanobot/agent/message_processor.py:301-330` (logging)
- Modify: `nanobot/agent/message_processor.py:486-493` (consolidation calls)

- [ ] **Step 1: Add `set_active_settings()` and instance fields**

In `nanobot/agent/message_processor.py`, after `self.classification_result` (line 74), add:

```python
        # Per-turn active settings (set by AgentLoop before each turn).
        self._active_model: str | None = None
        self._active_temperature: float | None = None
        self._active_max_iterations: int | None = None
        self._active_role_name: str | None = None
```

Add method after `set_classification_result()` (line 85):

```python
    def set_active_settings(
        self,
        *,
        model: str,
        temperature: float,
        max_iterations: int,
        role_name: str,
    ) -> None:
        """Forward role-switched settings for the upcoming turn."""
        self._active_model = model
        self._active_temperature = temperature
        self._active_max_iterations = max_iterations
        self._active_role_name = role_name
```

- [ ] **Step 2: Populate TurnState in `_run_orchestrator()`**

In `_run_orchestrator()` (line 390-395), modify the `TurnState` construction to include active fields:

```python
        state = TurnState(
            messages=messages,
            user_text=user_text,
            classification_result=self.classification_result,
            tools_def_cache=list(self.tools.get_definitions()),
            active_model=self._active_model,
            active_temperature=self._active_temperature,
            active_max_iterations=self._active_max_iterations,
            active_role_name=self._active_role_name,
        )
```

- [ ] **Step 3: Fix `attempt_recovery()` call to pass overrides**

In `_process_message()` (line 270-274), pass active values to recovery:

```python
            _recovered = await self.verifier.attempt_recovery(
                channel=msg.channel,
                chat_id=msg.chat_id,
                all_msgs=all_msgs,
                model=self._active_model,
                temperature=self._active_temperature,
            )
```

- [ ] **Step 4: Fix audit logging to use active values**

In `_process_message()`, replace stale `self.model` and `self.role_name` in the span metadata (line 306) and audit line (line 324):

```python
        effective_model = (
            self._active_model if self._active_model is not None else self.model
        )
        effective_role = (
            self._active_role_name if self._active_role_name is not None
            else self.role_name
        )
```

Use `effective_model` at lines 306, 324, and `effective_role` at lines 235, 307.

- [ ] **Step 5: Fix consolidation calls to use active model**

In `_process_message()` line 206:

```python
            self._consolidator.submit(session.key, session, self.provider, effective_model)
```

Note: `effective_model` must be computed before this line. Move the computation to the top of `_process_message()` (after `t0_request`).

In `_consolidate_memory()` (lines 489-492):

```python
        effective_model = (
            self._active_model if self._active_model is not None else self.model
        )
        if archive_all:
            return await self._consolidator.consolidate_and_wait(
                session.key, session, self.provider, effective_model, archive_all=True
            )
        self._consolidator.submit(session.key, session, self.provider, effective_model)
```

- [ ] **Step 6: Run lint + typecheck**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add nanobot/agent/message_processor.py
git commit -m "feat: MessageProcessor.set_active_settings() populates TurnState with role overrides"
```

---

### Task 7: Wire `AgentLoop` to call `set_active_settings()` at both call sites

**Files:**
- Modify: `nanobot/agent/loop.py:294-309` (run path)
- Modify: `nanobot/agent/loop.py:456-502` (process_direct path)
- Test: `tests/contract/test_role_propagation.py`

- [ ] **Step 1: Write the end-to-end integration tests**

Append to `tests/contract/test_role_propagation.py`. These tests use `loop.process_direct()`
(the public `AgentLoop` API) to exercise the full wiring path including `set_active_settings()`.

```python
@pytest.mark.asyncio
async def test_no_role_override_uses_defaults(tmp_path):
    """Without role switching, construction-time default model is used."""
    from tests.helpers import ScriptedProvider, _make_loop

    provider = ScriptedProvider([LLMResponse(content="response")])
    loop = _make_loop(tmp_path, provider)

    await loop.process_direct("hello")

    assert provider.call_log[0]["model"] == "test-model"


@pytest.mark.asyncio
async def test_forced_role_propagates_to_provider(tmp_path):
    """process_direct(forced_role=...) propagates the role's model to the provider."""
    from nanobot.config.schema import AgentRoleConfig
    from tests.helpers import ScriptedProvider, _make_loop

    provider = ScriptedProvider([LLMResponse(content="response")])
    loop = _make_loop(tmp_path, provider)

    # Register a role so forced_role can resolve it.
    # The coordinator is None in minimal test setup, so we wire it manually:
    # apply the role directly and call process_direct without forced_role to
    # exercise the set_active_settings wiring.
    role = AgentRoleConfig(name="code", description="", model="role-model", temperature=0.1)
    turn_ctx = loop._role_manager.apply(role)
    # After apply, loop.model is updated. Now call process_direct (no forced_role)
    # which should call set_active_settings with the loop's current values.
    await loop.process_direct("hello")
    loop._role_manager.reset(turn_ctx)

    assert provider.call_log[0]["model"] == "role-model"
    assert provider.call_log[0]["temperature"] == 0.1


@pytest.mark.asyncio
async def test_role_reset_restores_default_model(tmp_path):
    """After role reset, the next turn uses the default model."""
    from nanobot.config.schema import AgentRoleConfig
    from tests.helpers import ScriptedProvider, _make_loop

    provider = ScriptedProvider([
        LLMResponse(content="response1"),
        LLMResponse(content="response2"),
    ])
    loop = _make_loop(tmp_path, provider)

    # Turn 1: with role override
    role = AgentRoleConfig(name="code", description="", model="role-model")
    turn_ctx = loop._role_manager.apply(role)
    await loop.process_direct("turn1")
    loop._role_manager.reset(turn_ctx)

    # Turn 2: no role override — should use default
    await loop.process_direct("turn2")

    assert provider.call_log[0]["model"] == "role-model"
    assert provider.call_log[1]["model"] == "test-model"


@pytest.mark.asyncio
async def test_role_max_iterations_respected(tmp_path):
    """active_max_iterations limits the PAOR loop to the role's iteration count."""
    from nanobot.agent.turn_types import TurnState
    from nanobot.providers.base import LLMResponse, ToolCall
    from tests.helpers import ScriptedProvider, _make_loop

    # Script: 3 tool-call responses followed by a text response.
    # With max_iterations=1, only the first iteration should run.
    tool_call = ToolCall(id="t1", name="list_dir", arguments={"path": "."})
    provider = ScriptedProvider([
        LLMResponse(content=None, tool_calls=[tool_call]),
        LLMResponse(content=None, tool_calls=[tool_call]),
        LLMResponse(content="final"),
    ])
    loop = _make_loop(tmp_path, provider)

    state = TurnState(
        messages=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ],
        user_text="hello",
        active_max_iterations=1,
        tools_def_cache=list(loop._processor.tools.get_definitions()),
    )
    result = await loop._processor.orchestrator.run(state, None)

    # With max_iterations=1, the loop should have stopped after 1 iteration.
    # The result will be the max-iterations-reached message.
    assert "maximum number of tool call iterations (1)" in result.content
    assert result.llm_calls <= 1
```

- [ ] **Step 2: Run test to verify the end-to-end tests fail**

Run: `python -m pytest tests/contract/test_role_propagation.py::test_forced_role_propagates_to_provider -v`
Expected: FAIL (active settings not wired yet from loop)

- [ ] **Step 3: Wire `set_active_settings()` in `AgentLoop.run()` path**

In `nanobot/agent/loop.py`, after `turn_ctx = await self._classify_and_route(msg)` (line 294) and before the timeout/process block, add:

```python
                            # Propagate role-switched values to the processor
                            self._processor.set_active_settings(
                                model=self.model,
                                temperature=self.temperature,
                                max_iterations=self.max_iterations,
                                role_name=self.role_name,
                            )
```

- [ ] **Step 4: Wire `set_active_settings()` in `AgentLoop.process_direct()` path**

In `nanobot/agent/loop.py`, after `turn_ctx = self._role_manager.apply(role)` (line 481), add:

```python
            self._processor.set_active_settings(
                model=self.model,
                temperature=self.temperature,
                max_iterations=self.max_iterations,
                role_name=self.role_name,
            )
```

Also add the same call in the non-forced-role path (before the `trace_request` block) to ensure default values are synced:

```python
        # Always sync active settings (covers no-role and forced-role paths)
        self._processor.set_active_settings(
            model=self.model,
            temperature=self.temperature,
            max_iterations=self.max_iterations,
            role_name=self.role_name,
        )
```

- [ ] **Step 5: Run all contract tests**

Run: `python -m pytest tests/contract/test_role_propagation.py -v`
Expected: ALL PASS

- [ ] **Step 6: Run full test suite**

Run: `make test`
Expected: PASS (existing tests should not break since all new params are optional)

- [ ] **Step 7: Run lint + typecheck**

Run: `make lint && make typecheck`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add nanobot/agent/loop.py tests/contract/test_role_propagation.py
git commit -m "feat: AgentLoop syncs active settings to processor at both call sites"
```

---

### Task 8: Update existing test fixtures

**Files:**
- Modify: `tests/test_turn_orchestrator.py`
- Modify: `tests/test_message_processor.py`

- [ ] **Step 1: Update TurnState fixtures in test_turn_orchestrator.py**

Review `tests/test_turn_orchestrator.py` — any test that constructs a `TurnState` should continue to work since all new fields have `None` defaults. Verify no changes needed by running:

Run: `python -m pytest tests/test_turn_orchestrator.py -v`
Expected: PASS (all fields are optional with defaults)

If any test fails due to the new `model`/`temperature` keyword args on `llm_caller.call()`, update the `MagicMock` to accept them.

- [ ] **Step 2: Update MessageProcessor fixtures in test_message_processor.py**

If `test_message_processor.py` tests call `_process_message()` directly without calling `set_active_settings()` first, the `_active_*` fields will be `None` and the construction-time defaults will be used (which is the correct behavior for tests that don't test role switching). Verify:

Run: `python -m pytest tests/test_message_processor.py -v`
Expected: PASS

- [ ] **Step 3: Run full test suite**

Run: `make test`
Expected: ALL PASS

- [ ] **Step 4: Commit (if any fixtures needed updating)**

```bash
git add tests/test_turn_orchestrator.py tests/test_message_processor.py
git commit -m "test: update fixtures for per-turn active settings"
```

---

### Task 9: Add CLAUDE.md rules

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add prohibited pattern**

In `CLAUDE.md`, under **Prohibited Patterns > Wiring violations**, add:

```markdown
- Construction-time caching of role-switched fields (`model`, `temperature`,
  `max_iterations`, `role_name`) in extracted components without a per-turn
  override mechanism — components must accept per-turn values via `TurnState`
  or method parameters; construction-time values serve only as fallback defaults
```

- [ ] **Step 2: Add refactoring gate rule**

In `CLAUDE.md`, under **Before any structural refactoring**, add as item 6:

```markdown
6. **Check role-switched field propagation** — if the extracted component receives
   `model`, `temperature`, `max_iterations`, or `role_name` at construction time,
   verify that per-turn overrides from role switching reach the component. Add an
   integration test (see `tests/contract/test_role_propagation.py`) that wires real
   components via `build_agent()`, applies a role, runs a turn, and asserts the
   provider received the role's values.
```

- [ ] **Step 3: Run full validation**

Run: `make check`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add role-switch propagation rules to CLAUDE.md"
```

---

### Task 10: Final validation

- [ ] **Step 1: Run full CI check**

Run: `make check`
Expected: ALL PASS (lint + typecheck + import-check + prompt-check + test)

- [ ] **Step 2: Run contract tests in isolation**

Run: `python -m pytest tests/contract/test_role_propagation.py -v`
Expected: ALL PASS

- [ ] **Step 3: Verify no import boundary violations**

Run: `make import-check`
Expected: PASS

- [ ] **Step 4: Review git log**

Run: `git log --oneline -10`
Verify: 7-9 clean commits, one per task.
