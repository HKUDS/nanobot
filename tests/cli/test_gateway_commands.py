import json
from pathlib import Path

import pytest
import typer
from rich.console import Console
from typer.testing import CliRunner

from nanobot.cli.gateway import _resolved_config_selector, create_gateway_app
from nanobot.config.schema import Config
from nanobot.gateway import (
    GatewayAlreadyRunningError,
    GatewayInstance,
    GatewayRuntimePaths,
    GatewayStartOptions,
    GatewayStatus,
    RuntimeResult,
)
from nanobot.gateway.service import GatewayServiceOptions, GatewayServiceResult

runner = CliRunner()


def test_default_config_has_the_same_gateway_identity_when_explicit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.json"
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    assert _resolved_config_selector(None) == config_path
    assert _resolved_config_selector(str(config_path)) == config_path


class FakeRuntime:
    def __init__(self, tmp_path: Path):
        self.paths = GatewayRuntimePaths.for_instance(data_dir=tmp_path)
        self.status_value = GatewayStatus(
            running=True,
            pid=12345,
            state_path=tmp_path / "gateway.json",
            log_path=tmp_path / "gateway.log",
            started_at="2026-06-22T00:00:00Z",
            port=18790,
            reason="running",
            launch_mode="background",
            lifetime="explicit",
            clients=0,
        )
        self.started_options: GatewayStartOptions | None = None
        self.restarted_options: GatewayStartOptions | None = None
        self.stop_timeout: int | None = None
        self.follow_tail: int | None = None
        self.validated_configs: list[Config] = []

    def start_background(self, options: GatewayStartOptions) -> RuntimeResult:
        self.started_options = options
        return RuntimeResult(True, "gateway_started_background", self.status_value)

    def restart(self, options: GatewayStartOptions, *, timeout_s: int) -> RuntimeResult:
        self.restarted_options = options
        self.stop_timeout = timeout_s
        return RuntimeResult(True, "gateway_started_background", self.status_value)

    def stop(self, *, timeout_s: int) -> RuntimeResult:
        self.stop_timeout = timeout_s
        self.paths.state_path.with_name("gateway.clients.json").unlink(missing_ok=True)
        return RuntimeResult(True, "gateway_stopped", self.status_value)

    def status(self) -> GatewayStatus:
        return self.status_value

    def read_log_tail(self, *, tail: int) -> list[str]:
        return [f"line {tail}"]

    def follow_logs(self, *, tail: int) -> int:
        self.follow_tail = tail
        return 0


class FakeServiceInstaller:
    def __init__(self, tmp_path: Path):
        self.tmp_path = tmp_path
        self.installed_options: GatewayServiceOptions | None = None
        self.install_dry_run: bool | None = None
        self.uninstalled_name: str | None = None
        self.uninstall_manager: str | None = None

    def install(self, options: GatewayServiceOptions, *, dry_run: bool) -> GatewayServiceResult:
        self.installed_options = options
        self.install_dry_run = dry_run
        return GatewayServiceResult(
            True,
            "service_install_dry_run" if dry_run else "service_installed",
            "systemd",
            self.tmp_path / "nanobot-gateway.service",
            (("systemctl", "--user", "daemon-reload"),),
            "[Unit]\nDescription=Nanobot Gateway\n",
        )

    def uninstall(self, *, name: str, manager: str, dry_run: bool) -> GatewayServiceResult:
        self.uninstalled_name = name
        self.uninstall_manager = manager
        return GatewayServiceResult(
            True,
            "service_uninstall_dry_run" if dry_run else "service_uninstalled",
            "systemd",
            self.tmp_path / "nanobot-gateway.service",
            (("systemctl", "--user", "disable", "--now", "nanobot-gateway.service"),),
        )


