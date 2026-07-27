from __future__ import annotations

from io import StringIO

from rich.console import Console
from typer.testing import CliRunner

from nanobot.cli.extensions import create_extensions_app


class _Service:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def status(self):
        self.calls.append(("status", None))
        return {
            "extensions": [
                {
                    "id": "sample",
                    "name": "Sample",
                    "version": "1.0.0",
                    "description": "Example extension",
                    "enabled": True,
                    "trusted": False,
                    "active": False,
                    "dependencies": [],
                    "permissions": [{"name": "network", "reason": "Fetch data"}],
                    "granted_permissions": [],
                }
            ],
            "diagnostics": [],
        }

    async def install(self, source, *, kind, ref, trusted):
        self.calls.append(("install", (source, kind, ref, trusted)))
        return {
            "record": {
                "id": "sample",
                "version": "1.0.0",
                "trusted": trusted,
            }
        }

    async def set_enabled(self, extension_id, enabled):
        self.calls.append(("enabled", (extension_id, enabled)))
        return {"record": {"id": extension_id}}

    async def set_trusted(self, extension_id, trusted):
        self.calls.append(("trusted", (extension_id, trusted)))
        return {"record": {"id": extension_id}}

    async def set_permissions(self, extension_id, permissions):
        self.calls.append(("permissions", (extension_id, permissions)))
        return {
            "record": {
                "id": extension_id,
                "granted_permissions": sorted(permissions),
            }
        }

    async def uninstall(self, extension_id):
        self.calls.append(("uninstall", extension_id))
        return {"removed": extension_id}


def _runner(service: _Service):
    output = StringIO()
    app = create_extensions_app(
        console=Console(file=output, force_terminal=False),
        service_factory=lambda: service,
    )
    return CliRunner(), app, output


def test_extension_cli_inspects() -> None:
    service = _Service()
    runner, app, output = _runner(service)

    inspected = runner.invoke(app, ["inspect", "sample"])
    assert inspected.exit_code == 0
    assert "Sample" in output.getvalue()
    assert service.calls == [("status", None)]


def test_extension_cli_install_and_policy_commands() -> None:
    service = _Service()
    runner, app, _output = _runner(service)

    assert runner.invoke(app, ["install", "https://example.com/acme.git"]).exit_code == 0
    assert runner.invoke(app, ["trust", "sample"]).exit_code == 0
    assert runner.invoke(app, ["disable", "sample"]).exit_code == 0
    assert runner.invoke(
        app,
        ["permissions", "sample", "network", "filesystem.read"],
    ).exit_code == 0
    assert runner.invoke(app, ["uninstall", "sample", "--yes"]).exit_code == 0

    assert service.calls == [
        ("install", ("https://example.com/acme.git", "git", "", False)),
        ("trusted", ("sample", True)),
        ("enabled", ("sample", False)),
        ("permissions", ("sample", {"network", "filesystem.read"})),
        ("uninstall", "sample"),
    ]
