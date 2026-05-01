"""Unit tests for the tool-loop guardrail controller (#2298)."""

from __future__ import annotations

import json

import pytest

from nanobot.agent.tool_guardrails import (
    ToolCallGuardrailController,
    ToolGuardrailConfig,
    append_guidance,
    canonical_tool_args,
    synthetic_block_result,
)


def _make(**overrides) -> ToolCallGuardrailController:
    return ToolCallGuardrailController(ToolGuardrailConfig(**overrides))


def test_canonical_args_sorts_keys_for_stable_signature() -> None:
    assert canonical_tool_args({"b": 1, "a": 2}) == canonical_tool_args({"a": 2, "b": 1})


def test_first_failure_does_not_warn() -> None:
    c = _make()
    decision = c.after_call("read_file", {"path": "/x"}, "Error: nope", failed=True)
    assert decision.action == "allow"


def test_repeated_exact_failure_warns_after_threshold() -> None:
    c = _make(exact_failure_warn_after=2)
    args = {"path": "/x"}
    c.after_call("read_file", args, "Error: nope", failed=True)
    decision = c.after_call("read_file", args, "Error: nope", failed=True)
    assert decision.action == "warn"
    assert decision.code == "repeated_exact_failure_warning"
    assert decision.count == 2


def test_repeated_exact_failure_blocks_at_block_threshold() -> None:
    c = _make(exact_failure_block_after=3)
    args = {"path": "/x"}
    for _ in range(3):
        c.after_call("write_file", args, "Error: denied", failed=True)
    pre = c.before_call("write_file", args)
    assert pre.action == "block"
    assert pre.code == "repeated_exact_failure_block"
    assert c.halt_decision is not None


def test_block_disabled_when_hard_stop_disabled() -> None:
    c = _make(hard_stop_enabled=False, exact_failure_block_after=3)
    args = {"path": "/x"}
    for _ in range(5):
        c.after_call("write_file", args, "Error: denied", failed=True)
    pre = c.before_call("write_file", args)
    assert pre.action == "allow"
    assert c.halt_decision is None


def test_same_tool_failure_halts_across_different_args() -> None:
    c = _make(same_tool_failure_halt_after=3)
    for i in range(3):
        decision = c.after_call("exec", {"cmd": f"foo-{i}"}, "Error: fail", failed=True)
    assert decision.action == "halt"
    assert decision.code == "same_tool_failure_halt"
    assert decision.count == 3


def test_idempotent_no_progress_warns_when_same_result_repeats() -> None:
    c = _make(no_progress_warn_after=2)
    args = {"path": "/etc"}
    c.after_call("read_file", args, "hello", failed=False)
    decision = c.after_call("read_file", args, "hello", failed=False)
    assert decision.action == "warn"
    assert decision.code == "idempotent_no_progress_warning"
    assert decision.count == 2


def test_idempotent_no_progress_blocks_at_block_threshold() -> None:
    c = _make(no_progress_block_after=3)
    args = {"q": "foo"}
    for _ in range(3):
        c.after_call("web_search", args, '{"hits":[]}', failed=False)
    pre = c.before_call("web_search", args)
    assert pre.action == "block"
    assert pre.code == "idempotent_no_progress_block"


def test_mutating_tool_no_progress_does_not_warn() -> None:
    """write_file is mutating — even repeated identical success should not warn."""
    c = _make(no_progress_warn_after=2)
    args = {"path": "/x", "content": "hi"}
    decisions = [
        c.after_call("write_file", args, "ok", failed=False) for _ in range(5)
    ]
    assert all(d.action == "allow" for d in decisions)


def test_failure_then_success_resets_failure_counter() -> None:
    c = _make(exact_failure_warn_after=2, exact_failure_block_after=3)
    args = {"path": "/x"}
    c.after_call("read_file", args, "Error: nope", failed=True)
    c.after_call("read_file", args, "Error: nope", failed=True)  # would warn
    c.after_call("read_file", args, "ok", failed=False)
    pre = c.before_call("read_file", args)
    assert pre.action == "allow"


