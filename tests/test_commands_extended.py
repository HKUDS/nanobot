from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import typer
from typer.testing import CliRunner

from nanobot.cli.commands import _get_bridge_dir, _make_provider, app
from nanobot.config.schema import Config
from nanobot.providers.custom_provider import CustomProvider
from nanobot.providers.litellm_provider import LiteLLMProvider

runner = CliRunner()


def test_make_provider_missing_api_key_raises() -> None:
    config = Config()
    config.agents.defaults.model = "openai/gpt-4.1"

    with pytest.raises(typer.Exit):
        _make_provider(config)


def test_make_provider_litellm_bedrock_path() -> None:
    config = Config()
    config.agents.defaults.model = "bedrock/anthropic.claude"

    provider = _make_provider(config)
    assert isinstance(provider, LiteLLMProvider)


def test_make_provider_custom_path() -> None:
    config = Config()
    config.agents.defaults.model = "custom/my-model"
    config.providers.custom.api_key = "dummy"
    config.providers.custom.api_base = "http://localhost:1234/v1"

    provider = _make_provider(config)
    assert isinstance(provider, CustomProvider)


def test_make_provider_openai_codex_path(monkeypatch: pytest.MonkeyPatch) -> None:
    config = Config()
    config.agents.defaults.model = "openai-codex/gpt-5.1-codex"

    class _FakeCodexProvider:
        def __init__(self, default_model: str):
            self.default_model = default_model

    monkeypatch.setattr(
        "nanobot.providers.openai_codex_provider.OpenAICodexProvider", _FakeCodexProvider
    )
    provider = _make_provider(config)
    assert isinstance(provider, _FakeCodexProvider)
    assert provider.default_model == "openai-codex/gpt-5.1-codex"


def test_get_bridge_dir_fast_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    bridge = tmp_path / ".nanobot" / "bridge"
    (bridge / "dist").mkdir(parents=True)
    (bridge / "dist" / "index.js").write_text("ok", encoding="utf-8")

    out = _get_bridge_dir()
    assert out == bridge


def test_get_bridge_dir_requires_npm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: None)

    with pytest.raises(typer.Exit):
        _get_bridge_dir()


def test_get_bridge_dir_build_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/npm")

    def _boom(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["npm", "run", "build"], stderr=b"build failed")

    monkeypatch.setattr(subprocess, "run", _boom)

    with pytest.raises(typer.Exit):
        _get_bridge_dir()


def test_channels_status_command(monkeypatch: pytest.MonkeyPatch) -> None:
    config = Config()
    config.channels.telegram.enabled = True
    config.channels.telegram.token = "1234567890abcdefgh"
    config.channels.whatsapp.enabled = True

    monkeypatch.setattr("nanobot.config.loader.load_config", lambda: config)
    result = runner.invoke(app, ["channels", "status"])

    assert result.exit_code == 0
    assert "Channel Status" in result.stdout
    assert "WhatsApp" in result.stdout
    assert "Telegram" in result.stdout


def test_cron_list_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("nanobot.config.loader.get_data_dir", lambda: tmp_path)
    result = runner.invoke(app, ["cron", "list"])
    assert result.exit_code == 0
    assert "No scheduled jobs." in result.stdout


def test_cron_remove_and_enable_not_found(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("nanobot.config.loader.get_data_dir", lambda: tmp_path)

    remove_result = runner.invoke(app, ["cron", "remove", "missing-id"])
    assert remove_result.exit_code == 0
    assert "not found" in remove_result.stdout

    enable_result = runner.invoke(app, ["cron", "enable", "missing-id"])
    assert enable_result.exit_code == 0
    assert "not found" in enable_result.stdout


def test_cron_add_requires_schedule(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("nanobot.config.loader.get_data_dir", lambda: tmp_path)

    result = runner.invoke(
        app,
        ["cron", "add", "--name", "demo", "--message", "hello"],
    )
    assert result.exit_code == 1
    assert "Must specify --every, --cron, or --at" in result.stdout
