import json
from pathlib import Path
from unittest.mock import patch

from nanobot.extensions import (
    ExtensionSourceKind,
    ExtensionStore,
)


def _pi_package(root: Path, *, version: str = "1.0.0") -> Path:
    root.mkdir()
    (root / "index.mjs").write_text("export default function () {}")
    (root / "package.json").write_text(
        json.dumps(
            {
                "name": "store-test",
                "version": version,
                "pi": {"extensions": ["./index.mjs"]},
            }
        )
    )
    return root


def test_store_installs_and_applies_trust_state(tmp_path: Path) -> None:
    source = _pi_package(tmp_path / "source")
    store = ExtensionStore(tmp_path / "extensions")

    installed = store.install_local(source)

    assert installed.record.source is ExtensionSourceKind.LOCAL
    assert installed.record.integrity.startswith("sha256:")
    assert not store.discover().candidates[0].trusted

    store.set_trusted(installed.record.id, True)
    store.set_enabled(installed.record.id, False)

    candidate = store.discover().candidates[0]
    assert candidate.trusted
    assert not candidate.enabled


def test_store_updates_and_uninstalls_atomically(tmp_path: Path) -> None:
    source = _pi_package(tmp_path / "source")
    store = ExtensionStore(tmp_path / "extensions")
    first = store.install_local(source, trusted=True)
    package_json = source / "package.json"
    payload = json.loads(package_json.read_text())
    payload["version"] = "2.0.0"
    package_json.write_text(json.dumps(payload))

    second = store.install_local(source)

    assert second.record.version == "2.0.0"
    assert second.record.trusted
    store.uninstall(first.record.id)
    assert store.records() == {}
    assert not (store.root / first.record.id).exists()


def test_store_rejects_symlinked_package_content(tmp_path: Path) -> None:
    source = _pi_package(tmp_path / "source")
    (source / "outside").symlink_to(tmp_path)
    store = ExtensionStore(tmp_path / "extensions")

    try:
        store.install_local(source)
    except ValueError as exc:
        assert "symlink" in str(exc)
    else:
        raise AssertionError("symlinked package was accepted")


def test_store_restores_previous_package_when_registry_write_fails(
    tmp_path: Path,
) -> None:
    source = _pi_package(tmp_path / "source")
    store = ExtensionStore(tmp_path / "extensions")
    first = store.install_local(source)
    installed_package = store.root / first.record.id / "package.json"
    payload = json.loads((source / "package.json").read_text())
    payload["version"] = "2.0.0"
    (source / "package.json").write_text(json.dumps(payload))

    with patch.object(store, "_write_records", side_effect=OSError("disk full")):
        try:
            store.install_local(source)
        except OSError:
            pass
        else:
            raise AssertionError("registry failure did not abort installation")

    restored = json.loads(installed_package.read_text())
    assert restored["version"] == "1.0.0"
