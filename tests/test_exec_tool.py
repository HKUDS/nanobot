"""Tests for ExecTool truncate functionality."""

import os
import sys
import tempfile
import pytest

from nanobot.agent.tools.shell import ExecTool


class TestExecToolTruncate:
    """Test cases for output truncation with environment variables."""

    def setup_method(self):
        """Clean up environment variables before each test."""
        os.environ.pop("NANOBOT_MAX_OUTPUT", None)
        os.environ.pop("NANOBOT_TRUNCATE_MODE", None)

    def teardown_method(self):
        """Clean up environment variables after each test."""
        os.environ.pop("NANOBOT_MAX_OUTPUT", None)
        os.environ.pop("NANOBOT_TRUNCATE_MODE", None)

    @pytest.mark.asyncio
    async def test_default_truncate_head(self):
        """Default behavior: truncate from head (keep first part)."""
        tool = ExecTool()
        
        # Use Python to generate long output (avoids command line length limits)
        result = await tool.execute('python -c "print(\'A\' * 15000)"')
        
        assert len(result) < 15000
        assert result.startswith("A")
        assert "truncated" in result
        assert "more chars" in result

    @pytest.mark.asyncio
    async def test_truncate_tail_mode(self):
        """Truncate from tail: keep last part."""
        os.environ["NANOBOT_TRUNCATE_MODE"] = "tail"
        
        tool = ExecTool()
        
        result = await tool.execute('python -c "print(\'B\' * 15000)"')
        
        assert len(result) < 15000
        # Windows uses \r\n, Unix uses \n
        assert result.rstrip().endswith("B")
        assert "truncated" in result
        assert "more chars" in result

    @pytest.mark.asyncio
    async def test_custom_max_output(self):
        """Custom max output length via environment variable."""
        os.environ["NANOBOT_MAX_OUTPUT"] = "100"
        
        tool = ExecTool()
        
        result = await tool.execute('python -c "print(\'X\' * 200)"')
        
        assert len(result) < 200
        assert "truncated" in result

    @pytest.mark.asyncio
    async def test_custom_max_output_with_tail_mode(self):
        """Custom max output length with tail mode."""
        os.environ["NANOBOT_MAX_OUTPUT"] = "100"
        os.environ["NANOBOT_TRUNCATE_MODE"] = "tail"
        
        tool = ExecTool()
        
        result = await tool.execute('python -c "print(\'Y\' * 200)"')
        
        assert len(result) < 200
        assert "truncated" in result
        # Should contain the tail part
        assert "Y" in result

    @pytest.mark.asyncio
    async def test_short_output_not_truncated(self):
        """Short output should not be truncated."""
        tool = ExecTool()
        
        result = await tool.execute('python -c "print(\'Hello World\')"')
        
        assert "truncated" not in result
        assert "Hello World" in result

    @pytest.mark.asyncio
    async def test_invalid_max_output_uses_default(self):
        """Invalid NANOBOT_MAX_OUTPUT should fall back to default."""
        os.environ["NANOBOT_MAX_OUTPUT"] = "invalid"
        
        tool = ExecTool()
        
        # Should not raise, uses default 10000
        result = await tool.execute('python -c "print(\'Test\')"')
        
        assert "Test" in result

    @pytest.mark.asyncio
    async def test_truncate_mode_case_insensitive(self):
        """Truncate mode should be case insensitive."""
        os.environ["NANOBOT_TRUNCATE_MODE"] = "TAIL"
        
        tool = ExecTool()
        
        result = await tool.execute('python -c "print(\'Z\' * 15000)"')
        
        assert "truncated" in result
        # Windows uses \r\n, Unix uses \n
        assert result.rstrip().endswith("Z")


class TestExecToolBasic:
    """Basic functionality tests for ExecTool."""

    @pytest.mark.asyncio
    async def test_simple_command(self):
        """Test simple echo command."""
        tool = ExecTool()
        result = await tool.execute("echo Hello")
        assert "Hello" in result

    @pytest.mark.asyncio
    async def test_command_with_exit_code(self):
        """Test command with non-zero exit code."""
        tool = ExecTool()
        result = await tool.execute("exit 1")
        assert "Exit code: 1" in result

    @pytest.mark.asyncio
    async def test_command_timeout(self):
        """Test command timeout."""
        tool = ExecTool(timeout=1)
        # Use Python sleep for cross-platform compatibility
        result = await tool.execute('python -c "import time; time.sleep(10)"')
        assert "timed out" in result

    @pytest.mark.asyncio
    async def test_blocked_command(self):
        """Test that dangerous commands are blocked."""
        tool = ExecTool()
        result = await tool.execute("rm -rf /")
        assert "blocked" in result

    @pytest.mark.asyncio
    async def test_working_dir(self):
        """Test command with custom working directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = ExecTool(working_dir=tmpdir)
            # Use cd on Windows, pwd on Unix
            if sys.platform == "win32":
                result = await tool.execute("cd")
            else:
                result = await tool.execute("pwd")
            # Just verify it runs without error
            assert result