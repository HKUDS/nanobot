# Phase 3: Rewire the Loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace TurnOrchestrator with TurnRunner — a simplified loop that integrates the guardrail checkpoint, working memory (ToolAttempt logging), and configurable self-check. Delete the old orchestrator, ActPhase, and AnswerVerifier.

**Architecture:** TurnRunner implements the same `Orchestrator` protocol as TurnOrchestrator, so the swap is transparent to MessageProcessor and AgentLoop. The factory constructs TurnRunner instead of TurnOrchestrator. Feature-flag cutover for safety.

**Tech Stack:** Python 3.10+, ruff, mypy, pytest

**Spec:** `docs/superpowers/specs/2026-03-27-agent-cognitive-redesign.md`, Phase 3 + Section 2 (Cognitive Loop)

**Risk:** Medium. This replaces the core execution engine. Feature-flag approach mitigates: both implementations coexist until the new one passes all tests.

---

## File Map

### Files to CREATE

| File | LOC Target | Purpose |
|------|-----------|---------|
| `nanobot/agent/turn_runner.py` | ~250 | New cognitive loop with guardrail checkpoints + self-check |
| `tests/test_turn_runner.py` | ~300 | Contract tests + integration tests for the new loop |

### Files to MODIFY

| File | Change |
|------|--------|
| `nanobot/agent/agent_factory.py` | Construct TurnRunner + GuardrailChain instead of TurnOrchestrator |
| `nanobot/agent/turn_types.py` | Add `tool_results_log` field to TurnState, add `guardrail_log` to TurnResult |
| `nanobot/agent/__init__.py` | Update exports if needed |

### Files to DELETE (after cutover)

| File | LOC | Reason |
|------|-----|--------|
| `nanobot/agent/turn_orchestrator.py` | 392 | Replaced by turn_runner.py |
| `nanobot/agent/turn_phases.py` | 283 | ActPhase inlined into TurnRunner |
| `nanobot/agent/verifier.py` | 475 | Replaced by inline self-check |

---

## Tasks

### Task 1: Add working memory fields to TurnState

**Files:**
- Modify: `nanobot/agent/turn_types.py`

- [ ] **Step 1: Add tool_results_log to TurnState**

In `nanobot/agent/turn_types.py`, add `tool_results_log` field to the `TurnState` dataclass.
Also add a `guardrail_activations` field for tracking which guardrails fired (needed for
procedural memory extraction in Phase 5).

```python
# Add to TurnState, after existing fields:
    tool_results_log: list[ToolAttempt] = field(default_factory=list)
    guardrail_activations: list[dict] = field(default_factory=list)
```

Import `field` from dataclasses if not already imported. Import `ToolAttempt` — it's
already defined in this file (added in Phase 2).

- [ ] **Step 2: Run make lint && make typecheck**

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(agent): add working memory fields to TurnState"
```

---

### Task 2: Create TurnRunner

This is the core task. Create the new loop alongside the existing TurnOrchestrator.

**Files:**
- Create: `nanobot/agent/turn_runner.py`

- [ ] **Step 1: Create turn_runner.py**

The TurnRunner must:
1. Implement the `Orchestrator` protocol from `turn_types.py` (same `run()` signature)
2. Keep ALL existing loop mechanics from TurnOrchestrator:
   - Wall-time guardrail
   - Context compression
   - Tool definition filtering (disabled tools)
   - LLM call (streaming when progress callback exists)
   - LLM error handling (the `_handle_llm_error` method)
   - Malformed tool call filtering
   - Final answer nudge (when empty response after tool calls)
   - Max iterations fallback
   - Token accumulation
3. ADD these new capabilities:
   - GuardrailChain checkpoint after each tool execution batch
   - ToolAttempt logging to `state.tool_results_log` after each tool execution
   - Configurable self-check (replaces AnswerVerifier)
   - Langfuse observability for guardrail activations
4. INLINE the ActPhase tool execution logic (don't delegate to a separate class)

**Constructor parameters** (6, under the 7 limit):
```python
def __init__(
    self,
    *,
    llm_caller: StreamingLLMCaller,
    tool_executor: ToolExecutor,
    guardrails: GuardrailChain,
    context: ContextBuilder,
    config: AgentConfig,
    provider: LLMProvider | None = None,
) -> None:
```

**Key design rules:**
- Start with `from __future__ import annotations`
- Import `GuardrailChain`, `Intervention` from `turn_guardrails`
- Import `ToolAttempt` from `turn_types`
- The loop body follows the spec pseudocode exactly
- Tool execution is inlined from `ActPhase.execute_tools()` (copy the core logic: add
  assistant message, execute batch, add tool results, track failures, handle skill content)
- After tool execution, build `ToolAttempt` records and append to `state.tool_results_log`
- After ToolAttempt logging, call `self._guardrails.check(state.tool_results_log, latest_attempts, iteration=state.iteration)`
- If intervention returned, inject as system message and log to `state.guardrail_activations`
- Self-check: read `verification_mode` from config. If "structured", do one extra LLM call.
  If "off" or default, skip (prompt-only self-check is in the system prompt, not code).
- Target: ~250 LOC

**What NOT to include:**
- No planning logic, no plan enforcement
- No delegation advisor
- No ReflectPhase
- No role switching
- No `PromptLoader` dependency (prompts used inline or from config)

- [ ] **Step 2: Run make lint && make typecheck**

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(agent): add TurnRunner with guardrail checkpoints and self-check"
```

