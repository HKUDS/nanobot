"""Tests for tool hint formatting (nanobot.utils.tool_hints)."""

from nanobot.utils.tool_hints import format_tool_hints
from nanobot.providers.base import ToolCallRequest


def _tc(name: str, args) -> ToolCallRequest:
    return ToolCallRequest(id="c1", name=name, arguments=args)


def _hint(calls):
    """Shortcut for format_tool_hints."""
    return format_tool_hints(calls)


class TestToolHintKnownTools:
    """Test registered tool types produce correct formatted output."""

    def test_read_file_short_path(self):
        result = _hint([_tc("read_file", {"path": "foo.txt"})])
        assert result == 'read foo.txt'

    def test_read_file_long_path(self):
        result = _hint([_tc("read_file", {"path": "/home/user/.local/share/uv/tools/nanobot/agent/loop.py"})])
        assert "loop.py" in result
        assert "read " in result

    def test_write_file_shows_path_not_content(self):
        result = _hint([_tc("write_file", {"path": "docs/api.md", "content": "# API Reference\n\nLong content..."})])
        assert result == "write docs/api.md"

    def test_edit_shows_path(self):
        result = _hint([_tc("edit", {"file_path": "src/main.py", "old_string": "x", "new_string": "y"})])
        assert "main.py" in result
        assert "edit " in result

    def test_glob_shows_pattern(self):
        result = _hint([_tc("glob", {"pattern": "**/*.py", "path": "src"})])
        assert result == 'glob "**/*.py"'

    def test_grep_shows_pattern(self):
        result = _hint([_tc("grep", {"pattern": "TODO|FIXME", "path": "src"})])
        assert result == 'grep "TODO|FIXME"'

    def test_exec_shows_command(self):
        result = _hint([_tc("exec", {"command": "npm install typescript"})])
        assert result == "$ npm install typescript"

    def test_exec_truncates_long_command(self):
        cmd = "cd /very/long/path && cat file && echo done && sleep 1 && ls -la"
        result = _hint([_tc("exec", {"command": cmd})])
        assert result.startswith("$ ")
        assert len(result) <= 50  # reasonable limit

    def test_exec_abbreviates_paths_in_command(self):
        """Windows paths in exec commands should be folded, not blindly truncated."""
        cmd = "cd D:\\Documents\\GitHub\\nanobot\\.worktree\\tomain\\nanobot && git diff origin/main...pr-2706 --name-only 2>&1"
        result = _hint([_tc("exec", {"command": cmd})])
        assert "\u2026/" in result  # path should be folded with …/
        assert "worktree" not in result  # middle segments should be collapsed

    def test_exec_abbreviates_linux_paths(self):
        """Unix absolute paths in exec commands should be folded."""
        cmd = "cd /home/user/projects/nanobot/.worktree/tomain && make build"
        result = _hint([_tc("exec", {"command": cmd})])
        assert "\u2026/" in result
        assert "projects" not in result

    def test_exec_abbreviates_home_paths(self):
        """~/ paths in exec commands should be folded."""
        cmd = "cd ~/projects/nanobot/workspace && pytest tests/"
        result = _hint([_tc("exec", {"command": cmd})])
        assert "\u2026/" in result

    def test_exec_abbreviates_quoted_linux_paths_with_spaces(self):
        """Quoted Unix paths with spaces should still be folded."""
        cmd = 'cd "/home/user/My Documents/project" && pytest tests/'
        result = _hint([_tc("exec", {"command": cmd})])
        assert "\u2026/" in result
        assert '"/home/user/My Documents/project"' not in result
        assert '"' in result

    def test_exec_abbreviates_quoted_windows_paths_with_spaces(self):
        """Quoted Windows paths with spaces should still be folded."""
        cmd = 'cd "C:/Program Files/Git/project" && git status'
        result = _hint([_tc("exec", {"command": cmd})])
        assert "\u2026/" in result
        assert '"C:/Program Files/Git/project"' not in result
        assert '"' in result

    def test_exec_short_command_unchanged(self):
        result = _hint([_tc("exec", {"command": "npm install typescript"})])
        assert result == "$ npm install typescript"

    def test_exec_chained_commands_truncated_not_mid_path(self):
        """Long chained commands should truncate preserving abbreviated paths."""
        cmd = "cd D:\\Documents\\GitHub\\project && npm run build && npm test"
        result = _hint([_tc("exec", {"command": cmd})])
        assert "\u2026/" in result  # path folded
        assert "npm" in result  # chained command still visible

    def test_web_search(self):
        result = _hint([_tc("web_search", {"query": "Claude 4 vs GPT-4"})])
        assert result == 'search "Claude 4 vs GPT-4"'

    def test_web_fetch(self):
        result = _hint([_tc("web_fetch", {"url": "https://example.com/page"})])
        assert result == "fetch https://example.com/page"


