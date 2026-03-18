"""Tests for ToolCallTracker — infinite loop breaker."""

from __future__ import annotations

import pytest

from nanobot.agent.failure import FailureClass, ToolCallTracker
from nanobot.agent.tools.base import ToolResult


def test_first_failure_returns_one() -> None:
    tracker = ToolCallTracker()
    count, fc = tracker.record_failure("read_file", {"path": "/a"})
    assert count == 1
    assert fc == FailureClass.UNKNOWN
    assert tracker.total_failures == 1


def test_identical_failures_accumulate() -> None:
    tracker = ToolCallTracker()
    tracker.record_failure("read_file", {"path": "/a"})
    count, _ = tracker.record_failure("read_file", {"path": "/a"})
    assert count == 2
    count, _ = tracker.record_failure("read_file", {"path": "/a"})
    assert count == 3
    assert tracker.total_failures == 3


def test_different_args_tracked_separately() -> None:
    tracker = ToolCallTracker()
    tracker.record_failure("read_file", {"path": "/a"})
    count, _ = tracker.record_failure("read_file", {"path": "/b"})
    assert count == 1
    assert tracker.total_failures == 2


def test_different_tools_tracked_separately() -> None:
    tracker = ToolCallTracker()
    tracker.record_failure("read_file", {"path": "/a"})
    count, _ = tracker.record_failure("write_file", {"path": "/a"})
    assert count == 1


def test_success_resets_count() -> None:
    tracker = ToolCallTracker()
    tracker.record_failure("read_file", {"path": "/a"})
    tracker.record_failure("read_file", {"path": "/a"})
    tracker.record_success("read_file", {"path": "/a"})
    # After reset, next failure starts at 1 again
    count, _ = tracker.record_failure("read_file", {"path": "/a"})
    assert count == 1
    # But total_failures keeps accumulating (3 failures total)
    assert tracker.total_failures == 3


def test_warn_threshold() -> None:
    tracker = ToolCallTracker()
    tracker.record_failure("exec", {"cmd": "ls"})
    count, _ = tracker.record_failure("exec", {"cmd": "ls"})
    assert count >= ToolCallTracker.WARN_THRESHOLD


def test_remove_threshold() -> None:
    tracker = ToolCallTracker()
    for _ in range(ToolCallTracker.REMOVE_THRESHOLD - 1):
        tracker.record_failure("exec", {"cmd": "ls"})
    count, _ = tracker.record_failure("exec", {"cmd": "ls"})
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
    count, _ = tracker.record_failure("read_file", {"encoding": "utf-8", "path": "/a"})
    assert count == 2


def test_classify_permanent_config_from_error_type() -> None:
    result = ToolResult.fail("not found", error_type="not_found")
    assert ToolCallTracker.classify_failure("tool", result) == FailureClass.PERMANENT_CONFIG


def test_classify_permanent_config_from_message() -> None:
    result = ToolResult.fail("API key not configured")
    assert ToolCallTracker.classify_failure("tool", result) == FailureClass.PERMANENT_CONFIG


def test_classify_permanent_auth() -> None:
    result = ToolResult.fail("unauthorized: invalid key")
    assert ToolCallTracker.classify_failure("tool", result) == FailureClass.PERMANENT_AUTH


def test_classify_transient_timeout() -> None:
    result = ToolResult.fail("request timed out after 30s", error_type="timeout")
    assert ToolCallTracker.classify_failure("tool", result) == FailureClass.TRANSIENT_TIMEOUT


def test_classify_logical_error() -> None:
    result = ToolResult.fail("bad param", error_type="validation")
    assert ToolCallTracker.classify_failure("tool", result) == FailureClass.LOGICAL_ERROR


def test_permanent_failure_removed_on_first_occurrence() -> None:
    tracker = ToolCallTracker()
    result = ToolResult.fail("not configured", error_type="not_found")
    count, fc = tracker.record_failure("web_search", {"query": "x"}, result)
    assert count == 1
    assert fc.is_permanent
    assert "web_search" in tracker.permanent_failures


def test_transient_failure_not_in_permanent_set() -> None:
    tracker = ToolCallTracker()
    result = ToolResult.fail("timeout", error_type="timeout")
    _, fc = tracker.record_failure("web_search", {"query": "x"}, result)
    assert not fc.is_permanent
    assert "web_search" not in tracker.permanent_failures


