"""Tests for ToolCallTracker — infinite loop breaker."""

from __future__ import annotations

from nanobot.agent.loop import ToolCallTracker


def test_first_failure_returns_one() -> None:
    tracker = ToolCallTracker()
    assert tracker.record_failure("read_file", {"path": "/a"}) == 1
    assert tracker.total_failures == 1


def test_identical_failures_accumulate() -> None:
    tracker = ToolCallTracker()
    tracker.record_failure("read_file", {"path": "/a"})
    assert tracker.record_failure("read_file", {"path": "/a"}) == 2
    assert tracker.record_failure("read_file", {"path": "/a"}) == 3
    assert tracker.total_failures == 3


def test_different_args_tracked_separately() -> None:
    tracker = ToolCallTracker()
    tracker.record_failure("read_file", {"path": "/a"})
    assert tracker.record_failure("read_file", {"path": "/b"}) == 1
    assert tracker.total_failures == 2


def test_different_tools_tracked_separately() -> None:
    tracker = ToolCallTracker()
    tracker.record_failure("read_file", {"path": "/a"})
    assert tracker.record_failure("write_file", {"path": "/a"}) == 1


def test_success_resets_count() -> None:
    tracker = ToolCallTracker()
    tracker.record_failure("read_file", {"path": "/a"})
    tracker.record_failure("read_file", {"path": "/a"})
    tracker.record_success("read_file", {"path": "/a"})
    # After reset, next failure starts at 1 again
    assert tracker.record_failure("read_file", {"path": "/a"}) == 1
    # But total_failures keeps accumulating (3 failures total)
    assert tracker.total_failures == 3


def test_warn_threshold() -> None:
    tracker = ToolCallTracker()
    tracker.record_failure("exec", {"cmd": "ls"})
    count = tracker.record_failure("exec", {"cmd": "ls"})
    assert count >= ToolCallTracker.WARN_THRESHOLD


def test_remove_threshold() -> None:
    tracker = ToolCallTracker()
    for _ in range(ToolCallTracker.REMOVE_THRESHOLD - 1):
        tracker.record_failure("exec", {"cmd": "ls"})
    count = tracker.record_failure("exec", {"cmd": "ls"})
    assert count >= ToolCallTracker.REMOVE_THRESHOLD


def test_budget_exhausted() -> None:
    tracker = ToolCallTracker()
    assert not tracker.budget_exhausted
    for i in range(ToolCallTracker.GLOBAL_BUDGET + 1):
        tracker.record_failure("tool", {"i": i})
    assert tracker.budget_exhausted


def test_args_order_does_not_matter() -> None:
    """Args with same keys in different order should hash identically."""
    tracker = ToolCallTracker()
    tracker.record_failure("read_file", {"path": "/a", "encoding": "utf-8"})
    count = tracker.record_failure("read_file", {"encoding": "utf-8", "path": "/a"})
    assert count == 2