def _test_app(
    tmp_path: Path,
    config: Config | None = None,
    startup_error: str | None = None,
    run_error: Exception | None = None,
):
    app = typer.Typer()
    fake_runtime = FakeRuntime(tmp_path)
    fake_service = FakeServiceInstaller(tmp_path)
    run_calls: list[
        tuple[Config, int | None, str | None, str | None, GatewayInstance | None]
    ] = []
    prepare_calls: list[tuple[Config, str]] = []

    def load_runtime_config(_config_path: str | None, _workspace: str | None) -> Config:
        return config or Config()

    def run_gateway(
        config: Config,
        *,
        port: int | None = None,
        webui_bundle_mode: str | None = None,
        unconfigured_provider_error: str | None = None,
        gateway_instance: GatewayInstance | None = None,
    ) -> None:
        if run_error is not None:
            raise run_error
        run_calls.append(
            (config, port, webui_bundle_mode, unconfigured_provider_error, gateway_instance)
        )

    def prepare_webui_bundle(config: Config, mode: str) -> None:
        prepare_calls.append((config, mode))

    def validate_startup_config(config: Config) -> str | None:
        fake_runtime.validated_configs.append(config)
        return startup_error

    app.add_typer(
        create_gateway_app(
            console=Console(),
            log_handler_id=0,
            load_runtime_config=load_runtime_config,
            run_gateway=run_gateway,
            validate_startup_config=(
                validate_startup_config if startup_error is not None else None
            ),
            runtime_factory=lambda **_kwargs: fake_runtime,
            service_factory=lambda: fake_service,
            prepare_webui_bundle=prepare_webui_bundle,
        ),
        name="gateway",
    )
    return app, fake_runtime, fake_service, run_calls, prepare_calls


def test_gateway_default_still_runs_foreground(tmp_path):
    app, _runtime, _service, calls, _prepare_calls = _test_app(tmp_path)

    result = runner.invoke(app, ["gateway", "--port", "18791"])

    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0][1] == 18791
    assert calls[0][2] == "warn"
    assert calls[0][4] == GatewayInstance.resolve(
        config_path=_resolved_config_selector(None)
    )


def test_gateway_foreground_reports_a_competing_live_instance(tmp_path):
    status = GatewayStatus(
        running=True,
        pid=12345,
        state_path=tmp_path / "gateway.json",
        log_path=tmp_path / "gateway.log",
        reason="running",
        launch_mode="foreground",
    )
    app, _runtime, _service, _calls, _prepare_calls = _test_app(
        tmp_path,
        run_error=GatewayAlreadyRunningError(status),
    )

    result = runner.invoke(app, ["gateway"])

    assert result.exit_code == 1
    assert "Gateway is already running" in result.output
    assert "PID: 12345" in result.output


def test_config_workspace_does_not_split_the_foreground_instance(tmp_path: Path) -> None:
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "configured-workspace")
    app, _runtime, _service, calls, _prepare_calls = _test_app(tmp_path, config=config)

    result = runner.invoke(app, ["gateway"])

    assert result.exit_code == 0
    assert calls[0][4] == GatewayInstance.resolve(
        config_path=_resolved_config_selector(None)
    )


def test_gateway_foreground_passes_recoverable_provider_error_to_runner(tmp_path):
    setup_error = "No provider is configured."
    app, _runtime, _service, calls, _prepare_calls = _test_app(
        tmp_path,
        startup_error=setup_error,
    )

    result = runner.invoke(app, ["gateway"])

    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0][3] == setup_error
    assert len(_runtime.validated_configs) == 1


@pytest.mark.parametrize(
    ("args", "runtime_attribute"),
    [
        (["gateway", "--background"], "started_options"),
        (["gateway", "restart"], "restarted_options"),
    ],
)
def test_gateway_managed_start_allows_recoverable_provider_error(
    tmp_path,
    args: list[str],
    runtime_attribute: str,
) -> None:
    app, fake_runtime, _service, calls, _prepare_calls = _test_app(
        tmp_path,
        startup_error="No provider is configured.",
    )

    result = runner.invoke(app, args)

    assert result.exit_code == 0
    assert calls == []
    assert len(fake_runtime.validated_configs) == 1
    assert getattr(fake_runtime, runtime_attribute) is not None


def test_gateway_background_starts_detached_runtime(tmp_path):
    config = Config()
    config.gateway.port = 18792
    app, fake_runtime, _service, _calls, prepare_calls = _test_app(tmp_path, config=config)

    result = runner.invoke(app, ["gateway", "--background"])

    assert result.exit_code == 0
    assert "Gateway started in the background" in result.stdout
    assert fake_runtime.started_options == GatewayInstance.resolve(
        config_path=_resolved_config_selector(None)
    ).start_options(port=18792)
    assert prepare_calls == [(config, "warn")]