def test_classify_file_not_found_is_not_permanent() -> None:
    """OS 'No such file or directory' is a logical error — must NOT permanently disable read_file.

    This is the SEC-M3 regression guard: a missing file path is a logical error
    the LLM should correct (try a different path), not a permanent config failure
    that removes the tool for the rest of the turn.
    """
    os_error_msg = "Error: [Errno 2] No such file or directory: '/tmp/does_not_exist.txt'"
    result = ToolResult.fail(os_error_msg)
    fc = ToolCallTracker.classify_failure("read_file", result)
    assert fc not in (FailureClass.PERMANENT_CONFIG, FailureClass.PERMANENT_AUTH), (
        f"File-not-found classified as {fc} — would permanently disable read_file for the turn"
    )


def test_classify_transient_error() -> None:
    """500 / server error is a transient failure, not permanent."""
    result = ToolResult.fail("500 Internal Server Error")
    fc = ToolCallTracker.classify_failure("web_fetch", result)
    assert fc == FailureClass.TRANSIENT_ERROR


def test_classify_command_not_found_is_permanent() -> None:
    """'command not found' (binary missing) is a genuine permanent config failure."""
    result = ToolResult.fail("bash: jq: command not found")
    fc = ToolCallTracker.classify_failure("exec", result)
    assert fc == FailureClass.PERMANENT_CONFIG


# ---------------------------------------------------------------------------
# TEST-M2: parametrized boundary cases for classify_failure (SEC-M3 guard)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message,error_type,expected",
    [
        # PERMANENT_CONFIG — genuine missing config / binary
        ("API key not configured", None, FailureClass.PERMANENT_CONFIG),
        ("web_search is not installed", None, FailureClass.PERMANENT_CONFIG),
        ("bash: curl: command not found", None, FailureClass.PERMANENT_CONFIG),
        ("module not found: mymodule", None, FailureClass.PERMANENT_CONFIG),
        ("binary not found in PATH", None, FailureClass.PERMANENT_CONFIG),
        ("not found", "not_found", FailureClass.PERMANENT_CONFIG),  # explicit error_type
        # PERMANENT_AUTH
        ("401 Unauthorized", None, FailureClass.PERMANENT_AUTH),
        ("invalid authentication token", None, FailureClass.PERMANENT_AUTH),
        ("forbidden", None, FailureClass.PERMANENT_AUTH),
        # TRANSIENT_TIMEOUT
        ("request timed out after 30s", None, FailureClass.TRANSIENT_TIMEOUT),
        ("rate limit exceeded: 429", None, FailureClass.TRANSIENT_TIMEOUT),
        ("too many requests", None, FailureClass.TRANSIENT_TIMEOUT),
        # TRANSIENT_ERROR
        ("500 Internal Server Error", None, FailureClass.TRANSIENT_ERROR),
        ("service unavailable 503", None, FailureClass.TRANSIENT_ERROR),
        # LOGICAL_ERROR
        ("bad param", "validation", FailureClass.LOGICAL_ERROR),
        # File-not-found must NOT be permanent (SEC-M3 false-positive guard)
        ("Error: File not found: /tmp/foo.txt", None, FailureClass.UNKNOWN),
        ("Error: [Errno 2] No such file or directory: '/opt/x.txt'", None, FailureClass.UNKNOWN),
        ("No such file or directory", None, FailureClass.UNKNOWN),
    ],
)
def test_classify_failure_parametrized(
    message: str, error_type: str | None, expected: FailureClass
) -> None:
    kwargs = {"error_type": error_type} if error_type else {}
    result = ToolResult.fail(message, **kwargs)
    fc = ToolCallTracker.classify_failure("tool", result)
    assert fc == expected, (
        f"classify_failure({message!r}, error_type={error_type!r}) = {fc}, want {expected}"
    )


def test_key_stability() -> None:
    """_key() must produce the same digest for the same (name, args) regardless of dict insertion order."""
    k1 = ToolCallTracker._key("my_tool", {"b": 2, "a": 1})
    k2 = ToolCallTracker._key("my_tool", {"a": 1, "b": 2})
    assert k1 == k2, "_key() must be order-independent (sort_keys=True)"

    # Different args -> different key
    k3 = ToolCallTracker._key("my_tool", {"a": 1, "b": 3})
    assert k1 != k3

    # Different tool names -> different key even with same args
    k4 = ToolCallTracker._key("other_tool", {"a": 1, "b": 2})
    assert k1 != k4

    # Non-serialisable values should not raise (default=str fallback)
    k5 = ToolCallTracker._key("t", {"path": object()})
    assert k5.startswith("t:")