def test_reset_for_turn_clears_state() -> None:
    c = _make()
    c.after_call("exec", {"cmd": "x"}, "Error", failed=True)
    c.after_call("exec", {"cmd": "y"}, "Error", failed=True)
    c.reset_for_turn()
    decision = c.after_call("exec", {"cmd": "z"}, "Error", failed=True)
    assert decision.action == "allow"


def test_synthetic_block_result_returns_json_with_error() -> None:
    c = _make(exact_failure_block_after=1)
    args = {"path": "/x"}
    c.after_call("write_file", args, "Error", failed=True)
    pre = c.before_call("write_file", args)
    assert pre.should_halt
    body = synthetic_block_result(pre)
    parsed = json.loads(body)
    assert parsed["error"] == pre.message
    assert parsed["guardrail"]["code"] == "repeated_exact_failure_block"


def test_append_guidance_adds_warning_suffix() -> None:
    c = _make(exact_failure_warn_after=2)
    args = {"path": "/x"}
    c.after_call("read_file", args, "Error", failed=True)
    decision = c.after_call("read_file", args, "Error", failed=True)
    annotated = append_guidance("Error", decision)
    assert "[Tool loop warning:" in annotated
    assert "repeated_exact_failure_warning" in annotated


def test_append_guidance_noop_for_allow() -> None:
    c = _make()
    decision = c.after_call("read_file", {"path": "/x"}, "ok", failed=False)
    assert append_guidance("ok", decision) == "ok"


def test_config_from_mapping_overrides_thresholds() -> None:
    cfg = ToolGuardrailConfig.from_mapping({
        "warnings_enabled": False,
        "warn_after": {"exact_failure": 7},
        "hard_stop_after": {"same_tool_failure": 99},
    })
    assert cfg.warnings_enabled is False
    assert cfg.exact_failure_warn_after == 7
    assert cfg.same_tool_failure_halt_after == 99


def test_config_from_mapping_falls_back_to_defaults_for_invalid_values() -> None:
    cfg = ToolGuardrailConfig.from_mapping({
        "warn_after": {"exact_failure": -1},  # negative → ignored
        "warnings_enabled": "maybe",  # not parseable → default
    })
    defaults = ToolGuardrailConfig()
    assert cfg.exact_failure_warn_after == defaults.exact_failure_warn_after
    assert cfg.warnings_enabled == defaults.warnings_enabled


def test_loop_signature_unaffected_by_dict_key_order() -> None:
    """A real-world loop where the model alternates arg key order shouldn't
    bypass the no-progress detector."""
    c = _make(no_progress_warn_after=2)
    c.after_call("read_file", {"a": 1, "b": 2}, "data", failed=False)
    decision = c.after_call("read_file", {"b": 2, "a": 1}, "data", failed=False)
    assert decision.action == "warn"


def test_controller_does_not_crash_on_non_mapping_args() -> None:
    """Direct callers may pass list / None / scalars; controller must coerce
    silently rather than raising and tearing down the agent loop."""
    c = _make()
    # before_call / after_call already coerce internally; just verify the
    # public ``from_call`` path is also defensive (used by external callers).
    from nanobot.agent.tool_guardrails import ToolCallSignature

    sig_list = ToolCallSignature.from_call("read_file", ["not", "a", "mapping"])  # type: ignore[arg-type]
    sig_none = ToolCallSignature.from_call("read_file", None)
    sig_empty = ToolCallSignature.from_call("read_file", {})
    # All non-mapping inputs collapse to the same empty-args signature.
    assert sig_list.args_hash == sig_none.args_hash == sig_empty.args_hash

    # And the live observation methods don't crash either.
    assert c.before_call("read_file", "garbage").action == "allow"  # type: ignore[arg-type]
    assert c.after_call("read_file", None, "ok", failed=False).action == "allow"