---

### Task 3: Write TurnRunner tests

**Files:**
- Create: `tests/test_turn_runner.py`

- [ ] **Step 1: Write contract tests**

Using the `ScriptedProvider` pattern from existing tests (see `tests/test_agent_loop.py`
for the mock pattern). Tests needed:

```
test_loop_terminates_within_max_iterations
  — Set max_iterations=3, provider always returns tool calls. Verify iteration <= 3.

test_empty_response_triggers_final_answer_nudge
  — Provider returns tool calls, then empty response. Verify nudge injected.

test_text_response_breaks_loop
  — Provider returns text (no tool calls). Verify loop exits with content.

test_tool_results_logged_to_working_memory
  — Provider returns one tool call. Verify state.tool_results_log has one ToolAttempt.

test_guardrail_intervention_injected_as_system_message
  — Use a mock GuardrailChain that always returns an Intervention.
    Verify a system message with the intervention content appears in messages.

test_guardrail_activation_logged
  — Same as above. Verify state.guardrail_activations has one entry.

test_disabled_tools_excluded_from_definitions
  — Add a tool name to state.disabled_tools. Verify it's not in the tool definitions
    passed to the LLM.

test_structured_self_check_calls_llm
  — Set verification_mode="structured". Verify an extra LLM call is made after the loop.

test_no_self_check_by_default
  — Default config. Verify no extra LLM call after the loop.
```

