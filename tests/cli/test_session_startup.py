import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nanobot.cli.commands import app
from nanobot.cli.runtime_config import _load_runtime_config

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolate_config_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nanobot.config.loader._current_config_path", None)


@pytest.mark.parametrize(
    "args",
    [
        ["agent", "--message", "hello"],
        ["gateway", "--foreground"],
        ["gateway", "--background"],
        ["serve"],
        ["webui", "--yes", "--no-open"],
    ],
)
@pytest.mark.parametrize("override", [False, True])
def test_startup_rejects_nested_sessions_before_writing_files(
    tmp_path: Path, args: list[str], override: bool
) -> None:
    workspace = tmp_path / "work [personal]"
    config_path = workspace / "_nanobot" / "config.json"
    config_path.parent.mkdir(parents=True)
    configured_workspace = tmp_path / "safe-workspace" if override else workspace
    config_path.write_text(
        json.dumps({"agents": {"defaults": {"workspace": str(configured_workspace)}}}),
        encoding="utf-8",
    )
    before = config_path.read_bytes()
    command = [*args, "--config", str(config_path)]
    if override:
        command += ["--workspace", str(workspace)]

    result = runner.invoke(app, command)
    output = "".join(result.stdout.splitlines())

    assert result.exit_code == 1, result.output
    assert "chat history must be outside" in output
    assert config_path.name in output
    assert str(workspace) in output
    assert str(config_path.parent / "sessions") in output
    source = "--workspace" if override else "agents.defaults.workspace"
    assert f"Workspace ({source})" in output
    assert "back up" in output
    assert "--config pointing to the moved config file" in output
    assert "Traceback" not in output
    assert config_path.read_bytes() == before
    assert set(workspace.rglob("*")) == {config_path.parent, config_path}


def test_startup_rejects_sessions_equal_to_workspace(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    workspace = tmp_path / "sessions"
    config_path.write_text(
        json.dumps({"agents": {"defaults": {"workspace": str(workspace)}}}),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["gateway", "--config", str(config_path)])

    assert result.exit_code == 1
    assert "chat history must be outside" in result.stdout
    assert not workspace.exists()


def test_workspace_override_can_resolve_conflict_without_saving(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"agents": {"defaults": {"workspace": str(tmp_path)}}}),
        encoding="utf-8",
    )
    before = config_path.read_bytes()
    workspace = tmp_path / "workspace"

    config = _load_runtime_config(str(config_path), str(workspace))

    assert config.workspace_path == workspace
    assert config.runtime_data_dir == tmp_path
    assert config_path.read_bytes() == before
    assert not workspace.exists()
    assert not (tmp_path / "sessions").exists()


def test_webui_checks_resolved_workspace_before_saving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"agents": {"defaults": {"workspace": "${TEST_WORKSPACE}"}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_WORKSPACE", str(tmp_path))
    before = config_path.read_bytes()

    result = runner.invoke(app, ["webui", "--config", str(config_path), "--yes", "--no-open"])

    assert result.exit_code == 1
    assert "chat history must be outside" in result.stdout
    assert config_path.read_bytes() == before
    assert set(tmp_path.iterdir()) == {config_path}
