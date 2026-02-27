"""Tests for Cursor and gh API keys via config (feat/cursor-gh-variables)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from nanobot.cli.commands import app
from nanobot.config.schema import Config

runner = CliRunner()


def test_config_has_cursor_and_gh_tools_config():
    """ToolsConfig has cursor and gh fields with api_key, default empty."""
    config = Config()
    assert hasattr(config.tools, "cursor")
    assert hasattr(config.tools, "gh")
    assert hasattr(config.tools.cursor, "api_key")
    assert hasattr(config.tools.gh, "api_key")
    assert config.tools.cursor.api_key == ""
    assert config.tools.gh.api_key == ""


def test_config_loads_cursor_gh_from_json():
    """Config loads tools.cursor.apiKey and tools.gh.apiKey from JSON (camelCase)."""
    config = Config.model_validate(
        {
            "tools": {
                "cursor": {"apiKey": "cursor-key-123"},
                "gh": {"apiKey": "gh-token-456"},
            }
        }
    )
    assert config.tools.cursor.api_key == "cursor-key-123"
    assert config.tools.gh.api_key == "gh-token-456"


def test_agent_loop_stores_cursor_and_gh_api_keys():
    """AgentLoop stores cursor_api_key and gh_api_key on self when passed."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=Path("/tmp/test"),
        model="test-model",
        cursor_api_key="cursor-secret",
        gh_api_key="gh-secret",
    )
    assert loop.cursor_api_key == "cursor-secret"
    assert loop.gh_api_key == "gh-secret"


def test_status_shows_cursor_and_gh_cli(tmp_path):
    """Status command shows Cursor CLI and gh CLI lines."""
    config_file = tmp_path / "config.json"
    config_file.touch()
    with (
        patch("nanobot.config.loader.get_config_path") as mock_cp,
        patch("nanobot.config.loader.load_config") as mock_lc,
    ):
        mock_cp.return_value = config_file
        config = Config()
        config.tools.cursor.api_key = "cursor-key"
        config.tools.gh.api_key = ""
        mock_lc.return_value = config

        result = runner.invoke(app, ["status"])

        assert result.exit_code == 0
        assert "Cursor CLI" in result.stdout
        assert "gh CLI" in result.stdout
