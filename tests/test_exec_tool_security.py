"""Tests for ExecTool security guard functionality."""

import tempfile
from pathlib import Path

from nanobot.agent.tools.shell import ExecTool


class TestExecToolSecurity:
    """Test security guard in ExecTool."""

    def test_relative_path_allowed(self) -> None:
        """Relative paths should be allowed when restrict_to_workspace is True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = ExecTool(working_dir=tmpdir, restrict_to_workspace=True)
            result = tool._guard_command(".venv/bin/python scripts/run.py", cwd=tmpdir)
            assert result is None, "Relative paths should be allowed"

    def test_relative_path_with_slash_not_matched_as_absolute(self) -> None:
        """Paths like '.venv/bin/python' should not be matched as absolute paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = ExecTool(working_dir=tmpdir, restrict_to_workspace=True)
            # This was the bug: the regex would match '/bin/python' from '.venv/bin/python'
            result = tool._guard_command(".venv/bin/python scripts/fund_analyzer.py", cwd=tmpdir)
            assert result is None, "Relative paths containing slashes should not trigger absolute path check"

    def test_absolute_path_outside_workspace_blocked(self) -> None:
        """Absolute paths outside workspace should be blocked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = ExecTool(working_dir=tmpdir, restrict_to_workspace=True)
            result = tool._guard_command("/usr/bin/python scripts/run.py", cwd=tmpdir)
            assert result is not None, "Absolute paths outside workspace should be blocked"
            assert "outside working dir" in result

    def test_absolute_path_inside_workspace_allowed(self) -> None:
        """Absolute paths inside workspace should be allowed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = ExecTool(working_dir=tmpdir, restrict_to_workspace=True)
            result = tool._guard_command(f"{tmpdir}/scripts/run.py", cwd=tmpdir)
            assert result is None, "Absolute paths inside workspace should be allowed"

    def test_path_traversal_blocked(self) -> None:
        """Path traversal attempts should be blocked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = ExecTool(working_dir=tmpdir, restrict_to_workspace=True)
            result = tool._guard_command("cat ../../etc/passwd", cwd=tmpdir)
            assert result is not None, "Path traversal should be blocked"
            assert "path traversal" in result

    def test_pipe_with_absolute_path_outside_blocked(self) -> None:
        """Pipes with absolute paths outside workspace should be blocked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = ExecTool(working_dir=tmpdir, restrict_to_workspace=True)
            result = tool._guard_command("cat file.txt | grep test > /tmp/output", cwd=tmpdir)
            assert result is not None, "Redirection to paths outside workspace should be blocked"

    def test_pipe_with_absolute_path_inside_allowed(self) -> None:
        """Pipes with absolute paths inside workspace should be allowed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = ExecTool(working_dir=tmpdir, restrict_to_workspace=True)
            result = tool._guard_command(f"cat file.txt | grep test > {tmpdir}/output", cwd=tmpdir)
            assert result is None, "Redirection within workspace should be allowed"

    def test_deny_patterns_rm_rf(self) -> None:
        """Dangerous commands like rm -rf should be blocked by deny_patterns."""
        tool = ExecTool(deny_patterns=[r"\brm\s+-[rf]{1,2}\b"])
        result = tool._guard_command("rm -rf /tmp/test", cwd="/tmp")
        assert result is not None, "rm -rf should be blocked by deny_patterns"

    def test_allow_patterns(self) -> None:
        """Commands matching allow_patterns should be allowed."""
        tool = ExecTool(allow_patterns=[r"git\s+\w+"])
        result = tool._guard_command("git status", cwd="/tmp")
        assert result is None, "Commands matching allow_patterns should be allowed"

    def test_windows_path_detection(self) -> None:
        """Windows-style absolute paths should be detected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = ExecTool(working_dir=tmpdir, restrict_to_workspace=True)
            result = tool._guard_command("C:\\Windows\\System32\\cmd.exe", cwd=tmpdir)
            # Windows paths outside workspace should be blocked on any platform
            assert result is not None, "Windows absolute paths outside workspace should be blocked"
            assert "outside working dir" in result

    def test_empty_command_allowed(self) -> None:
        """Empty or minimal commands should not cause errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = ExecTool(working_dir=tmpdir, restrict_to_workspace=True)
            result = tool._guard_command("echo test", cwd=tmpdir)
            assert result is None, "Simple commands without paths should be allowed"

    def test_restricted_to_workspace_false_disables_check(self) -> None:
        """When restrict_to_workspace is False, path checks should be disabled."""
        tool = ExecTool(restrict_to_workspace=False)
        result = tool._guard_command("/usr/bin/python", cwd="/tmp")
        assert result is None, "Path restrictions should be disabled when restrict_to_workspace=False"
