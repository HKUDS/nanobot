from __future__ import annotations

from nanobot.session.goal_state import (
    GOAL_STATE_KEY,
    MAX_GOAL_OBJECTIVE_CHARS,
    explicit_goal_requested,
    goal_state_runtime_lines,
    sustained_goal_active,
)


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


def test_sustained_goal_active_false_when_missing_or_completed():
    assert sustained_goal_active(None) is False
    assert sustained_goal_active({}) is False
    assert sustained_goal_active({GOAL_STATE_KEY: {"status": "completed", "objective": "x"}}) is False


def test_sustained_goal_active_true_when_active():
    meta = {GOAL_STATE_KEY: {"status": "active", "objective": "Run long task."}}
    assert sustained_goal_active(meta) is True


def test_explicit_goal_requested_only_reads_command_metadata():
    assert explicit_goal_requested({}) is False
    message_meta = {"original_command": "/goal", "goal_requested": True}
    assert explicit_goal_requested(message_meta) is True