def test_gateway_background_adopts_an_existing_on_demand_gateway(tmp_path):
    app, fake_runtime, _service, _calls, _prepare_calls = _test_app(tmp_path)
    lease_state = fake_runtime.paths.state_path.with_name("gateway.clients.json")
    lease_state.parent.mkdir(parents=True, exist_ok=True)
    lease_state.write_text('{"auto_stop": true, "clients": {}}', encoding="utf-8")

    def already_running(_options: GatewayStartOptions) -> RuntimeResult:
        lease_state.unlink(missing_ok=True)
        return RuntimeResult(
            False,
            "gateway_already_running",
            fake_runtime.status_value,
            promoted=True,
        )

    fake_runtime.start_background = already_running  # type: ignore[method-assign]

    result = runner.invoke(app, ["gateway", "--background"])

    assert result.exit_code == 0
    assert "promoted to persistent background mode" in result.stdout
    assert "will keep running after all local clients exit" in result.stdout
    assert not lease_state.exists()


def test_gateway_background_reports_an_existing_persistent_gateway(tmp_path):
    app, fake_runtime, _service, _calls, _prepare_calls = _test_app(tmp_path)

    def already_running(_options: GatewayStartOptions) -> RuntimeResult:
        return RuntimeResult(False, "gateway_already_running", fake_runtime.status_value)

    fake_runtime.start_background = already_running  # type: ignore[method-assign]

    result = runner.invoke(app, ["gateway", "--background"])

    assert result.exit_code == 0
    assert "already running in persistent background mode" in result.stdout


def test_gateway_background_does_not_claim_a_foreground_gateway(tmp_path):
    app, fake_runtime, _service, _calls, _prepare_calls = _test_app(tmp_path)
    fake_runtime.status_value = GatewayStatus(
        running=True,
        pid=12345,
        state_path=fake_runtime.paths.state_path,
        log_path=fake_runtime.paths.log_path,
        launch_mode="foreground",
    )

    def already_running(_options: GatewayStartOptions) -> RuntimeResult:
        return RuntimeResult(False, "gateway_already_running", fake_runtime.status_value)

    fake_runtime.start_background = already_running  # type: ignore[method-assign]

    result = runner.invoke(app, ["gateway", "--background"])

    assert result.exit_code == 1
    assert "cannot be" in result.stdout
    assert "detached in place" in result.stdout
    assert "Stop it in its current terminal" in result.stdout


def test_gateway_rejects_conflicting_modes(tmp_path):
    app, _runtime, _service, _calls, _prepare_calls = _test_app(tmp_path)

    result = runner.invoke(app, ["gateway", "--foreground", "--background"])

    assert result.exit_code == 1
    assert "--foreground and --background cannot be used together" in result.stdout


def test_gateway_status_uses_runtime(tmp_path):
    app, _runtime, _service, _calls, _prepare_calls = _test_app(tmp_path)

    result = runner.invoke(app, ["gateway", "status"])

    assert result.exit_code == 0
    assert "Running: yes" in result.stdout
    assert "PID: 12345" in result.stdout
    assert "Launch Mode: background" in result.stdout
    assert "Lifetime: explicit" in result.stdout
    assert "Clients: 0" in result.stdout


def test_gateway_logs_can_read_without_following(tmp_path):
    app, _runtime, _service, _calls, _prepare_calls = _test_app(tmp_path)

    result = runner.invoke(app, ["gateway", "logs", "--tail", "12", "--no-follow"])

    assert result.exit_code == 0
    assert "line 12" in result.stdout


