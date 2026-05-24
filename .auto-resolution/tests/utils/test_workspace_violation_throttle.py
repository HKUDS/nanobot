"""Tests for repeated_workspace_violation throttle and signature."""

from __future__ import annotations

from nanobot.utils.runtime import (
    repeated_workspace_violation_error,
    workspace_violation_signature,
)


def test_signature_for_filesystem_tools_uses_path_argument():
    sig_a = workspace_violation_signature(
        "read_file", {"path": "/Users/x/Downloads/01.md"}
    )
    sig_b = workspace_violation_signature(
        "write_file", {"path": "/Users/x/Downloads/01.md"}
    )
    sig_c = workspace_violation_signature(
        "edit_file", {"file_path": "/Users/x/Downloads/01.md"}
    )

    assert sig_a is not None
    assert sig_a == sig_b == sig_c, (
        "the throttle must collapse equivalent paths across different tools "
        "so the LLM cannot bypass it by switching tool"
    )
    assert "/users/x/downloads/01.md" in sig_a


def test_signature_for_exec_extracts_first_absolute_path_in_command():
    sig = workspace_violation_signature(
        "exec",
        {"command": "cat /Users/x/Downloads/01.md && echo done"},
    )
    assert sig is not None
    assert "/users/x/downloads/01.md" in sig


def test_signature_collides_across_filesystem_and_exec_for_same_target():
    """LLM bypass loops jump tools (read_file -> exec cat). Throttle must
    treat both attempts as targeting the same outside resource."""
    fs_sig = workspace_violation_signature(
        "read_file", {"path": "/Users/x/Downloads/01.md"}
    )
    exec_sig = workspace_violation_signature(
        "exec", {"command": "cat /Users/x/Downloads/01.md"}
    )
    assert fs_sig == exec_sig


def test_signature_falls_back_to_working_dir_when_no_absolute_in_command():
    sig = workspace_violation_signature(
        "exec",
        {"command": "ls -la", "working_dir": "/etc"},
    )
    assert sig is not None
    assert "/etc" in sig


def test_signature_is_none_for_unknown_tool_with_no_path():
    assert workspace_violation_signature("web_search", {"query": "anything"}) is None
    assert workspace_violation_signature("exec", {"command": "echo hello"}) is None


def test_repeated_workspace_violation_returns_none_within_budget():
    counts: dict[str, int] = {}
    arguments = {"path": "/Users/x/Downloads/01.md"}

    assert repeated_workspace_violation_error("read_file", arguments, counts) is None
    assert repeated_workspace_violation_error("read_file", arguments, counts) is None


def test_repeated_workspace_violation_escalates_after_third_attempt():
    counts: dict[str, int] = {}
    arguments = {"path": "/Users/x/Downloads/01.md"}

    repeated_workspace_violation_error("read_file", arguments, counts)
    repeated_workspace_violation_error("read_file", arguments, counts)
    third = repeated_workspace_violation_error("read_file", arguments, counts)

    assert third is not None
    assert "refusing repeated workspace-bypass" in third
    assert "/users/x/downloads/01.md" in third
    assert "ask how they want to proceed" in third


def test_repeated_workspace_violation_independent_per_target():
    """Different outside paths must each get their own retry budget."""
    counts: dict[str, int] = {}

    repeated_workspace_violation_error(
        "read_file", {"path": "/Users/x/Downloads/01.md"}, counts,
    )
    repeated_workspace_violation_error(
        "read_file", {"path": "/Users/x/Downloads/01.md"}, counts,
    )
    # Different target, fresh budget.
    assert repeated_workspace_violation_error(
        "read_file", {"path": "/Users/x/Documents/notes.md"}, counts,
    ) is None


def test_repeated_workspace_violation_collapses_tool_switching():
    """LLM switches from read_file to exec cat then to python -c open(...)
    against the same path; the throttle must escalate on the third attempt."""
    counts: dict[str, int] = {}

    repeated_workspace_violation_error(
        "read_file", {"path": "/Users/x/Downloads/01.md"}, counts,
    )
    repeated_workspace_violation_error(
        "exec", {"command": "cat /Users/x/Downloads/01.md"}, counts,
    )
    third = repeated_workspace_violation_error(
        "exec",
        {"command": "python3 -c \"open('/Users/x/Downloads/01.md').read()\""},
        counts,
    )
    assert third is not None
    assert "refusing repeated workspace-bypass" in third
