"""Tests for skill tool mapping (detection, rewrite, preamble)."""

from __future__ import annotations

from nanobot.context.skills import CLAUDE_TOOL_MAPPING


def test_mapping_has_expected_keys():
    """All Claude Code tool names are present."""
    expected = {
        "Bash",
        "Read",
        "Write",
        "Edit",
        "Glob",
        "Grep",
        "WebFetch",
        "WebSearch",
        "Agent",
        "TodoWrite",
        "TodoRead",
        "ListDir",
        "AskUserQuestion",
    }
    assert set(CLAUDE_TOOL_MAPPING.keys()) == expected


def test_mapping_values_are_tuples():
    """Each mapping value is a (tool_name, hint) tuple."""
    for key, value in CLAUDE_TOOL_MAPPING.items():
        assert isinstance(value, tuple), f"{key} value is not a tuple"
        assert len(value) == 2, f"{key} tuple length is not 2"
        assert isinstance(value[0], str), f"{key} tool name is not str"
        assert isinstance(value[1], str), f"{key} hint is not str"
