"""Tests for ``thread_goal_state`` (runtime injection helpers)."""

from __future__ import annotations

from nanobot.agent.thread_goal_state import (
    THREAD_GOAL_KEY,
    parse_thread_goal,
    runtime_lines_for_metadata,
)


def test_runtime_lines_empty_when_no_metadata():
    assert runtime_lines_for_metadata(None) == []
    assert runtime_lines_for_metadata({}) == []


def test_runtime_lines_empty_when_completed():
    meta = {
        THREAD_GOAL_KEY: {"status": "completed", "objective": "was doing X"},
    }
    assert runtime_lines_for_metadata(meta) == []


def test_runtime_lines_include_objective_when_active():
    meta = {
        THREAD_GOAL_KEY: {
            "status": "active",
            "objective": "Ship the fix.",
            "ui_summary": "fix",
        },
    }
    lines = runtime_lines_for_metadata(meta)
    assert "Thread goal (active):" in lines
    assert "Ship the fix." in lines
    assert any("Summary: fix" in ln for ln in lines)


def test_parse_thread_goal_accepts_json_string():
    assert parse_thread_goal('{"status":"active","objective":"x"}') == {
        "status": "active",
        "objective": "x",
    }