- [ ] **Step 2: Run tests (should fail — TurnRunner exists but isn't wired)**

- [ ] **Step 3: Fix any test issues**

- [ ] **Step 4: Commit**

```bash
git commit -m "test(agent): add TurnRunner contract tests"
```

---

### Task 4: Wire TurnRunner into factory with feature flag

**Files:**
- Modify: `nanobot/agent/agent_factory.py`

- [ ] **Step 1: Add feature flag and TurnRunner construction**

In `build_agent()`, after the existing TurnOrchestrator construction:

```python
# Feature flag: use new TurnRunner when enabled
_use_turn_runner = getattr(config, "use_turn_runner", False)
if _use_turn_runner:
    from nanobot.agent.turn_guardrails import (
        EmptyResultRecovery,
        FailureEscalation,
        GuardrailChain,
        NoProgressBudget,
        RepeatedStrategyDetection,
        SkillTunnelVision,
    )
    from nanobot.agent.turn_runner import TurnRunner

    guardrails = GuardrailChain([
        FailureEscalation(),
        NoProgressBudget(),
        RepeatedStrategyDetection(),
        EmptyResultRecovery(),
        SkillTunnelVision(),
    ])
    orchestrator = TurnRunner(
        llm_caller=llm_caller,
        tool_executor=tools,
        guardrails=guardrails,
        context=context,
        config=config,
        provider=provider,
    )
else:
    # Existing TurnOrchestrator (will be removed after cutover)
    orchestrator = TurnOrchestrator(...)
```

Both implement the `Orchestrator` protocol, so the rest of the factory doesn't change.

- [ ] **Step 2: Run make lint && make typecheck**

- [ ] **Step 3: Run make test to verify existing tests still pass**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(agent): wire TurnRunner with feature flag in factory"
```

---

### Task 5: Cut over — make TurnRunner the default

**Files:**
- Modify: `nanobot/agent/agent_factory.py` — remove feature flag, always use TurnRunner
- Delete: `nanobot/agent/turn_orchestrator.py`
- Delete: `nanobot/agent/turn_phases.py`
- Delete: `nanobot/agent/verifier.py`
- Modify: `nanobot/agent/__init__.py` — update exports (remove AnswerVerifier if exported)
- Modify: various test files — remove references to deleted modules

- [ ] **Step 1: Make TurnRunner the default in factory**

Remove the feature flag. Always construct TurnRunner. Remove TurnOrchestrator construction
code and its imports.

- [ ] **Step 2: Delete old files**

```bash
rm nanobot/agent/turn_orchestrator.py
rm nanobot/agent/turn_phases.py
rm nanobot/agent/verifier.py
```

- [ ] **Step 3: Clean imports across codebase**

Search for and remove all imports from deleted modules:
```bash
grep -rn "turn_orchestrator\|turn_phases\|from nanobot.agent.verifier" nanobot/ tests/ --include="*.py"
```

Also grep for class names: `TurnOrchestrator`, `ActPhase`, `AnswerVerifier`, `ToolBatchResult`.

Clean each file found. For test files that test deleted classes, either:
- Delete the test file entirely (if it only tests deleted code)
- Remove specific test functions/classes that test deleted code

Key test files to check:
- `tests/test_turn_orchestrator.py` — DELETE entirely
- `tests/test_turn_phases.py` — DELETE (ActPhase tests, but ActPhase is inlined)
- `tests/test_coverage_push_wave6.py` — remove references to deleted code
- `tests/test_agent_loop.py` — may reference TurnOrchestrator or AnswerVerifier
- `tests/test_agent_factory.py` — update for TurnRunner construction

- [ ] **Step 4: Update __init__.py exports**

If `AnswerVerifier` is in `nanobot/agent/__init__.py` exports, remove it.

- [ ] **Step 5: Clear mypy cache and run full validation**

```bash
rm -rf .mypy_cache
make lint && make typecheck
```

- [ ] **Step 6: Run full test suite**

```bash
python -m pytest tests/ --ignore=tests/integration -x -q
```

- [ ] **Step 7: Commit**

```bash
git commit -m "refactor(agent): replace TurnOrchestrator with TurnRunner

Delete turn_orchestrator.py (392 LOC), turn_phases.py (283 LOC), and
verifier.py (475 LOC). TurnRunner is now the default cognitive loop
with guardrail checkpoints and configurable self-check.

Part of Phase 3: agent cognitive core redesign (rewire the loop)."
```

---

### Task 6: Final validation

- [ ] **Step 1: Run make pre-push**

```bash
rm -rf .mypy_cache && make pre-push
```

- [ ] **Step 2: Verify LOC reduction**

```bash
wc -l nanobot/agent/turn_runner.py
# Expected: ~250 LOC (replacing 392 + 283 + 475 = 1,150 LOC)
```

- [ ] **Step 3: Verify no stale references**

```bash
grep -rn "TurnOrchestrator\|ActPhase\|AnswerVerifier\|ReflectPhase\|turn_orchestrator\|turn_phases" nanobot/ --include="*.py" | grep -v __pycache__
```
Expected: No matches in production code.

---

## Summary

| Task | Files Changed | Estimated Effort |
|------|--------------|-----------------|
| 1. Add working memory fields to TurnState | 1 modified | 5 min |
| 2. Create TurnRunner | 1 created | 45 min |
| 3. Write TurnRunner tests | 1 created | 30 min |
| 4. Wire with feature flag | 1 modified | 15 min |
| 5. Cut over + delete old files | 3 deleted, 5+ modified | 30 min |
| 6. Final validation | 0 | 10 min |
| **Total** | **2 created, 3 deleted, 7+ modified** | **~2.5 hours** |
