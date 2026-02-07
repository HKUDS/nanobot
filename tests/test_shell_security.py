"""Tests for shell tool security features."""

import pytest

from nanobot.agent.tools.shell import ExecTool


class TestExecToolSecurity:
    """Test security features of ExecTool."""

    @pytest.mark.asyncio
    async def test_shell_operator_blocking(self):
        """Test that shell operators are blocked."""
        tool = ExecTool(timeout=60)

        test_cases = [
            "echo hello; whoami",
            "cat file | grep test",
            "ls && pwd",
            "echo $(whoami)",
            "echo `whoami`",
            "cat < file",
            "echo > file",
        ]

        for cmd in test_cases:
            result = await tool.execute(cmd)
            assert "Shell operator not allowed" in result or "not allowed" in result, f"Command should be blocked: {cmd}"

    @pytest.mark.asyncio
    async def test_dangerous_command_blocking(self):
        """Test that dangerous commands are blocked."""
        tool = ExecTool(timeout=60)

        test_cases = [
            "rm -rf /tmp/test",
            "dd if=/dev/zero of=/tmp/test",
            "shutdown -h now",
        ]

        for cmd in test_cases:
            result = await tool.execute(cmd)
            assert "blocked" in result or "not allowed" in result, f"Command should be blocked: {cmd}"

    @pytest.mark.asyncio
    async def test_whitelist_mode(self):
        """Test command whitelist functionality."""
        tool = ExecTool(
            timeout=60,
            allowed_commands={'ls', 'echo', 'cat'}
        )

        # Allowed commands
        result = await tool.execute("ls -la")
        assert "Shell operator" not in result

        # Blocked commands
        result = await tool.execute("whoami")
        assert "not allowed" in result
        assert "whoami" in result

    @pytest.mark.asyncio
    async def test_custom_deny_patterns(self):
        """Test custom deny patterns."""
        tool = ExecTool(
            timeout=60,
            deny_patterns=['whoami', 'id']
        )

        # Built-in patterns still work
        result = await tool.execute("rm -rf /tmp/test")
        assert "blocked" in result

        # Custom patterns work
        result = await tool.execute("whoami")
        assert "blocked" in result

    @pytest.mark.asyncio
    async def test_safe_commands_allowed(self):
        """Test that safe commands are allowed."""
        tool = ExecTool(timeout=60)

        safe_commands = [
            "ls -la",
            "echo hello",
            "pwd",
        ]

        for cmd in safe_commands:
            result = await tool.execute(cmd)
            assert "Error" not in result or "no output" in result, f"Command should succeed: {cmd}"

    @pytest.mark.asyncio
    async def test_empty_command(self):
        """Test empty command handling."""
        tool = ExecTool(timeout=60)

        result = await tool.execute("")
        assert "Empty command" in result

    @pytest.mark.asyncio
    async def test_path_traversal_detection(self):
        """Test path traversal detection in workspace mode."""
        tool = ExecTool(
            timeout=60,
            working_dir="/tmp",
            restrict_to_workspace=True
        )

        # Path traversal should be blocked
        result = await tool.execute("cat ../../../etc/passwd")
        assert "traversal" in result.lower() or "blocked" in result.lower()

    @pytest.mark.asyncio
    async def test_parameterized_execution(self):
        """Test that commands use parameterized execution (not shell)."""
        tool = ExecTool(timeout=60)

        # This should NOT execute whoami - the semicolon becomes part of echo's argument
        result = await tool.execute("echo hello; whoami")
        assert "Shell operator not allowed" in result

    @pytest.mark.asyncio
    async def test_quotes_preserved(self):
        """Test that quotes are properly preserved."""
        tool = ExecTool(timeout=60)

        # Quotes should be preserved by shlex.split
        result = await tool.execute('echo "hello world"')
        # Should not error, quotes handled correctly
        assert "hello world" in result or "no output" in result
