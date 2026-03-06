import pytest
from typer.testing import CliRunner

from nanobot.cli.commands import app
from nanobot.gateway_runtime.models import (
    GatewayStatus,
    RestartResult,
    RuntimeMode,
    StartResult,
)
from nanobot.gateway_runtime.state_store import (
    GatewayStateStore,
    build_gateway_instance_key,
)

runner = CliRunner()


def test_gateway_defaults_to_daemon_on_darwin(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("nanobot.cli.commands.platform.system", lambda: "Darwin")
    monkeypatch.setattr("nanobot.gateway_runtime.state_store.get_data_dir", lambda: tmp_path)
    calls = {"daemon": 0, "foreground": 0}

    class StubDaemonAdapter:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self, _options) -> StartResult:
            calls["daemon"] += 1
            return StartResult(
                started=True,
                message="gateway_started_background_managed",
                mode=RuntimeMode.BACKGROUND_MANAGED,
            )

        def stop(self, timeout_s: int = 20):
            raise NotImplementedError

        def restart(self, options, timeout_s: int = 20) -> RestartResult:
            raise NotImplementedError

        def status(self) -> GatewayStatus:
            raise NotImplementedError

        def logs(self, follow: bool = True, tail: int = 200) -> int:
            raise NotImplementedError

    monkeypatch.setattr("nanobot.gateway_runtime.facade.PosixDaemonAdapter", StubDaemonAdapter, raising=False)
    monkeypatch.setattr(
        "nanobot.cli.commands.run_gateway_foreground_loop",
        lambda _p, _v, _w, _c: calls.__setitem__("foreground", calls["foreground"] + 1),
    )

    result = runner.invoke(app, ["gateway"])

    assert result.exit_code == 0
    assert "mode=background_managed" in result.stdout
    assert calls["daemon"] == 1
    assert calls["foreground"] == 0


@pytest.mark.parametrize("platform_name", ["Linux", "Windows"])
def test_gateway_defaults_to_legacy_on_linux_and_windows(monkeypatch, tmp_path, platform_name: str) -> None:
    monkeypatch.setattr("nanobot.cli.commands.platform.system", lambda: platform_name)
    monkeypatch.setattr("nanobot.gateway_runtime.state_store.get_data_dir", lambda: tmp_path)
    calls = {"foreground": 0}
    monkeypatch.setattr(
        "nanobot.cli.commands.run_gateway_foreground_loop",
        lambda _p, _v, _w, _c: calls.__setitem__("foreground", calls["foreground"] + 1),
    )

    result = runner.invoke(app, ["gateway"])

    assert result.exit_code == 0
    assert "mode=foreground_legacy" in result.stdout
    assert calls["foreground"] == 1


