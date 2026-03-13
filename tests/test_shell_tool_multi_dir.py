"""Test ExecTool with multi-directory whitelist."""

import tempfile
from pathlib import Path

from nanobot.agent.tools.shell import ExecTool


def test_exec_tool_guard_multiple_allowed_dir() -> None:
    """Test _guard_command with multiple allowed directories."""
    with tempfile.TemporaryDirectory() as dir1, tempfile.TemporaryDirectory() as dir2:
        path1 = Path(dir1).resolve()
        path2 = Path(dir2).resolve()

        tool = ExecTool(
            working_dir=str(path1),
            restrict_to_workspace=True,
            allowed_dir=[path1, path2]
        )

        # Path in first allowed dir should be allowed
        error = tool._guard_command(f"cat {path1}/file.txt", str(path1))
        assert error is None

        # Path in second allowed dir should be allowed
        error = tool._guard_command(f"cat {path2}/file.txt", str(path1))
        assert error is None

        # Path outside should be blocked
        error = tool._guard_command("cat /etc/passwd", str(path1))
        assert error is not None
        assert "outside" in error


def test_exec_tool_backward_compatibility() -> None:
    """Test that ExecTool still works without allowed_dir."""
    with tempfile.TemporaryDirectory() as workspace:
        workspace_path = Path(workspace).resolve()

        # Should work without allowed_dir parameter
        tool = ExecTool(
            working_dir=str(workspace_path),
            restrict_to_workspace=True
        )

        error = tool._guard_command("ls", str(workspace_path))
        assert error is None
