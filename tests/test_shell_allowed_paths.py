import pytest
from pydantic import ValidationError

from nanobot.agent.tools.shell import ExecTool
from nanobot.config.schema import Config


def test_config_accepts_tools_allowed_paths() -> None:
    config = Config.model_validate({
        "tools": {
            "restrictToWorkspace": True,
            "allowedPaths": ["/dev/null", "/tmp/example"],
        }
    })
    assert config.tools.restrict_to_workspace is True
    assert config.tools.allowed_paths == ["/dev/null", "/tmp/example"]


def test_config_accepts_home_allowed_path() -> None:
    config = Config.model_validate({
        "tools": {
            "restrictToWorkspace": True,
            "allowedPaths": ["~/.nanobot"],
        }
    })
    assert config.tools.allowed_paths == ["~/.nanobot"]


def test_config_rejects_relative_allowed_path() -> None:
    with pytest.raises(ValidationError, match="tools.allowedPaths entries must be absolute paths"):
        Config.model_validate({
            "tools": {
                "restrictToWorkspace": True,
                "allowedPaths": ["tmp/example"],
            }
        })


class TestExecToolAllowedPaths:
    def test_blocks_absolute_path_outside_workspace_when_restricted(self, tmp_path):
        tool = ExecTool(working_dir=str(tmp_path), restrict_to_workspace=True)
        result = tool._guard_command("cat /etc/hosts", str(tmp_path))
        assert result == "Error: Command blocked by safety guard (path outside working dir)"

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

    def test_allows_sibling_media_path_when_allowlisted(self, tmp_path):
        media_dir = tmp_path.parent / "media"
        media_file = media_dir / "upload.txt"
        tool = ExecTool(
            working_dir=str(tmp_path),
            restrict_to_workspace=True,
            allowed_paths=[str(media_dir)],
        )
        result = tool._guard_command(f"cat {media_file}", str(tmp_path))
        assert result is None
