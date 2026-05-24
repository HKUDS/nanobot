"""Tests for ``goal_state`` session metadata helpers."""

from __future__ import annotations

from nanobot.session.goal_state import (
    GOAL_STATE_KEY,
    discard_legacy_goal_state_key,
    goal_state_runtime_lines,
    goal_state_ws_blob,
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
        "ui_summary": "feat",
        "objective": "Build feature.",
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
