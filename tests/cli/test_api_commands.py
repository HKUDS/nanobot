from pathlib import Path

import typer
from rich.console import Console
from typer.testing import CliRunner

from nanobot.cli.api import create_api_app
from nanobot.config.schema import Config
from nanobot.process_runtime import ProcessStatus

runner = CliRunner()


class FakeRuntime:
    def __init__(self, status: ProcessStatus) -> None:
        self.status_value = status

    def effective_status(self, *, host: str, port: int, **_kwargs) -> ProcessStatus:
        return self.status_value


def _test_app(tmp_path: Path, status: ProcessStatus) -> typer.Typer:
    app = typer.Typer()

    def load_runtime_config(_config_path, _workspace) -> Config:
        return Config()

    app.add_typer(
        create_api_app(
            console=Console(),
            load_runtime_config=load_runtime_config,
            runtime_factory=lambda **_kwargs: FakeRuntime(status),
        ),
        name="api",
    )
    return app


def _status(tmp_path: Path, *, running: bool, managed: bool, reason: str) -> ProcessStatus:
    return ProcessStatus(
        running=running,
        pid=1234 if running and managed else None,
        state_path=tmp_path / "api.json",
        log_path=tmp_path / "api.log",
        port=8900 if running else None,
        reason=reason,
        managed=managed,
    )


def test_api_status_reports_externally_managed(tmp_path) -> None:
    app = _test_app(tmp_path, _status(tmp_path, running=True, managed=False, reason="external"))
    config_path = str((tmp_path / "config.json").resolve())

    result = runner.invoke(app, ["api", "status", "--config", config_path])

    assert result.exit_code == 0
    assert "Running: yes" in result.output
    assert "Managed: no" in result.output
    assert "Reason: external" in result.output
    assert "Endpoint: http://127.0.0.1:8900/v1" in result.output
    assert f"Config: {config_path}" in result.output
    assert "Port: 8900" in result.output


def test_api_status_reports_managed_running(tmp_path) -> None:
    app = _test_app(tmp_path, _status(tmp_path, running=True, managed=True, reason="running"))

    result = runner.invoke(app, ["api", "status"])

    assert result.exit_code == 0
    assert "Running: yes" in result.output
    assert "Managed: yes" in result.output
    assert "PID: 1234" in result.output


def test_api_status_reports_off(tmp_path) -> None:
    app = _test_app(tmp_path, _status(tmp_path, running=False, managed=False, reason="not_started"))

    result = runner.invoke(app, ["api", "status"])

    assert result.exit_code == 0
    assert "Running: no" in result.output
    assert "Managed: no" in result.output
    assert "Reason: not_started" in result.output
