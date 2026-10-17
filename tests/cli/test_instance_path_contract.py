import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nanobot.cli.commands import app
from nanobot.config import home as instance_home
from nanobot.config import loader


@pytest.fixture(autouse=True)
def isolate_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(loader, "_current_config_path", None)
    monkeypatch.setattr(instance_home, "_home_path", None)
    user_home = tmp_path / "user"
    monkeypatch.setenv("HOME", str(user_home))
    monkeypatch.setenv("USERPROFILE", str(user_home))
    monkeypatch.setattr(Path, "home", lambda: user_home)
    monkeypatch.chdir(tmp_path)


@pytest.mark.parametrize("select_home,select_config", [(False, False), (True, False), (False, True), (True, True)])
def test_paths_resolves_instance_without_creating_files(tmp_path, select_home, select_config):
    home = tmp_path / "instance with spaces"
    config = tmp_path / "settings" / "work.json"
    args = ["--home", str(home)] if select_home else []
    args.append("paths")
    if select_config:
        config.parent.mkdir()
        config.write_text("{}", encoding="utf-8")
        args.extend(["--config", str(config)])
    args.append("--json")
    before = set(tmp_path.rglob("*"))

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    expected_home = home if select_home else config.parent if select_config else tmp_path / "user" / ".nanobot"
    assert data["home"] == str(expected_home)
    assert data["config"] == str(config if select_config else expected_home / "config.json")
    assert data["workspace"] == str(expected_home / "workspace")
    assert data["paths"]["auth"] == str(expected_home / "auth")
    assert data["paths"]["sessions"] == str(expected_home / "sessions")
    assert set(tmp_path.rglob("*")) == before


def test_workspace_override_is_relative_to_launch_directory_and_not_saved(tmp_path):
    home = tmp_path / "bot"
    config = tmp_path / "settings" / "work.json"
    config.parent.mkdir()
    original = '{"agents":{"defaults":{"workspace":"./agent-data"}}}'
    config.write_text(original, encoding="utf-8")

    result = CliRunner().invoke(app, [
        "--home", str(home), "paths", "--config", str(config),
        "--workspace", "./override", "--json",
    ])

    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["home"] == str(home)
    assert data["workspace"] == str(tmp_path / "override")
    assert config.read_text(encoding="utf-8") == original


def test_config_only_onboard_creates_agent_under_config_parent(tmp_path):
    config = tmp_path / "bot" / "work.json"

    result = CliRunner().invoke(app, ["onboard", "--config", str(config)])

    assert result.exit_code == 0, result.output
    assert loader.load_config(config).workspace_path == config.parent / "workspace"
    assert (config.parent / "workspace" / "SOUL.md").is_file()


def test_persisted_relative_workspace_uses_home_from_different_launch_directory(tmp_path):
    home = tmp_path / "bot"
    config = tmp_path / "settings" / "work.json"
    config.parent.mkdir()
    config.write_text('{"agents":{"defaults":{"workspace":"./agent-data"}}}', encoding="utf-8")

    result = CliRunner().invoke(app, ["--home", str(home), "paths", "--config", str(config), "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["workspace"] == str(home / "agent-data")


def test_cli_config_selection_does_not_leak_into_next_home(tmp_path):
    first = tmp_path / "first" / "work.json"
    runner = CliRunner()
    result = runner.invoke(app, ["onboard", "--config", str(first)])
    assert result.exit_code == 0, result.output

    second = tmp_path / "second"
    result = runner.invoke(app, ["--home", str(second), "paths", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["home"] == str(second)
    assert data["config"] == str(second / "config.json")
    assert loader.get_selected_config_path() is None


def test_paths_does_not_require_provider_secret_environment(tmp_path, monkeypatch):
    config = tmp_path / "work.json"
    config.write_text('{"providers":{"openai":{"apiKey":"${NANOBOT_PATH_TEST_SECRET}"}}}', encoding="utf-8")
    monkeypatch.delenv("NANOBOT_PATH_TEST_SECRET", raising=False)

    result = CliRunner().invoke(app, ["paths", "--config", str(config), "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["workspace"] == str(tmp_path / "workspace")


def test_implicit_config_symlink_keeps_default_home(tmp_path, create_symlink):
    home = tmp_path / "user" / ".nanobot"
    home.mkdir(parents=True)
    config = tmp_path / "external.json"
    config.write_text("{}", encoding="utf-8")
    create_symlink(home / "config.json", config)

    result = CliRunner().invoke(app, ["paths", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["home"] == str(home)
    assert data["config"] == str(config)
    assert data["workspace"] == str(home / "workspace")


@pytest.mark.parametrize("command", ["status", "logs"])
def test_gateway_inspection_keeps_default_home_when_config_is_a_symlink(tmp_path, monkeypatch, command):
    from nanobot.gateway import GatewayInstance, GatewayRuntime

    user_home = tmp_path / "user"
    home = user_home / ".nanobot"
    home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(user_home))
    monkeypatch.setenv("USERPROFILE", str(user_home))
    external_config = tmp_path / "external.json"
    external_config.write_text("invalid config; inspection must not load it", encoding="utf-8")
    try:
        (home / "config.json").symlink_to(external_config)
    except OSError:
        pytest.skip("symlinks unavailable")
    instance = GatewayInstance.resolve(
        home=home, config_path=external_config, workspace=str(home / "workspace"),
    )
    runtime = GatewayRuntime(paths=instance.paths)
    runtime.paths.logs_dir.mkdir()
    runtime.paths.log_path.write_text("default-home-log-marker\n", encoding="utf-8")
    with runtime.foreground_instance(instance.start_options(port=18790)):
        args = ["gateway", command]
        if command == "logs":
            args.append("--no-follow")
        result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    expected = "Running:yes" if command == "status" else "default-home-log-marker"
    assert expected in "".join(result.output.split())