def test_gateway_stop_treats_not_running_as_clean(tmp_path):
    app, fake_runtime, _service, _calls, _prepare_calls = _test_app(tmp_path)
    lease_state = fake_runtime.paths.state_path.with_name("gateway.clients.json")
    lease_state.parent.mkdir(parents=True, exist_ok=True)
    lease_state.write_text('{"auto_stop": true, "clients": {}}', encoding="utf-8")

    def fake_stop(*, timeout_s: int) -> RuntimeResult:
        fake_runtime.stop_timeout = timeout_s
        lease_state.unlink(missing_ok=True)
        return RuntimeResult(False, "gateway_not_running", fake_runtime.status_value)

    fake_runtime.stop = fake_stop  # type: ignore[method-assign]

    result = runner.invoke(app, ["gateway", "stop", "--timeout", "3"])

    assert result.exit_code == 0
    assert "gateway_not_running" in result.stdout
    assert fake_runtime.stop_timeout == 3
    assert not lease_state.exists()


def test_gateway_restart_starts_background_runtime(tmp_path):
    config = Config()
    config.gateway.port = 18793
    app, fake_runtime, _service, _calls, prepare_calls = _test_app(tmp_path, config=config)
    lease_state = fake_runtime.paths.state_path.with_name("gateway.clients.json")
    lease_state.parent.mkdir(parents=True, exist_ok=True)
    lease_state.write_text('{"auto_stop": true, "clients": {}}', encoding="utf-8")

    result = runner.invoke(app, ["gateway", "restart", "--timeout", "9", "--verbose"])

    assert result.exit_code == 0
    assert "Gateway restarted in the background" in result.stdout
    assert fake_runtime.stop_timeout == 9
    assert fake_runtime.restarted_options == GatewayInstance.resolve(
        config_path=_resolved_config_selector(None)
    ).start_options(port=18793, verbose=True)
    assert prepare_calls == [(config, "warn")]
    assert json.loads(lease_state.read_text(encoding="utf-8"))["auto_stop"] is True


def test_gateway_restart_does_not_create_a_persistent_gateway(tmp_path):
    app, fake_runtime, _service, _calls, _prepare_calls = _test_app(tmp_path)

    def not_running(
        _options: GatewayStartOptions, *, timeout_s: int
    ) -> RuntimeResult:
        fake_runtime.stop_timeout = timeout_s
        return RuntimeResult(False, "gateway_not_running", fake_runtime.status_value)

    fake_runtime.restart = not_running  # type: ignore[method-assign]

    result = runner.invoke(app, ["gateway", "restart"])

    assert result.exit_code == 1
    assert "there is nothing to restart" in result.stdout
    assert "nanobot gateway --background" in result.stdout


def test_gateway_restart_explains_foreground_lifecycle(tmp_path):
    app, fake_runtime, _service, _calls, _prepare_calls = _test_app(tmp_path)

    def foreground_restart(
        _options: GatewayStartOptions, *, timeout_s: int
    ) -> RuntimeResult:
        fake_runtime.stop_timeout = timeout_s
        return RuntimeResult(
            False,
            "gateway_foreground_restart_required",
            GatewayStatus(
                running=True,
                pid=12345,
                state_path=fake_runtime.paths.state_path,
                log_path=fake_runtime.paths.log_path,
                launch_mode="foreground",
            ),
        )

    fake_runtime.restart = foreground_restart  # type: ignore[method-assign]

    result = runner.invoke(app, ["gateway", "restart"])

    assert result.exit_code == 1
    assert "attached to a foreground terminal" in result.stdout


def test_gateway_install_service_uses_service_installer(tmp_path):
    config = Config()
    config.gateway.port = 18794
    app, _runtime, service, _calls, _prepare_calls = _test_app(tmp_path, config=config)

    result = runner.invoke(app, ["gateway", "install-service", "--dry-run", "--manager", "systemd"])

    assert result.exit_code == 0
    assert "Gateway service dry run" in result.stdout
    assert service.install_dry_run is True
    assert service.installed_options is not None
    assert service.installed_options.start.port == 18794
    assert service.installed_options.manager == "systemd"


def test_gateway_uninstall_service_uses_service_installer(tmp_path):
    app, _runtime, service, _calls, _prepare_calls = _test_app(tmp_path)

    result = runner.invoke(
        app,
        ["gateway", "uninstall-service", "--dry-run", "--name", "custom-gateway", "--manager", "systemd"],
    )

    assert result.exit_code == 0
    assert "Gateway service uninstall dry run" in result.stdout
    assert service.uninstalled_name == "custom-gateway"
    assert service.uninstall_manager == "systemd"
