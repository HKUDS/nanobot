from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nanobot.cli.commands import app
from nanobot.config.schema import Config

runner = CliRunner()


def test_replay_deadletters_empty_file_and_invalid_json_dry_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg = Config()
    cfg.agents.defaults.workspace = str(tmp_path)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda: cfg)

    dead = tmp_path / "outbound_failed.jsonl"
    dead.write_text("\n", encoding="utf-8")
    empty = runner.invoke(app, ["replay-deadletters"])
    assert empty.exit_code == 0
    assert "Dead-letter file is empty" in empty.stdout

    dead.write_text(
        "not-json\n" + json.dumps({"channel": "telegram", "chat_id": "1", "content": "hi"}) + "\n",
        encoding="utf-8",
    )
    dry = runner.invoke(app, ["replay-deadletters", "--dry-run"])
    assert dry.exit_code == 0
    assert "invalid JSON line" in dry.stdout


def test_replay_deadletters_success_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = Config()
    cfg.agents.defaults.workspace = str(tmp_path)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda: cfg)

    dead = tmp_path / "outbound_failed.jsonl"
    dead.write_text(
        json.dumps({"channel": "telegram", "chat_id": "1", "content": "hi"}) + "\n",
        encoding="utf-8",
    )

    class _Mgr:
        def __init__(self, config: Config, bus: object):
            self.channels = {"telegram": object()}
            self.enabled_channels = ["telegram"]

        async def replay_dead_letters(self, dry_run: bool = False):
            return (1, 1, 0)

    monkeypatch.setattr("nanobot.channels.manager.ChannelManager", _Mgr)

    out = runner.invoke(app, ["replay-deadletters"])
    assert out.exit_code == 0
    assert "Replay complete" in out.stdout


def test_status_shows_oauth_and_local_provider_states(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg = Config()
    cfg.agents.defaults.workspace = str(tmp_path)
    cfg.providers.vllm.api_base = "http://localhost:11434"
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda: cfg)

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("nanobot.config.loader.get_config_path", lambda: cfg_path)

    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "OAuth" in result.stdout
    assert "http://localhost:11434" in result.stdout
