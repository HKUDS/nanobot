from pathlib import Path

import typer
from rich.console import Console
from typer.testing import CliRunner

from nanobot.cli.gateway import create_gateway_app
from nanobot.config.schema import Config
from nanobot.gateway import GatewayStartOptions, GatewayStatus, RuntimeResult
from nanobot.gateway.service import GatewayServiceOptions, GatewayServiceResult

runner = CliRunner()


class FakeRuntime:
    def __init__(self, tmp_path: Path):
        self.status_value = GatewayStatus(
            running=True,
            pid=12345,
            state_path=tmp_path / "gateway.json",
            log_path=tmp_path / "gateway.log",
            started_at="2026-06-22T00:00:00Z",
            port=18790,
            reason="running",
        )
        self.started_options: GatewayStartOptions | None = None
        self.restarted_options: GatewayStartOptions | None = None
        self.stop_timeout: int | None = None
        self.follow_tail: int | None = None

    def start_background(self, options: GatewayStartOptions) -> RuntimeResult:
        self.started_options = options
        return RuntimeResult(True, "gateway_started_background", self.status_value)

    def restart(self, options: GatewayStartOptions, *, timeout_s: int) -> RuntimeResult:
        self.restarted_options = options
        self.stop_timeout = timeout_s
        return RuntimeResult(True, "gateway_started_background", self.status_value)

    def stop(self, *, timeout_s: int) -> RuntimeResult:
        self.stop_timeout = timeout_s
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


def _test_app(tmp_path: Path, config: Config | None = None):
    app = typer.Typer()
    fake_runtime = FakeRuntime(tmp_path)
    fake_service = FakeServiceInstaller(tmp_path)
    run_calls: list[tuple[Config, int | None]] = []

    def load_runtime_config(_config_path: str | None, _workspace: str | None) -> Config:
        return config or Config()

    def run_gateway(config: Config, *, port: int | None = None) -> None:
        run_calls.append((config, port))

    app.add_typer(
        create_gateway_app(
            console=Console(),
            log_handler_id=0,
            load_runtime_config=load_runtime_config,
            run_gateway=run_gateway,
            runtime_factory=lambda **_kwargs: fake_runtime,
            service_factory=lambda: fake_service,
        ),
        name="gateway",
    )
    return app, fake_runtime, fake_service, run_calls


def test_gateway_default_still_runs_foreground(tmp_path):
    app, _runtime, _service, calls = _test_app(tmp_path)

    result = runner.invoke(app, ["gateway", "--port", "18791"])

    assert result.exit_code == 0
    assert len(calls) == 1
    assert calls[0][1] == 18791


def test_gateway_background_starts_detached_runtime(tmp_path):
    config = Config()
    config.gateway.port = 18792
    app, fake_runtime, _service, _calls = _test_app(tmp_path, config=config)

    result = runner.invoke(app, ["gateway", "--background"])

    assert result.exit_code == 0
    assert "Gateway started in the background" in result.stdout
    assert fake_runtime.started_options == GatewayStartOptions(port=18792)


def test_gateway_rejects_conflicting_modes(tmp_path):
    app, _runtime, _service, _calls = _test_app(tmp_path)

    result = runner.invoke(app, ["gateway", "--foreground", "--background"])

    assert result.exit_code == 1
    assert "--foreground and --background cannot be used together" in result.stdout


def test_gateway_status_uses_runtime(tmp_path):
    app, _runtime, _service, _calls = _test_app(tmp_path)

    result = runner.invoke(app, ["gateway", "status"])

    assert result.exit_code == 0
    assert "Running: yes" in result.stdout
    assert "PID: 12345" in result.stdout


def test_gateway_logs_can_read_without_following(tmp_path):
    app, _runtime, _service, _calls = _test_app(tmp_path)

    result = runner.invoke(app, ["gateway", "logs", "--tail", "12", "--no-follow"])

    assert result.exit_code == 0
    assert "line 12" in result.stdout


def test_gateway_stop_treats_not_running_as_clean(tmp_path):
    app, fake_runtime, _service, _calls = _test_app(tmp_path)

    def fake_stop(*, timeout_s: int) -> RuntimeResult:
        fake_runtime.stop_timeout = timeout_s
        return RuntimeResult(False, "gateway_not_running", fake_runtime.status_value)

    fake_runtime.stop = fake_stop  # type: ignore[method-assign]

    result = runner.invoke(app, ["gateway", "stop", "--timeout", "3"])

    assert result.exit_code == 0
    assert "gateway_not_running" in result.stdout
    assert fake_runtime.stop_timeout == 3


def test_gateway_restart_starts_background_runtime(tmp_path):
    config = Config()
    config.gateway.port = 18793
    app, fake_runtime, _service, _calls = _test_app(tmp_path, config=config)

    result = runner.invoke(app, ["gateway", "restart", "--timeout", "9", "--verbose"])

    assert result.exit_code == 0
    assert "Gateway restarted in the background" in result.stdout
    assert fake_runtime.stop_timeout == 9
    assert fake_runtime.restarted_options == GatewayStartOptions(port=18793, verbose=True)


def test_gateway_install_service_uses_service_installer(tmp_path):
    config = Config()
    config.gateway.port = 18794
    app, _runtime, service, _calls = _test_app(tmp_path, config=config)

    result = runner.invoke(app, ["gateway", "install-service", "--dry-run", "--manager", "systemd"])

    assert result.exit_code == 0
    assert "Gateway service dry run" in result.stdout
    assert service.install_dry_run is True
    assert service.installed_options is not None
    assert service.installed_options.start.port == 18794
    assert service.installed_options.manager == "systemd"


def test_gateway_uninstall_service_uses_service_installer(tmp_path):
    app, _runtime, service, _calls = _test_app(tmp_path)

    result = runner.invoke(
        app,
        ["gateway", "uninstall-service", "--dry-run", "--name", "custom-gateway", "--manager", "systemd"],
    )

    assert result.exit_code == 0
    assert "Gateway service uninstall dry run" in result.stdout
    assert service.uninstalled_name == "custom-gateway"
    assert service.uninstall_manager == "systemd"
