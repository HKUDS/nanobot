"""Test config schema with allowed_dirs."""

from nanobot.config.schema import Config, ToolsConfig


def test_tools_config_default_allowed_dirs() -> None:
    """Test that allowed_dirs defaults to empty list."""
    tools = ToolsConfig()
    assert tools.allowed_dirs == []


def test_config_with_allowed_dirs() -> None:
    """Test that allowed_dirs can be set in config."""
    config = Config()
    config.tools.allowed_dirs = ["~/projects", "/data"]
    assert config.tools.allowed_dirs == ["~/projects", "/data"]


def test_config_from_dict_with_allowed_dirs() -> None:
    """Test config loading from dict with allowedDirs (camelCase)."""
    data = {
        "tools": {
            "restrictToWorkspace": True,
            "allowedDirs": ["~/notes", "/tmp"]
        }
    }
    config = Config(**data)
    assert config.tools.restrict_to_workspace is True
    assert config.tools.allowed_dirs == ["~/notes", "/tmp"]