def test_gateway_foreground_flag_overrides_env_mode(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("nanobot.cli.commands.platform.system", lambda: "Linux")
    monkeypatch.setattr("nanobot.gateway_runtime.state_store.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("nanobot.cli.commands.run_gateway_foreground_loop", lambda _p, _v, _w, _c: None)
    monkeypatch.setenv("NANOBOT_GATEWAY_MODE", "background")

    result = runner.invoke(app, ["gateway", "--foreground"])

    assert result.exit_code == 0
    assert "reason=cli_override_foreground" in result.stdout


def test_gateway_auto_mode_falls_back_to_legacy_when_daemon_start_fails(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("nanobot.cli.commands.platform.system", lambda: "Darwin")
    monkeypatch.setattr("nanobot.gateway_runtime.state_store.get_data_dir", lambda: tmp_path)
    calls = {"foreground": 0}

    class FailingDaemonAdapter:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self, _options) -> StartResult:
            raise RuntimeError("daemon start failed")

        def stop(self, timeout_s: int = 20):
            raise NotImplementedError

        def restart(self, options, timeout_s: int = 20) -> RestartResult:
            raise NotImplementedError

        def status(self) -> GatewayStatus:
            raise NotImplementedError

        def logs(self, follow: bool = True, tail: int = 200) -> int:
            raise NotImplementedError

    monkeypatch.setattr(
        "nanobot.gateway_runtime.facade.PosixDaemonAdapter",
        FailingDaemonAdapter,
        raising=False,
    )
    monkeypatch.setattr(
        "nanobot.cli.commands.run_gateway_foreground_loop",
        lambda _p, _v, _w, _c: calls.__setitem__("foreground", calls["foreground"] + 1),
    )

    result = runner.invoke(app, ["gateway"])

    assert result.exit_code == 0
    assert "preferred_mode=background_managed" in result.stdout.lower()
    assert calls["foreground"] == 1


def test_gateway_explicit_background_fails_when_daemon_start_fails(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("nanobot.cli.commands.platform.system", lambda: "Darwin")
    monkeypatch.setattr("nanobot.gateway_runtime.state_store.get_data_dir", lambda: tmp_path)
    calls = {"foreground": 0}

    class FailingDaemonAdapter:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self, _options) -> StartResult:
            raise RuntimeError("daemon start failed")

        def stop(self, timeout_s: int = 20):
            raise NotImplementedError

        def restart(self, options, timeout_s: int = 20) -> RestartResult:
            raise NotImplementedError

        def status(self) -> GatewayStatus:
            raise NotImplementedError

        def logs(self, follow: bool = True, tail: int = 200) -> int:
            raise NotImplementedError

    monkeypatch.setattr(
        "nanobot.gateway_runtime.facade.PosixDaemonAdapter",
        FailingDaemonAdapter,
        raising=False,
    )
    monkeypatch.setattr(
        "nanobot.cli.commands.run_gateway_foreground_loop",
        lambda _p, _v, _w, _c: calls.__setitem__("foreground", calls["foreground"] + 1),
    )

    result = runner.invoke(app, ["gateway", "--background"])

    assert result.exit_code == 1
    assert "gateway start failed" in result.stdout.lower()
    assert "daemon start failed" in result.stdout.lower()
    assert calls["foreground"] == 0


def test_gateway_restart_status_logs_commands_are_available(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("nanobot.cli.commands.platform.system", lambda: "Windows")
    monkeypatch.setattr("nanobot.gateway_runtime.state_store.get_data_dir", lambda: tmp_path)

    restart_result = runner.invoke(app, ["gateway", "restart"])
    status_result = runner.invoke(app, ["gateway", "status"])
    logs_result = runner.invoke(app, ["gateway", "logs", "--no-follow", "--tail", "5"])

    assert restart_result.exit_code == 0
    assert "legacy" in restart_result.stdout.lower()

    assert status_result.exit_code == 0
    assert "mode: foreground_legacy" in status_result.stdout.lower()

    assert logs_result.exit_code == 0
    assert "foreground mode" in logs_result.stdout.lower()


def test_gateway_rejects_group_background_flag_for_subcommand(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("nanobot.gateway_runtime.state_store.get_data_dir", lambda: tmp_path)

    result = runner.invoke(app, ["gateway", "--background", "status"])

    assert result.exit_code == 1
    assert "cannot be used before gateway" in result.stdout.lower()
    assert "pass options after the subcommand" in result.stdout.lower()


def test_gateway_rejects_group_port_flag_for_subcommand(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("nanobot.gateway_runtime.state_store.get_data_dir", lambda: tmp_path)

    result = runner.invoke(app, ["gateway", "--port", "19000", "restart"])

    assert result.exit_code == 1
    assert "cannot be used before gateway" in result.stdout.lower()
    assert "pass options after the subcommand" in result.stdout.lower()


def test_gateway_rejects_group_default_port_flag_for_subcommand(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("nanobot.gateway_runtime.state_store.get_data_dir", lambda: tmp_path)

    result = runner.invoke(app, ["gateway", "--port", "18790", "restart"])

    assert result.exit_code == 1
    assert "cannot be used before gateway" in result.stdout.lower()
    assert "pass options after the subcommand" in result.stdout.lower()


def test_gateway_start_passes_workspace_and_config_to_foreground_runner(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("nanobot.cli.commands.platform.system", lambda: "Linux")
    monkeypatch.setattr("nanobot.gateway_runtime.state_store.get_data_dir", lambda: tmp_path)
    captured: dict[str, object] = {}

    def fake_run(
        port: int,
        verbose: bool,
        workspace: str | None,
        config_path: str | None,
    ) -> None:
        captured["port"] = port
        captured["verbose"] = verbose
        captured["workspace"] = workspace
        captured["config_path"] = config_path

    monkeypatch.setattr("nanobot.cli.commands.run_gateway_foreground_loop", fake_run)

    result = runner.invoke(
        app,
        [
            "gateway",
            "--port",
            "19100",
            "--workspace",
            "/tmp/work-a",
            "--config",
            "/tmp/cfg-a.json",
        ],
    )

    assert result.exit_code == 0
    assert captured == {
        "port": 19100,
        "verbose": False,
        "workspace": "/tmp/work-a",
        "config_path": "/tmp/cfg-a.json",
    }


def test_gateway_restart_accepts_workspace_and_config_after_subcommand(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("nanobot.cli.commands.platform.system", lambda: "Linux")
    monkeypatch.setattr("nanobot.gateway_runtime.state_store.get_data_dir", lambda: tmp_path)

    result = runner.invoke(
        app,
        [
            "gateway",
            "restart",
            "--workspace",
            "/tmp/work-b",
            "--config",
            "/tmp/cfg-b.json",
        ],
    )

    assert result.exit_code == 0
    assert "gateway restart" in result.stdout.lower()


def test_gateway_rejects_group_workspace_flag_for_subcommand(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("nanobot.gateway_runtime.state_store.get_data_dir", lambda: tmp_path)

    result = runner.invoke(app, ["gateway", "--workspace", "/tmp/work-x", "status"])

    assert result.exit_code == 1
    assert "cannot be used before gateway" in result.stdout.lower()
    assert "pass options after the subcommand" in result.stdout.lower()


def test_gateway_rejects_group_config_flag_for_subcommand(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("nanobot.gateway_runtime.state_store.get_data_dir", lambda: tmp_path)

    result = runner.invoke(app, ["gateway", "--config", "/tmp/cfg-x.json", "logs", "--no-follow"])

    assert result.exit_code == 1
    assert "cannot be used before gateway" in result.stdout.lower()
    assert "pass options after the subcommand" in result.stdout.lower()


def test_gateway_status_targets_instance_scoped_runtime_files(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("nanobot.cli.commands.platform.system", lambda: "Linux")
    monkeypatch.setattr("nanobot.gateway_runtime.state_store.get_data_dir", lambda: tmp_path)

    key_a = build_gateway_instance_key(workspace="/tmp/work-a", config_path="/tmp/cfg-a.json")
    key_b = build_gateway_instance_key(workspace="/tmp/work-b", config_path="/tmp/cfg-b.json")
    assert key_a is not None
    assert key_b is not None

    store_a = GatewayStateStore(data_dir=tmp_path, instance_key=key_a)
    store_b = GatewayStateStore(data_dir=tmp_path, instance_key=key_b)
    store_a.write_pid(4444)
    store_b.clear_pid()

    result_a = runner.invoke(
        app,
        ["gateway", "status", "--workspace", "/tmp/work-a", "--config", "/tmp/cfg-a.json"],
    )
    result_b = runner.invoke(
        app,
        ["gateway", "status", "--workspace", "/tmp/work-b", "--config", "/tmp/cfg-b.json"],
    )

    assert result_a.exit_code == 0
    assert "running: yes" in result_a.stdout.lower()
    assert "pid: 4444" in result_a.stdout.lower()

    assert result_b.exit_code == 0
    assert "running: no" in result_b.stdout.lower()


def test_gateway_start_writes_instance_scoped_state_files(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("nanobot.cli.commands.platform.system", lambda: "Linux")
    monkeypatch.setattr("nanobot.gateway_runtime.state_store.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("nanobot.cli.commands.run_gateway_foreground_loop", lambda _p, _v, _w, _c: None)

    result_a = runner.invoke(
        app,
        ["gateway", "--workspace", "/tmp/work-a", "--config", "/tmp/cfg-a.json"],
    )
    result_b = runner.invoke(
        app,
        ["gateway", "--workspace", "/tmp/work-b", "--config", "/tmp/cfg-b.json"],
    )

    assert result_a.exit_code == 0
    assert result_b.exit_code == 0

    key_a = build_gateway_instance_key(workspace="/tmp/work-a", config_path="/tmp/cfg-a.json")
    key_b = build_gateway_instance_key(workspace="/tmp/work-b", config_path="/tmp/cfg-b.json")
    assert key_a is not None
    assert key_b is not None

    state_a = GatewayStateStore(data_dir=tmp_path, instance_key=key_a).read_state()
    state_b = GatewayStateStore(data_dir=tmp_path, instance_key=key_b).read_state()
    assert state_a is not None
    assert state_b is not None
    assert state_a["mode"] == "foreground_legacy"
    assert state_b["mode"] == "foreground_legacy"
