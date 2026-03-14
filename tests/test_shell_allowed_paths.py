import pytest

from nanobot.agent.tools.shell import ExecTool


class TestExecToolAllowedPaths:
    def test_blocks_absolute_path_outside_workspace_when_restricted(self, tmp_path):
        tool = ExecTool(working_dir=str(tmp_path), restrict_to_workspace=True)
        result = tool._guard_command("cat /etc/hosts", str(tmp_path))
        assert result == "Error: Command blocked by safety guard (path outside allowed directories)"

    def test_allows_absolute_path_in_extra_allowed_paths(self, tmp_path):
        tool = ExecTool(
            working_dir=str(tmp_path),
            restrict_to_workspace=True,
            allowed_paths=["/etc"],
        )
        result = tool._guard_command("cat /etc/hosts", str(tmp_path))
        assert result is None

    def test_allows_absolute_path_inside_workspace(self, tmp_path):
        tool = ExecTool(working_dir=str(tmp_path), restrict_to_workspace=True)
        allowed_file = tmp_path / "data.txt"
        result = tool._guard_command(f"cat {allowed_file}", str(tmp_path))
        assert result is None
