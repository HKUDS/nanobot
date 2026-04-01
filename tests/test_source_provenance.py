"""Tests for source provenance on memory events."""

from __future__ import annotations

from nanobot.agent.turn_types import ToolAttempt


def _make_attempt(tool_name: str, arguments: dict | None = None) -> ToolAttempt:
    """Helper to build a ToolAttempt with sensible defaults."""
    return ToolAttempt(
        tool_name=tool_name,
        arguments=arguments or {},
        success=True,
        output_empty=False,
        output_snippet="some output",
        iteration=1,
    )


class TestExtractToolHints:
    """Tests for _extract_tool_hints in message_processor."""

    def test_non_exec_tool_uses_name_directly(self):
        from nanobot.agent.message_processor import _extract_tool_hints

        attempts = [_make_attempt("read_file", {"path": "/foo/bar.md"})]
        assert _extract_tool_hints(attempts) == ["read_file"]

    def test_exec_with_command_extracts_first_word(self):
        from nanobot.agent.message_processor import _extract_tool_hints

        attempts = [_make_attempt("exec", {"command": "obsidian search query=DS10540"})]
        assert _extract_tool_hints(attempts) == ["exec:obsidian"]

    def test_exec_without_command_arg_returns_exec(self):
        from nanobot.agent.message_processor import _extract_tool_hints

        attempts = [_make_attempt("exec", {"working_dir": "/tmp"})]
        assert _extract_tool_hints(attempts) == ["exec"]

    def test_deduplicates_identical_hints(self):
        from nanobot.agent.message_processor import _extract_tool_hints

        attempts = [
            _make_attempt("exec", {"command": "obsidian search query=DS10540"}),
            _make_attempt("exec", {"command": "obsidian files folder=DS10540"}),
            _make_attempt("exec", {"command": "obsidian search query=other"}),
        ]
        assert _extract_tool_hints(attempts) == ["exec:obsidian"]

    def test_mixed_tools_sorted_and_deduped(self):
        from nanobot.agent.message_processor import _extract_tool_hints

        attempts = [
            _make_attempt("exec", {"command": "obsidian files folder=DS10540"}),
            _make_attempt("read_file", {"path": "/foo/bar.md"}),
            _make_attempt("exec", {"command": "obsidian search query=test"}),
            _make_attempt("list_dir", {"path": "/foo"}),
        ]
        result = _extract_tool_hints(attempts)
        assert sorted(result) == sorted(result)  # already sorted
        assert set(result) == {"exec:obsidian", "list_dir", "read_file"}

    def test_empty_attempts_returns_empty(self):
        from nanobot.agent.message_processor import _extract_tool_hints

        assert _extract_tool_hints([]) == []

    def test_exec_with_empty_command_string(self):
        from nanobot.agent.message_processor import _extract_tool_hints

        attempts = [_make_attempt("exec", {"command": ""})]
        assert _extract_tool_hints(attempts) == ["exec"]
