from pathlib import Path

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
