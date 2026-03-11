from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nanobot.cli.commands import app
from nanobot.config.schema import Config

runner = CliRunner()


def test_get_bridge_dir_source_not_found(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/npm")

    # Force both package and source bridge checks to fail.
    from nanobot import cli as cli_pkg

    commands_file = Path(cli_pkg.commands.__file__).resolve()
    pkg_bridge = commands_file.parent.parent / "bridge"
    src_bridge = commands_file.parent.parent.parent / "bridge"

    if (pkg_bridge / "package.json").exists() or (src_bridge / "package.json").exists():
        pytest.skip("Bridge source exists in this environment; source-not-found path not reachable.")

    out = runner.invoke(app, ["channels", "login"])
    assert out.exit_code == 1
    assert "Bridge source not found" in out.stdout


def test_channels_login_success_and_failures(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = Config()
    cfg.agents.defaults.workspace = str(tmp_path)
    cfg.channels.whatsapp.bridge_token = "bridge-token"
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda: cfg)

    bridge_dir = tmp_path / "bridge"
    bridge_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("nanobot.cli.commands._get_bridge_dir", lambda: bridge_dir)

    calls = {"n": 0}

    def _run(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return subprocess.CompletedProcess(args, 0)
        if calls["n"] == 2:
            raise subprocess.CalledProcessError(1, ["npm", "start"])
        raise FileNotFoundError("npm")

    monkeypatch.setattr(subprocess, "run", _run)

    ok = runner.invoke(app, ["channels", "login"])
    assert ok.exit_code == 0
    assert "Starting bridge" in ok.stdout

    fail = runner.invoke(app, ["channels", "login"])
    assert fail.exit_code == 0
    assert "Bridge failed" in fail.stdout

    missing = runner.invoke(app, ["channels", "login"])
    assert missing.exit_code == 0
    assert "npm not found" in missing.stdout
