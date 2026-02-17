"""Additional CLI command coverage for non-onboarding paths."""

from __future__ import annotations

import builtins
from pathlib import Path

import click
import pytest
from typer.testing import CliRunner

from nanobot.cli.commands import _get_bridge_dir, app
from nanobot.config.schema import Config

runner = CliRunner()


def test_cron_add_requires_schedule_option() -> None:
    """Fails with a clear error when no schedule option is provided."""
    result = runner.invoke(app, ["cron", "add", "--name", "daily", "--message", "ping"])
    assert result.exit_code == 1
    assert "Must specify --every, --cron, or --at" in result.stdout


def test_cron_add_every_creates_job(monkeypatch, tmp_path) -> None:
    """Creates an every-schedule job and prints success output."""
    captured: dict[str, object] = {}

    class FakeJob:
        name = "daily"
        id = "job123"

    class FakeCronService:
        def __init__(self, store_path: Path):
            captured["store_path"] = store_path

        def add_job(self, **kwargs):
            captured["kwargs"] = kwargs
            return FakeJob()

    monkeypatch.setattr("nanobot.config.loader.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("nanobot.cron.service.CronService", FakeCronService)

    result = runner.invoke(
        app,
        ["cron", "add", "--name", "daily", "--message", "ping", "--every", "60"],
    )

    assert result.exit_code == 0
    assert "Added job 'daily' (job123)" in result.stdout
    assert (captured["store_path"]).as_posix().endswith("cron/jobs.json")
    kwargs = captured["kwargs"]
    assert kwargs["message"] == "ping"
    assert kwargs["schedule"].kind == "every"
    assert kwargs["schedule"].every_ms == 60000


def test_channels_status_renders_table(monkeypatch) -> None:
    """Prints the channel status table using loaded configuration."""
    cfg = Config()
    cfg.channels.telegram.enabled = True
    cfg.channels.telegram.token = "1234567890ABCDEF"
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda: cfg)

    result = runner.invoke(app, ["channels", "status"])

    assert result.exit_code == 0
    assert "Channel Status" in result.stdout
    assert "Telegram" in result.stdout


def test_provider_login_unknown_provider_exits() -> None:
    """Rejects unsupported provider names with a non-zero exit."""
    result = runner.invoke(app, ["provider", "login", "unknown-provider"])
    assert result.exit_code == 1
    assert "Unknown OAuth provider" in result.stdout


def test_provider_login_import_error_exits(monkeypatch) -> None:
    """Returns a helpful message when oauth_cli_kit cannot be imported."""
    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "oauth_cli_kit":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    result = runner.invoke(app, ["provider", "login", "openai-codex"])

    assert result.exit_code == 1
    assert "oauth_cli_kit not installed" in result.stdout


def test_get_bridge_dir_exits_when_npm_missing(monkeypatch) -> None:
    """Raises exit when npm is unavailable for bridge setup."""
    monkeypatch.setattr("shutil.which", lambda _x: None)
    monkeypatch.setattr("pathlib.Path.home", lambda: Path("/tmp/nonexistent-home"))

    with pytest.raises(click.exceptions.Exit):
        _get_bridge_dir()
