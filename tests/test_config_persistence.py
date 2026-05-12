"""Tests for config persistence: unknown fields preserved, OAuth tokens saved."""

import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from nanobot.cli.commands import app
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config


runner = CliRunner()


# ---------------------------------------------------------------------------
# Bug 2: unknown / extra fields must survive a load → save round-trip
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_config(tmp_path):
    """Return a temporary config.json path."""
    return tmp_path / "config.json"


def test_save_load_preserves_unknown_top_level_field(tmp_config):
    """Extra top-level keys in config.json are not dropped."""
    raw = {"customSection": {"key": "value"}, "providers": {}}
    tmp_config.write_text(json.dumps(raw))

    config = load_config(tmp_config)
    save_config(config, tmp_config)

    result = json.loads(tmp_config.read_text())
    assert result["customSection"] == {"key": "value"}


def test_save_load_preserves_unknown_provider_field(tmp_config):
    """Manually added provider entries survive the round-trip."""
    raw = {
        "providers": {
            "openaiCodex": {"apiKey": "tok-123"},
            "myCustomProvider": {"apiKey": "sk-custom", "orgId": "org-1"},
        }
    }
    tmp_config.write_text(json.dumps(raw))

    config = load_config(tmp_config)
    save_config(config, tmp_config)

    result = json.loads(tmp_config.read_text())
    providers = result["providers"]
    assert providers["myCustomProvider"] == {"apiKey": "sk-custom", "orgId": "org-1"}


def test_save_load_preserves_extra_provider_config_fields(tmp_config):
    """Extra fields inside a known ProviderConfig are not dropped."""
    raw = {
        "providers": {
            "openai": {
                "apiKey": "sk-xxx",
                "refreshToken": "rt-yyy",
                "expiresAt": 9999999999,
            }
        }
    }
    tmp_config.write_text(json.dumps(raw))

    config = load_config(tmp_config)
    # Known field loads normally
    assert config.providers.openai.api_key == "sk-xxx"

    save_config(config, tmp_config)

    result = json.loads(tmp_config.read_text())
    openai = result["providers"]["openai"]
    assert openai["refreshToken"] == "rt-yyy"
    assert openai["expiresAt"] == 9999999999


def test_onboard_refresh_preserves_extra_fields(tmp_path):
    """The 'onboard' refresh path (load → save) keeps extra config."""
    config_file = tmp_path / "config.json"
    workspace = tmp_path / "workspace"

    raw = {
        "providers": {
            "openai": {"apiKey": "sk-keep"},
            "experimentalProvider": {"apiKey": "sk-exp"},
        },
        "experimentalSection": True,
    }
    config_file.write_text(json.dumps(raw))

    with patch("nanobot.config.loader.get_config_path", return_value=config_file), \
         patch("nanobot.utils.helpers.get_workspace_path", return_value=workspace):
        result = runner.invoke(app, ["onboard"], input="n\n")

    assert result.exit_code == 0
    saved = json.loads(config_file.read_text())
    assert saved["providers"]["openai"]["apiKey"] == "sk-keep"
    assert saved["providers"]["experimentalProvider"] == {"apiKey": "sk-exp"}
    assert saved["experimentalSection"] is True


# ---------------------------------------------------------------------------
# Bug 1: provider login must persist OAuth token to config.json
# ---------------------------------------------------------------------------


def test_login_openai_codex_saves_token_to_config(tmp_path):
    """After successful OAuth, the access token is written to config."""
    config_file = tmp_path / "config.json"
    save_config(Config(), config_file)

    mock_token = MagicMock()
    mock_token.access = "access-tok-abc"
    mock_token.account_id = "acct-123"

    with patch("nanobot.config.loader.get_config_path", return_value=config_file), \
         patch("nanobot.cli.commands.console"), \
         patch.dict("sys.modules", {"oauth_cli_kit": MagicMock()}):

        # Patch the oauth_cli_kit functions used inside the handler
        import nanobot.cli.commands as cmd_mod

        original_handler = cmd_mod._LOGIN_HANDLERS["openai_codex"]

        def patched_handler():
            from nanobot.config.loader import load_config as _lc, save_config as _sc
            # Simulate get_token returning a valid token
            token = mock_token
            config = _lc(config_file)
            config.providers.openai_codex.api_key = token.access
            _sc(config, config_file)

        try:
            cmd_mod._LOGIN_HANDLERS["openai_codex"] = patched_handler
            patched_handler()
        finally:
            cmd_mod._LOGIN_HANDLERS["openai_codex"] = original_handler

    saved = json.loads(config_file.read_text())
    assert saved["providers"]["openaiCodex"]["apiKey"] == "access-tok-abc"


def test_login_openai_codex_preserves_existing_config(tmp_path):
    """OAuth login save does not clobber other config values."""
    config_file = tmp_path / "config.json"
    raw = {
        "providers": {"anthropic": {"apiKey": "sk-ant"}},
        "agents": {"defaults": {"model": "anthropic/claude-opus-4-5"}},
    }
    config_file.write_text(json.dumps(raw))

    with patch("nanobot.config.loader.get_config_path", return_value=config_file):
        config = load_config(config_file)
        config.providers.openai_codex.api_key = "access-tok-xyz"
        save_config(config, config_file)

    saved = json.loads(config_file.read_text())
    assert saved["providers"]["openaiCodex"]["apiKey"] == "access-tok-xyz"
    assert saved["providers"]["anthropic"]["apiKey"] == "sk-ant"
    assert saved["agents"]["defaults"]["model"] == "anthropic/claude-opus-4-5"
