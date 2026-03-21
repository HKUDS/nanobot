# Test Coverage for Newly Extracted Loop Modules

**Date:** 2026-03-21
**Status:** Draft
**Scope:** Dedicated unit tests for `role_switching.py`, `verifier.py`, `tool_setup.py`

## Problem

The LAN-213 through LAN-216 refactoring commits extracted three modules from
`AgentLoop` but left them without dedicated test files. They are only tested
indirectly through `test_agent_loop.py` and `test_loop_run_verify_paths.py`.
This creates compounding risk: further extractions from `loop.py` move logic
into modules whose contracts are not independently verified.

The project's own refactoring principles state "tests first, then extract."
This spec retrofits the missing test coverage to unblock continued safe
decomposition.

## Approach

Three new test files, one per module. Each tests the module's public interface
in isolation using lightweight fakes — no `AgentLoop` instantiation needed.

Follows existing conventions:
- `ScriptedProvider` from `tests/helpers.py` for async LLM paths
- `pytest-asyncio` auto mode for async tests
- `@pytest.mark.parametrize` for variant coverage
- `tmp_path` fixture for filesystem needs

## Module 1: `test_role_switching.py`

**Target:** `nanobot/agent/role_switching.py` (132 lines)
**Nature:** Pure synchronous state machine, no I/O

### Test fixture: `FakeLoop`

A minimal dataclass satisfying the `_LoopLike` protocol:

```python
@dataclass
class FakeLoop:
    model: str = "default-model"
    temperature: float = 0.7
    max_iterations: int = 10
    role_name: str = "general"
    role_config: AgentRoleConfig | None = None
    context: Any = None       # stub with role_system_prompt attr
    tools: Any = None         # stub with snapshot/restore/unregister/tool_names
    _dispatcher: Any = None   # stub with role_name attr
    _capabilities: Any = None
    exec_config: Any = None
```

Plus `FakeContext` (holds `role_system_prompt: str`), `FakeTools` (dict-backed
stub implementing `snapshot`, `restore`, `unregister`, `tool_names`), and
`FakeDispatcher` (holds `role_name: str`). The `role_config` attribute should
be a stub with a `.name` attribute (used by `reset` to restore `role_name`).

### Test cases (~10 tests)

| Test | What it verifies |
|------|-----------------|
| `test_apply_captures_snapshot` | `TurnContext` contains original model/temp/iterations/prompt |
| `test_apply_overrides_model` | `loop.model` updated to role's model |
| `test_apply_overrides_temperature` | `loop.temperature` updated |
| `test_apply_overrides_max_iterations` | `loop.max_iterations` updated |
| `test_apply_sets_role_system_prompt` | `loop.context.role_system_prompt` set from role |
| `test_apply_syncs_dispatcher_role_name` | `loop._dispatcher.role_name` matches role |
| `test_apply_no_model_override_preserves_default` | Role with `model=None` leaves loop.model unchanged |
| `test_filter_tools_allowed_whitelist` | Only allowed tools remain |
| `test_filter_tools_denied_blacklist` | Denied tools removed, others kept |
| `test_filter_tools_noop_when_unset` | No allowed/denied → no filtering, `ctx.tools` is None |
| `test_reset_restores_all_values` | After apply+reset, all loop attrs back to original |
| `test_reset_none_is_noop` | `reset(None)` does not touch loop |
| `test_reset_skips_tool_restore_when_no_filtering` | `ctx.tools is None` → `restore()` not called |

## Module 2: `test_verifier.py`

**Target:** `nanobot/agent/verifier.py` (317 lines)
**Nature:** Mixed — async LLM calls + pure helper methods

### Test fixture

Construct `AnswerVerifier` directly with `ScriptedProvider`. No `AgentLoop`.
Mock `langfuse_span` and `score_current_trace` to no-ops (they are observability
side-effects, not behavior under test).

### Test cases (~15 tests)

#### `verify()` paths

