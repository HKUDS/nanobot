"""Test config schema with allowed_dir."""

from nanobot.config.schema import Config, ToolsConfig


def test_tools_config_default_allowed_dir() -> None:
    """Test that allowed_dir defaults to empty list."""
    tools = ToolsConfig()
    assert tools.allowed_dir == []


def test_config_with_allowed_dir() -> None:
    """Test that allowed_dir can be set in config."""
    config = Config()
    config.tools.allowed_dir = ["~/projects", "/data"]
    assert config.tools.allowed_dir == ["~/projects", "/data"]


def test_config_from_dict_with_allowed_dir() -> None:
    """Test config loading from dict with allowedDir (camelCase)."""
    data = {
        "tools": {
            "restrictToWorkspace": True,
            "allowedDir": ["~/notes", "/tmp"]
        }
    }
    config = Config(**data)
    assert config.tools.restrict_to_workspace is True
    assert config.tools.allowed_dir == ["~/notes", "/tmp"]
