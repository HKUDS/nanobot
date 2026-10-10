import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nanobot.cli.commands import app
from nanobot.config import loader
from nanobot.config.paths import get_cli_history_path, get_legacy_sessions_dir, get_media_dir
from nanobot.config.schema import Config


@pytest.fixture(autouse=True)
def isolate_config(monkeypatch):
    monkeypatch.setattr(loader, "_current_config_path", None)
    monkeypatch.delenv("NANOBOT_HOME", raising=False)


def test_home_onboard_and_status(tmp_path):
    home = tmp_path / "instance with spaces"
    runner = CliRunner()
    result = runner.invoke(app, ["--home", str(home), "onboard"])
    assert result.exit_code == 0, result.output
    data = json.loads((home / "config.json").read_text(encoding="utf-8"))
    assert Path(data["agents"]["defaults"]["workspace"]) == home / "workspace"
    assert (home / "workspace" / "SOUL.md").is_file()
    result = runner.invoke(app, ["--home", str(home), "status"])
    assert result.exit_code == 0, result.output
    assert str(home) in "".join(result.output.splitlines())
    assert "NANOBOT_HOME" not in os.environ


def test_home_explicit_config_and_workspace_take_precedence(tmp_path):
    home = tmp_path / "home"
    config = tmp_path / "other" / "config.json"
    workspace = tmp_path / "project"
    result = CliRunner().invoke(app, [
        "--home", str(home), "onboard", "--config", str(config),
        "--workspace", str(workspace),
    ])
    assert result.exit_code == 0, result.output
    assert not (home / "config.json").exists()
    loaded = loader.load_config(config)
    assert loaded.workspace_path == workspace
    assert loaded.runtime_data_dir == config.parent


def test_home_environment_paths_and_saved_workspace(monkeypatch, tmp_path):
    monkeypatch.setenv("NANOBOT_HOME", str(tmp_path))
    assert loader.get_config_path() == tmp_path / "config.json"
    assert Config().workspace_path == tmp_path / "workspace"
    assert get_media_dir() == tmp_path / "media"
    assert get_cli_history_path() == tmp_path / "history" / "cli_history"
    assert get_legacy_sessions_dir() == tmp_path / "sessions"
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "custom")
    loader.save_config(config)
    assert loader.load_config().workspace_path == tmp_path / "custom"


def test_installed_entry_dispatch_and_help(tmp_path):
    root = Path(__file__).parents[2]
    for args in (["--home", str(tmp_path), "onboard"], ["-h"], ["--home", str(tmp_path), "status"]):
        result = subprocess.run(
            [sys.executable, "-m", "nanobot", *args], cwd=root,
            capture_output=True, text=True, encoding="utf-8", check=False,
        )
        assert result.returncode == 0, result.stderr
    assert (tmp_path / "config.json").is_file()


def test_home_rejects_file(tmp_path):
    target = tmp_path / "file"
    target.touch()
    result = CliRunner().invoke(app, ["--home", str(target), "onboard"])
    assert result.exit_code == 2


def test_home_overrides_environment_and_bare_command_starts_agent(monkeypatch, tmp_path):
    from nanobot.cli import entry

    inherited = tmp_path / "inherited"
    selected = tmp_path / "selected"
    monkeypatch.setenv("NANOBOT_HOME", str(inherited))
    observed = []

    def run_agent(args, *, prog_name):
        observed.append((loader.get_config_path(), Config().workspace_path))

    monkeypatch.setattr(entry, "_run_agent", run_agent)
    result = CliRunner().invoke(app, ["--home", str(selected)])
    assert result.exit_code == 0, result.output
    assert observed == [(selected / "config.json", selected / "workspace")]
    assert os.environ["NANOBOT_HOME"] == str(inherited)
