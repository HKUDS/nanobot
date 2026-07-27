import json
from pathlib import Path

import pytest

from nanobot.extensions.store import (
    ExtensionSourceKind,
    ExtensionStore,
    InstalledExtension,
)


def _package(root: Path, *, version: str = "1.0.0") -> Path:
    root.mkdir()
    (root / "extension.py").write_text("def register(api):\n    pass\n")
    (root / "nanobot.extension.json").write_text(
        json.dumps(
            {
                "id": "store.test",
                "name": "Store test",
                "version": version,
                "entry": "extension:register",
                "permissions": [
                    {"name": "network", "reason": "Fetch selected sources."}
                ],
            }
        )
    )
    return root


def test_local_install_is_atomic_and_untrusted_by_default(tmp_path: Path) -> None:
    store = ExtensionStore(tmp_path / "installed")

    result = store.install_local(_package(tmp_path / "source"))

    assert result.record.source is ExtensionSourceKind.LOCAL
    assert result.record.integrity.startswith("sha256:")
    assert result.manifest.id == "store.test"
    assert not store.discover().candidates[0].trusted


def test_policy_updates_survive_discovery(tmp_path: Path) -> None:
    store = ExtensionStore(tmp_path / "installed")
    store.install_local(_package(tmp_path / "source"))

    store.set_trusted("store.test", True)
    store.set_enabled("store.test", False)
    store.set_permissions("store.test", {"network"})

    candidate = store.discover().candidates[0]
    assert candidate.trusted
    assert not candidate.enabled
    assert candidate.granted_permissions == frozenset({"network"})


def test_unknown_permission_cannot_be_granted(tmp_path: Path) -> None:
    store = ExtensionStore(tmp_path / "installed")
    store.install_local(_package(tmp_path / "source"))

    with pytest.raises(ValueError, match="not requested"):
        store.set_permissions("store.test", {"filesystem.write"})


def test_modified_install_loses_effective_trust(tmp_path: Path) -> None:
    store = ExtensionStore(tmp_path / "installed")
    store.install_local(_package(tmp_path / "source"), trusted=True)
    (store.root / "store.test" / "extension.py").write_text("changed = True\n")

    discovery = store.discover()

    assert not discovery.candidates[0].trusted
    assert not discovery.candidates[0].integrity_valid
    assert discovery.diagnostics[0].code == "extension_integrity_mismatch"


def test_changed_reinstall_revokes_trust_but_identical_reinstall_preserves_it(
    tmp_path: Path,
) -> None:
    source = _package(tmp_path / "source")
    store = ExtensionStore(tmp_path / "installed")
    store.install_local(source, trusted=True)

    identical = store.install_local(source)
    assert identical.record.trusted

    (source / "extension.py").write_text("changed = True\n")
    changed = store.install_local(source)
    assert not changed.record.trusted


def test_install_rejects_missing_manifest_and_symlinks(tmp_path: Path) -> None:
    store = ExtensionStore(tmp_path / "installed")
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="cannot read extension manifest"):
        store.install_local(empty)

    source = _package(tmp_path / "source")
    (source / "outside").symlink_to(tmp_path)
    with pytest.raises(ValueError, match="symlink"):
        store.install_local(source)


def test_install_rejects_source_containing_store(tmp_path: Path) -> None:
    source = _package(tmp_path / "source")
    store = ExtensionStore(source / "installed")

    with pytest.raises(ValueError, match="cannot contain the extension store"):
        store.install_local(source)


def test_registry_validation_and_uninstall(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="sha256 digest"):
        InstalledExtension.model_validate(
            {
                "id": "sample",
                "version": "1.0.0",
                "source": "local",
                "source_ref": "/tmp/sample",
                "integrity": "invalid",
                "installed_at": "2026-01-01T00:00:00Z",
            }
        )

    store = ExtensionStore(tmp_path / "installed")
    store.install_local(_package(tmp_path / "source"))
    store.uninstall("store.test")

    assert store.records() == {}
    assert not (store.root / "store.test").exists()


def test_corrupt_registry_is_diagnostic_and_not_overwritten(tmp_path: Path) -> None:
    store = ExtensionStore(tmp_path / "installed")
    store.install_local(_package(tmp_path / "source"))
    store.registry_path.write_text("{broken")

    discovery = store.discover()

    assert discovery.diagnostics[0].code == "invalid_extension_registry"
    with pytest.raises(ValueError, match="invalid extension registry"):
        store.set_trusted("store.test", True)
    assert store.registry_path.read_text() == "{broken"
