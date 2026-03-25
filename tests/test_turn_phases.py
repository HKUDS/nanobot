"""Unit tests for turn_phases module helpers.

Tests the pure functions extracted from turn_orchestrator.py.
ActPhase and ReflectPhase integration is covered indirectly by
test_turn_orchestrator.py.
"""

from __future__ import annotations

import pytest

from nanobot.agent.turn_phases import _dynamic_preserve_recent, _needs_planning

# ---------------------------------------------------------------------------
# _needs_planning
# ---------------------------------------------------------------------------


class TestNeedsPlanning:
    """Heuristic planning detection for user messages."""

    def test_empty_string_returns_false(self) -> None:
        assert _needs_planning("") is False

    def test_short_greeting_returns_false(self) -> None:
        assert _needs_planning("Hello!") is False
        assert _needs_planning("Hi there") is False

    def test_multi_step_task_returns_true(self) -> None:
        assert _needs_planning("Please research the topic and then write a summary") is True

    def test_numbered_list_returns_true(self) -> None:
        assert _needs_planning("I need you to:\n1. Read the file\n2. Update it") is True

    def test_single_action_below_threshold(self) -> None:
        # Short but above greeting length, no planning signals
        assert _needs_planning("What is the weather today?") is False

    @pytest.mark.parametrize(
        "text",
        [
            "First read the config and then update it",
            "Create a new file and implement the feature",
            "Analyze the logs and compare with yesterday",
        ],
    )
    def test_various_planning_signals(self, text: str) -> None:
        assert _needs_planning(text) is True


# ---------------------------------------------------------------------------
# _dynamic_preserve_recent
# ---------------------------------------------------------------------------


class TestDynamicPreserveRecent:
    """Tail-message preservation count for context compression."""

    def test_short_history_returns_floor(self) -> None:
        messages: list[dict[str, str]] = [{"role": "user", "content": "hi"}]
        assert _dynamic_preserve_recent(messages) == 6

    def test_known_index_returns_correct_count(self) -> None:
        messages = [{"role": "user", "content": f"msg{i}"} for i in range(20)]
        # last_tool_call_idx=15 means 20 - 15 = 5 messages needed,
        # but floor is 6, so result is 6
        assert _dynamic_preserve_recent(messages, last_tool_call_idx=15) == 6

    def test_known_index_above_floor(self) -> None:
        messages = [{"role": "user", "content": f"msg{i}"} for i in range(20)]
        # last_tool_call_idx=10 means 20 - 10 = 10 messages needed
        assert _dynamic_preserve_recent(messages, last_tool_call_idx=10) == 10

    def test_known_index_capped(self) -> None:
        messages = [{"role": "user", "content": f"msg{i}"} for i in range(50)]
        # last_tool_call_idx=5 means 50 - 5 = 45, capped at 30
        assert _dynamic_preserve_recent(messages, last_tool_call_idx=5) == 30

    def test_scan_fallback_finds_tool_calls(self) -> None:
        messages: list[dict[str, object]] = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "ok", "tool_calls": [{"id": "1"}]},
            {"role": "tool", "content": "result"},
            {"role": "assistant", "content": "done"},
        ]
        # tool call at index 1, so needed = 4 - 1 = 3, floor = 6
        assert _dynamic_preserve_recent(messages) == 6

    def test_no_tool_calls_returns_floor(self) -> None:
        messages = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
        assert _dynamic_preserve_recent(messages) == 6
