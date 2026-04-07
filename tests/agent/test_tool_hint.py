"""Tests for AgentLoop._tool_hint() formatting."""

from nanobot.agent.loop import AgentLoop
from nanobot.providers.base import ToolCallRequest


def _tc(name: str, args: dict) -> ToolCallRequest:
    return ToolCallRequest(id="c1", name=name, arguments=args)


class TestToolHintKnownTools:
    """Test registered tool types produce correct formatted output."""

    def test_read_file_short_path(self):
        result = AgentLoop._tool_hint([_tc("read_file", {"path": "foo.txt"})])
        assert result == 'read foo.txt'

    def test_read_file_long_path(self):
        result = AgentLoop._tool_hint([_tc("read_file", {"path": "/home/user/.local/share/uv/tools/nanobot/agent/loop.py"})])
        assert "loop.py" in result
        assert "read " in result

    def test_write_file_shows_path_not_content(self):
        result = AgentLoop._tool_hint([_tc("write_file", {"path": "docs/api.md", "content": "# API Reference\n\nLong content..."})])
        assert result == "write docs/api.md"

    def test_edit_shows_path(self):
        result = AgentLoop._tool_hint([_tc("edit", {"file_path": "src/main.py", "old_string": "x", "new_string": "y"})])
        assert "main.py" in result
        assert "edit " in result

    def test_glob_shows_pattern(self):
        result = AgentLoop._tool_hint([_tc("glob", {"pattern": "**/*.py", "path": "src"})])
        assert result == 'glob "**/*.py"'

    def test_grep_shows_pattern(self):
        result = AgentLoop._tool_hint([_tc("grep", {"pattern": "TODO|FIXME", "path": "src"})])
        assert result == 'grep "TODO|FIXME"'

    def test_exec_shows_command(self):
        result = AgentLoop._tool_hint([_tc("exec", {"command": "npm install typescript"})])
        assert result == "$ npm install typescript"

    def test_exec_truncates_long_command(self):
        cmd = "cd /very/long/path && cat file && echo done && sleep 1 && ls -la"
        result = AgentLoop._tool_hint([_tc("exec", {"command": cmd})])
        assert result.startswith("$ ")
        assert len(result) <= 50  # reasonable limit

    def test_web_search(self):
        result = AgentLoop._tool_hint([_tc("web_search", {"query": "Claude 4 vs GPT-4"})])
        assert result == 'search "Claude 4 vs GPT-4"'

    def test_web_fetch(self):
        result = AgentLoop._tool_hint([_tc("web_fetch", {"url": "https://example.com/page"})])
        assert result == "fetch https://example.com/page"


class TestToolHintMCP:
    """Test MCP tools are abbreviated to server::tool format."""

    def test_mcp_standard_format(self):
        result = AgentLoop._tool_hint([_tc("mcp_4_5v_mcp__analyze_image", {"imageSource": "https://img.jpg", "prompt": "describe"})])
        assert "4_5v" in result
        assert "analyze_image" in result

    def test_mcp_simple_name(self):
        result = AgentLoop._tool_hint([_tc("mcp_github__create_issue", {"title": "Bug fix"})])
        assert "github" in result
        assert "create_issue" in result


class TestToolHintFallback:
    """Test unknown tools fall back to original behavior."""

    def test_unknown_tool_with_string_arg(self):
        result = AgentLoop._tool_hint([_tc("custom_tool", {"data": "hello world"})])
        assert result == 'custom_tool("hello world")'

    def test_unknown_tool_with_long_arg_truncates(self):
        long_val = "a" * 60
        result = AgentLoop._tool_hint([_tc("custom_tool", {"data": long_val})])
        assert len(result) < 80
        assert "\u2026" in result

    def test_unknown_tool_no_string_arg(self):
        result = AgentLoop._tool_hint([_tc("custom_tool", {"count": 42})])
        assert result == "custom_tool"

    def test_empty_tool_calls(self):
        result = AgentLoop._tool_hint([])
        assert result == ""


class TestToolHintFolding:
    """Test consecutive same-tool calls are folded."""

    def test_single_call_no_fold(self):
        calls = [_tc("grep", {"pattern": "*.py"})]
        result = AgentLoop._tool_hint(calls)
        assert "\u00d7" not in result

    def test_two_consecutive_same_folded(self):
        calls = [
            _tc("grep", {"pattern": "*.py"}),
            _tc("grep", {"pattern": "*.ts"}),
        ]
        result = AgentLoop._tool_hint(calls)
        assert "\u00d7 2" in result

    def test_three_consecutive_same_folded(self):
        calls = [
            _tc("read_file", {"path": "a.py"}),
            _tc("read_file", {"path": "b.py"}),
            _tc("read_file", {"path": "c.py"}),
        ]
        result = AgentLoop._tool_hint(calls)
        assert "\u00d7 3" in result

    def test_different_tools_not_folded(self):
        calls = [
            _tc("grep", {"pattern": "TODO"}),
            _tc("read_file", {"path": "a.py"}),
        ]
        result = AgentLoop._tool_hint(calls)
        assert "\u00d7" not in result

    def test_interleaved_same_tools_not_folded(self):
        calls = [
            _tc("grep", {"pattern": "a"}),
            _tc("read_file", {"path": "f.py"}),
            _tc("grep", {"pattern": "b"}),
        ]
        result = AgentLoop._tool_hint(calls)
        assert "\u00d7" not in result


class TestToolHintMultipleCalls:
    """Test multiple different tool calls are comma-separated."""

    def test_two_different_tools(self):
        calls = [
            _tc("grep", {"pattern": "TODO"}),
            _tc("read_file", {"path": "main.py"}),
        ]
        result = AgentLoop._tool_hint(calls)
        assert 'grep "TODO"' in result
        assert "read main.py" in result
        assert ", " in result