| Test | Setup | Assertion |
|------|-------|-----------|
| `test_verify_off_passthrough` | mode="off" | Returns candidate unchanged, no LLM call |
| `test_verify_on_uncertainty_skips_non_question` | mode="on_uncertainty", text="hello" | Passthrough |
| `test_verify_always_high_confidence_passes` | critique returns `{"confidence": 5, "issues": []}` | Returns candidate unchanged |
| `test_verify_always_low_confidence_revises` | critique returns `{"confidence": 1, "issues": ["wrong"]}` | Returns revised content from second LLM call |
| `test_verify_issues_injected_as_system_message` | Low confidence | System message with issues appended to messages list |
| `test_verify_unparseable_json_passthrough` | Critique returns "not json" | Returns candidate (crash-barrier) |
| `test_verify_llm_exception_passthrough` | Provider raises `RuntimeError` | Returns candidate (crash-barrier) |

#### `_looks_like_question()` (static, parametrized)

| Input | Expected |
|-------|----------|
| `"What is X?"` | `True` |
| `"how do I..."` | `True` |
| `"Hello"` | `False` |
| `""` | `False` |
| `"Save this note"` | `False` |
| `"is it ready?"` | `True` |

#### `_estimate_grounding_confidence()`

| Test | Setup | Expected |
|------|-------|----------|
| `test_no_memory_returns_zero` | `_memory=None` | `0.0` |
| `test_empty_results_returns_zero` | Memory returns `[]` | `0.0` |
| `test_score_clamped_to_unit_interval` | Score `1.5` | `1.0` |
| `test_memory_exception_returns_zero` | Memory raises | `0.0` |

#### `attempt_recovery()`

| Test | Setup | Assertion |
|------|-------|-----------|
| `test_recovery_success` | Provider returns content | Returns content string |
| `test_recovery_missing_messages` | Missing system or user message (e.g., only tool-role messages) | Returns `None` |
| `test_recovery_llm_error` | Provider raises | Returns `None` |
| `test_recovery_error_finish_reason` | `finish_reason="error"` | Returns `None` |

#### `build_no_answer_explanation()` (static, parametrized)

| Test | Tool results | Expected substring |
|------|-------------|-------------------|
| `test_no_tool_results` | `[]` | "did not produce" |
| `test_exit_code_error` | `[{content: "exit code: 1"}]` | "no matching data" |
| `test_permission_denied` | `[{content: "permission denied"}]` | "permission error" |
| `test_question_input` | user_text="What is X?" | "rephrasing" |
| `test_statement_input` | user_text="My name is Y" | "share the fact" |

## Module 3: `test_tool_setup.py`

**Target:** `nanobot/agent/tool_setup.py` (203 lines)
**Nature:** Pure synchronous construction, no async

### Test fixture

Build a real `ToolExecutor` backed by a real `ToolRegistry`. Use `tmp_path` for
workspace. Provide minimal stubs for:

- `ExecToolConfig(timeout=30)`
- `SkillsLoader` that returns an empty list from `discover_tools()`
- `MissionManager` — a `Mock()` (never called, just passed as constructor arg)
- `ToolResultCache` — a `Mock()` (same)
- `publish_outbound` — an async no-op

### Test cases (~7 tests)

| Test | Setup | Assertion |
|------|-------|-----------|
| `test_default_tools_registered` | No allow/deny, delegation on | All expected tool names present |
| `test_expected_tool_count` | Default config | Tool count matches expected number (audit `tool_setup.py` at current commit to derive the number) |
| `test_allowed_tools_whitelist` | `allowed_tools=["exec", "read_file"]` | Only those two registered |
| `test_denied_tools_blacklist` | `denied_tools=["exec"]` | exec absent, all others present |
| `test_delegation_disabled_skips_tools` | `delegation_enabled=False` | No delegate/mission tools |
| `test_no_cron_service_skips_cron` | `cron_service=None` | No cron tool |
| `test_skills_tools_discovered` | `SkillsLoader` returns 1 tool | That tool registered |

## Out of Scope

- Changes to production code
- Tests for `consolidation.py`, `context_assembler.py`, `retrieval_planner.py`
  (future work, different extraction campaign)
- Integration tests that spin up `AgentLoop`

## Estimated Size

~32 tests across ~450 lines of test code, split into 3 files.
