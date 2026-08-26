"""Tests for ``goal_state`` session metadata helpers."""

from __future__ import annotations

from nanobot.session.goal_state import (
    GOAL_STATE_KEY,
    MAX_GOAL_OBJECTIVE_CHARS,
    discard_legacy_goal_state_key,
    explicit_goal_requested,
    goal_state_runtime_lines,
    goal_state_ws_blob,
    had_goal_completion_attempt,
    parse_goal_state,
    runner_wall_llm_timeout_s,
    sustained_goal_active,
)
from nanobot.session.manager import SessionManager


def test_runtime_lines_empty_when_no_metadata():
    assert goal_state_runtime_lines(None) == []
    assert goal_state_runtime_lines({}) == []


def test_runtime_lines_empty_when_completed():
    meta = {
        GOAL_STATE_KEY: {"status": "completed", "objective": "was doing X"},
    }
    assert goal_state_runtime_lines(meta) == []


def test_runtime_lines_include_objective_when_active():
    meta = {
        GOAL_STATE_KEY: {
            "status": "active",
            "objective": "Ship the fix.",
            "ui_summary": "fix",
        },
    }
    lines = goal_state_runtime_lines(meta)
    assert "Goal (active):" in lines
    assert "Ship the fix." in lines
    assert any("Summary: fix" in ln for ln in lines)


def test_runtime_lines_preserve_maximum_accepted_objective():
    objective = "x" * MAX_GOAL_OBJECTIVE_CHARS

    lines = goal_state_runtime_lines(
        {GOAL_STATE_KEY: {"status": "active", "objective": objective}}
    )

    assert lines == ["Goal (active):", objective]


def test_runtime_lines_read_legacy_thread_goal_key():
    meta = {"thread_goal": {"status": "active", "objective": "Legacy key.", "ui_summary": "L"}}
    lines = goal_state_runtime_lines(meta)
    assert "Legacy key." in lines


def test_goal_state_key_takes_precedence_over_legacy():
    meta = {
        GOAL_STATE_KEY: {"status": "active", "objective": "New key wins.", "ui_summary": "n"},
        "thread_goal": {"status": "active", "objective": "Ignored.", "ui_summary": "o"},
    }
    lines = goal_state_runtime_lines(meta)
    assert "New key wins." in lines
    assert "Ignored." not in "".join(lines)


def test_discard_legacy_goal_state_key():
    meta: dict = {"thread_goal": {"x": 1}, GOAL_STATE_KEY: {"status": "active"}}
    discard_legacy_goal_state_key(meta)
    assert "thread_goal" not in meta
    assert GOAL_STATE_KEY in meta


def test_parse_goal_state_accepts_json_string():
    assert parse_goal_state('{"status":"active","objective":"x"}') == {
        "status": "active",
        "objective": "x",
    }


def test_goal_state_ws_blob_inactive_when_missing_or_completed():
    assert goal_state_ws_blob(None) == {"active": False}
    assert goal_state_ws_blob({}) == {"active": False}
    assert goal_state_ws_blob({GOAL_STATE_KEY: {"status": "completed", "objective": "x"}}) == {
        "active": False,
    }


def test_goal_state_ws_blob_active_shape():
    meta = {
        GOAL_STATE_KEY: {
            "status": "active",
            "objective": "Build feature.",
            "ui_summary": "feat",
        },
    }
    assert goal_state_ws_blob(meta) == {
        "active": True,
        "status": "active",
        "ui_summary": "feat",
        "objective": "Build feature.",
    }


def test_goal_state_ws_blob_preserves_blocked_state_for_host_attention():
    meta = {
        GOAL_STATE_KEY: {
            "status": "blocked",
            "objective": "Deploy safely.",
            "ui_summary": "Approval required",
            "recap": "Production access is required.",
        },
    }
    assert goal_state_ws_blob(meta) == {
        "active": False,
        "status": "blocked",
        "ui_summary": "Approval required",
        "objective": "Deploy safely.",
        "recap": "Production access is required.",
    }


def test_sustained_goal_active_false_when_missing_or_completed():
    assert sustained_goal_active(None) is False
    assert sustained_goal_active({}) is False
    assert sustained_goal_active({GOAL_STATE_KEY: {"status": "completed", "objective": "x"}}) is False


def test_sustained_goal_active_true_when_active():
    meta = {GOAL_STATE_KEY: {"status": "active", "objective": "Run long task."}}
    assert sustained_goal_active(meta) is True


def test_sustained_goal_active_respects_legacy_thread_goal_key():
    meta = {"thread_goal": {"status": "active", "objective": "Legacy."}}
    assert sustained_goal_active(meta) is True


def _assistant_call(name: str, arguments: object) -> dict:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": name, "arguments": arguments}}
        ],
    }


def test_goal_completion_attempt_detects_update_goal_complete():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "start"},
        _assistant_call("update_goal", '{"action": "complete", "recap": "done"}'),
        {"role": "tool", "tool_call_id": "call_1", "name": "update_goal",
         "content": "Error: action is required"},
    ]
    assert had_goal_completion_attempt(messages) is True


def test_goal_completion_attempt_accepts_dict_arguments():
    messages = [
        _assistant_call("update_goal", {"action": "complete", "recap": "done"}),
    ]
    assert had_goal_completion_attempt(messages) is True


def test_goal_completion_attempt_detects_complete_goal_alias():
    # Third-party models emit complete_goal even though it is not registered.
    messages = [_assistant_call("complete_goal", '{"recap": "done"}')]
    assert had_goal_completion_attempt(messages) is True


def test_goal_completion_attempt_ignores_non_complete_update_goal():
    messages = [_assistant_call("update_goal", '{"action": "cancel", "recap": "stop"}')]
    assert had_goal_completion_attempt(messages) is False


def test_goal_completion_attempt_ignores_other_tools():
    messages = [
        _assistant_call("read_file", '{"path": "a.py"}'),
        {"role": "assistant", "content": "working"},
    ]
    assert had_goal_completion_attempt(messages) is False


def test_goal_completion_attempt_malformed_arguments_is_safe():
    assert had_goal_completion_attempt([_assistant_call("update_goal", "{not json")]) is False
    assert had_goal_completion_attempt([_assistant_call("update_goal", None)]) is False


def test_goal_completion_attempt_empty_or_none_inputs():
    assert had_goal_completion_attempt(None) is False
    assert had_goal_completion_attempt([]) is False
    assert had_goal_completion_attempt([{"role": "assistant", "content": "no tools"}]) is False


def test_explicit_goal_requested_only_reads_command_metadata():
    assert explicit_goal_requested({}) is False
    message_meta = {"original_command": "/goal", "goal_requested": True}
    assert explicit_goal_requested(message_meta) is True


def test_runner_wall_llm_timeout_uses_metadata_override(tmp_path):
    sm = SessionManager(tmp_path)
    assert (
        runner_wall_llm_timeout_s(
            sm,
            "cli:test",
            metadata={GOAL_STATE_KEY: {"status": "active", "objective": "x"}},
        )
        == 0.0
    )
    assert runner_wall_llm_timeout_s(sm, "cli:test", metadata={}) is None


def test_runner_wall_llm_timeout_reads_session_when_metadata_missing(tmp_path):
    sm = SessionManager(tmp_path)
    sess = sm.get_or_create("c:d")
    sess.metadata = {GOAL_STATE_KEY: {"status": "active", "objective": "z"}}
    assert runner_wall_llm_timeout_s(sm, "c:d") == 0.0
    sess.metadata = {}
    assert runner_wall_llm_timeout_s(sm, "c:d") is None
