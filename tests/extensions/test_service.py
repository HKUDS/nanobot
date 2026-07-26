from pathlib import Path
from types import SimpleNamespace

from nanobot.extensions import (
    ExtensionCandidate,
    ExtensionDiagnostic,
    ExtensionManifest,
    ExtensionRuntime,
    ExtensionScope,
    ExtensionSnapshot,
)
from nanobot.extensions.service import ExtensionService
from nanobot.extensions.store import ExtensionStore


async def test_service_installs_untrusted_extension_and_reports_status(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "nanobot.extension.json").write_text(
        """
{
  "apiVersion": 1,
  "id": "sample",
  "name": "Sample",
  "version": "1.0.0",
  "runtime": "declarative"
}
""",
        encoding="utf-8",
    )
    service = ExtensionService(store=ExtensionStore(tmp_path / "installed"))

    installed = await service.install(str(source), kind="local")
    status = await service.status()

    assert installed["record"]["trusted"] is False
    assert status["extensions"][0]["id"] == "sample"
    assert status["extensions"][0]["active"] is False
    assert status["extensions"][0]["managed_by_store"] is True


async def test_service_updates_policy_and_uninstalls(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "nanobot.extension.json").write_text(
        """
{
  "apiVersion": 1,
  "id": "sample",
  "name": "Sample",
  "version": "1.0.0",
  "runtime": "declarative"
}
""",
        encoding="utf-8",
    )
    service = ExtensionService(store=ExtensionStore(tmp_path / "installed"))
    await service.install(str(source), kind="local")

    trusted = await service.set_trusted("sample", True)
    await service.set_enabled("sample", False)
    removed = await service.uninstall("sample")

    assert trusted["record"]["trusted"] is True
    assert removed == {"removed": "sample"}
    assert (await service.status())["extensions"] == []


async def test_service_reports_active_only_after_runtime_activation(
    tmp_path: Path,
) -> None:
    candidate = ExtensionCandidate(
        manifest=ExtensionManifest(
            id="broken",
            name="Broken",
            version="1.0.0",
            runtime=ExtensionRuntime.PYTHON,
            entry="missing:register",
        ),
        scope=ExtensionScope.USER,
        location=tmp_path,
        trusted=True,
    )
    snapshot = ExtensionSnapshot((candidate,), (), ())
    host = SimpleNamespace(
        snapshot=SimpleNamespace(
            catalog=SimpleNamespace(
                candidates=(candidate,),
                diagnostics=(),
                snapshot=snapshot,
            ),
            activation=SimpleNamespace(
                extensions=(),
                diagnostics=(
                    ExtensionDiagnostic(
                        code="activation_failed",
                        extension_id="broken",
                        message="missing module",
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

    assert status["extensions"][0]["active"] is False
    assert status["extensions"][0]["managed_by_store"] is False
    assert status["diagnostics"][0]["code"] == "activation_failed"


async def test_service_reports_projected_native_capability_as_active(
    tmp_path: Path,
) -> None:
    candidate = ExtensionCandidate(
        manifest=ExtensionManifest(
            id="nanobot.core",
            name="nanobot core",
            version="1.0.0",
            runtime=ExtensionRuntime.DECLARATIVE,
        ),
        scope=ExtensionScope.BUILTIN,
        trusted=True,
    )
    snapshot = ExtensionSnapshot((candidate,), (), ())
    host = SimpleNamespace(
        snapshot=SimpleNamespace(
            catalog=SimpleNamespace(
                candidates=(candidate,),
                diagnostics=(),
                snapshot=snapshot,
            ),
            activation=SimpleNamespace(extensions=(), diagnostics=()),
        )
    )
    service = ExtensionService(
        host=host,
        store=ExtensionStore(tmp_path / "installed"),
    )

    status = await service.status()

    assert status["extensions"][0]["active"] is True
    assert status["extensions"][0]["managed_by_store"] is False
