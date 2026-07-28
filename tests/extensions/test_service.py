import json
from pathlib import Path
from types import SimpleNamespace

from nanobot.extensions import ExtensionManifest
from nanobot.extensions.registry import (
    ExtensionCandidate,
    ExtensionDiagnostic,
    ExtensionSnapshot,
)
from nanobot.extensions.service import ExtensionService
from nanobot.extensions.store import ExtensionStore


def _package(root: Path) -> Path:
    root.mkdir()
    (root / "extension.py").write_text("def register(api):\n    pass\n")
    (root / "nanobot.extension.json").write_text(
        json.dumps(
            {
                "id": "sample",
                "name": "Sample",
                "version": "1.0.0",
                "entry": "extension:register",
            }
        )
    )
    return root


async def test_service_installs_untrusted_and_updates_policy(tmp_path: Path) -> None:
    service = ExtensionService(store=ExtensionStore(tmp_path / "installed"))

    installed = await service.install(
        str(_package(tmp_path / "source")),
        kind="local",
    )
    trusted = await service.set_trusted("sample", True)
    await service.set_enabled("sample", False)

    assert installed["record"]["trusted"] is False
    assert "runtime" not in installed["manifest"]
    assert trusted["record"]["trusted"] is True
    assert (await service.status())["extensions"][0]["enabled"] is False


async def test_service_reports_activation_failure(tmp_path: Path) -> None:
    candidate = ExtensionCandidate(
        ExtensionManifest(id="broken", name="Broken", version="1.0.0"),
        location=tmp_path,
        trusted=True,
    )
    host = SimpleNamespace(
        snapshot=SimpleNamespace(
            catalog=SimpleNamespace(
                candidates=(candidate,),
                diagnostics=(),
                snapshot=ExtensionSnapshot((candidate,), ()),
            ),
            activation=SimpleNamespace(
                extensions=(),
                diagnostics=(
                    ExtensionDiagnostic(
                        "activation_failed",
                        "broken",
                        "missing module",
                    ),
                ),
            ),
        )
    )
    service = ExtensionService(
        host=host,
        store=ExtensionStore(tmp_path / "installed"),
    )

    status = await service.status()

    assert not status["extensions"][0]["active"]
    assert status["diagnostics"][0]["code"] == "activation_failed"


async def test_service_uninstalls_package(tmp_path: Path) -> None:
    service = ExtensionService(store=ExtensionStore(tmp_path / "installed"))
    await service.install(str(_package(tmp_path / "source")), kind="local")

    assert await service.uninstall("sample") == {"removed": "sample"}
    assert (await service.status())["extensions"] == []