class TestToolHintMCP:
    """Test MCP tools are abbreviated to server::tool format."""

    def test_mcp_standard_format(self):
        result = _hint([_tc("mcp_4_5v_mcp__analyze_image", {"imageSource": "https://img.jpg", "prompt": "describe"})])
        assert "4_5v" in result
        assert "analyze_image" in result

    def test_mcp_simple_name(self):
        result = _hint([_tc("mcp_github__create_issue", {"title": "Bug fix"})])
        assert "github" in result
        assert "create_issue" in result


class TestToolHintFallback:
    """Test unknown tools fall back to original behavior."""

    def test_unknown_tool_with_string_arg(self):
        result = _hint([_tc("custom_tool", {"data": "hello world"})])
        assert result == 'custom_tool("hello world")'

    def test_unknown_tool_with_long_arg_truncates(self):
        long_val = "a" * 60
        result = _hint([_tc("custom_tool", {"data": long_val})])
        assert len(result) < 80
        assert "\u2026" in result

    def test_unknown_tool_no_string_arg(self):
        result = _hint([_tc("custom_tool", {"count": 42})])
        assert result == "custom_tool"

    def test_empty_tool_calls(self):
        result = _hint([])
        assert result == ""


class TestToolHintFolding:
    """Test consecutive same-tool calls are folded."""

    def test_single_call_no_fold(self):
        calls = [_tc("grep", {"pattern": "*.py"})]
        result = _hint(calls)
        assert "\u00d7" not in result

    def test_two_consecutive_different_args_not_folded(self):
        calls = [
            _tc("grep", {"pattern": "*.py"}),
            _tc("grep", {"pattern": "*.ts"}),
        ]
        result = _hint(calls)
        assert "\u00d7" not in result

    def test_two_consecutive_same_args_folded(self):
        calls = [
            _tc("grep", {"pattern": "TODO"}),
            _tc("grep", {"pattern": "TODO"}),
        ]
        result = _hint(calls)
        assert "\u00d7 2" in result

    def test_three_consecutive_different_args_not_folded(self):
        calls = [
            _tc("read_file", {"path": "a.py"}),
            _tc("read_file", {"path": "b.py"}),
            _tc("read_file", {"path": "c.py"}),
        ]
        result = _hint(calls)
        assert "\u00d7" not in result

    def test_different_tools_not_folded(self):
        calls = [
            _tc("grep", {"pattern": "TODO"}),
            _tc("read_file", {"path": "a.py"}),
        ]
        result = _hint(calls)
        assert "\u00d7" not in result

    def test_interleaved_same_tools_not_folded(self):
        calls = [
            _tc("grep", {"pattern": "a"}),
            _tc("read_file", {"path": "f.py"}),
            _tc("grep", {"pattern": "b"}),
        ]
        result = _hint(calls)
        assert "\u00d7" not in result


class TestToolHintMultipleCalls:
    """Test multiple different tool calls are comma-separated."""

    def test_two_different_tools(self):
        calls = [
            _tc("grep", {"pattern": "TODO"}),
            _tc("read_file", {"path": "main.py"}),
        ]
        result = _hint(calls)
        assert 'grep "TODO"' in result
        assert "read main.py" in result
        assert ", " in result


class TestToolHintEdgeCases:
    """Test edge cases and defensive handling (G1, G2)."""

    def test_known_tool_empty_list_args(self):
        """C1/G1: Empty list arguments should not crash."""
        result = _hint([_tc("read_file", [])])
        assert result == "read_file"

    def test_known_tool_none_args(self):
        """G2: None arguments should not crash."""
        result = _hint([_tc("read_file", None)])
        assert result == "read_file"

    def test_fallback_empty_list_args(self):
        """C1: Empty list args in fallback should not crash."""
        result = _hint([_tc("custom_tool", [])])
        assert result == "custom_tool"

    def test_fallback_none_args(self):
        """G2: None args in fallback should not crash."""
        result = _hint([_tc("custom_tool", None)])
        assert result == "custom_tool"

    def test_list_dir_registered(self):
        """S2: list_dir should use 'ls' format."""
        result = _hint([_tc("list_dir", {"path": "/tmp"})])
        assert result == "ls /tmp"


class TestToolHintMixedFolding:
    """G4: Mixed folding groups with interleaved same-tool segments."""

    def test_read_read_grep_grep_read(self):
        """All different args — each hint listed separately."""
        calls = [
            _tc("read_file", {"path": "a.py"}),
            _tc("read_file", {"path": "b.py"}),
            _tc("grep", {"pattern": "x"}),
            _tc("grep", {"pattern": "y"}),
            _tc("read_file", {"path": "c.py"}),
        ]
        result = _hint(calls)
        assert "\u00d7" not in result
        parts = result.split(", ")
        assert len(parts) == 5
