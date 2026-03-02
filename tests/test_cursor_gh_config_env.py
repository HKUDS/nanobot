"""Tests for Cursor and gh API keys via config (feat/cursor-gh-variables)."""

import os
from pathlib import Path
from unittest.mock import patch

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


def test_inject_cli_env_sets_gh_token_and_cursor_api_key():
    """_inject_cli_env sets GH_TOKEN and CURSOR_API_KEY in os.environ."""
    from nanobot.cli.commands import _inject_cli_env

    config = Config.model_validate(
        {"tools": {"cursor": {"apiKey": "cursor-secret"}, "gh": {"apiKey": "gh-secret"}}}
    )
    try:
        _inject_cli_env(config)
        assert os.environ.get("GH_TOKEN") == "gh-secret"
        assert os.environ.get("CURSOR_API_KEY") == "cursor-secret"
    finally:
        os.environ.pop("GH_TOKEN", None)
        os.environ.pop("CURSOR_API_KEY", None)


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
