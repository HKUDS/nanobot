import json
import tarfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest

from nanobot.extensions import (
    DependencyKind,
    ExtensionDependency,
    ExtensionManifest,
    ExtensionPermission,
    ExtensionRuntime,
    ExtensionSourceKind,
    ExtensionStore,
    InstalledExtension,
    dump_manifest,
)
from nanobot.extensions.store import _extract_tar


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
    dump_manifest(
        ExtensionManifest(
            id="pi.store-test",
            name="store-test",
            version=version,
            runtime=ExtensionRuntime.PI,
            entry="./index.mjs",
            permissions=(
                ExtensionPermission(name="network"),
                ExtensionPermission(name="filesystem.read"),
            ),
        ),
        root / "nanobot.extension.json",
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
    store.set_permissions(installed.record.id, {"network", "filesystem.read"})

    candidate = store.discover().candidates[0]
    assert candidate.trusted
    assert not candidate.enabled
    assert candidate.granted_permissions == frozenset(
        {"network", "filesystem.read"}
    )


def test_registry_permissions_must_be_a_string_array() -> None:
    with pytest.raises(ValueError, match="array of strings"):
        InstalledExtension.from_mapping(
            {
                "id": "sample",
                "version": "1.0.0",
                "source": "npm",
                "source_ref": "sample",
                "integrity": "sha256:test",
                "installed_at": "2026-01-01T00:00:00Z",
                "granted_permissions": "network",
            }
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source", 3, "source must be a string"),
        ("integrity", "sha256:test", "sha256 digest"),
        (
            "granted_permissions",
            ["network", "network"],
            "cannot contain duplicates",
        ),
    ],
)
def test_registry_record_rejects_ambiguous_metadata(
    field: str,
    value: object,
    message: str,
) -> None:
    payload = {
        "id": "sample",
        "version": "1.0.0",
        "source": "npm",
        "source_ref": "sample",
        "integrity": f"sha256:{'0' * 64}",
        "installed_at": "2026-01-01T00:00:00Z",
    }
    payload[field] = value

    with pytest.raises(ValueError, match=message):
        InstalledExtension.from_mapping(payload)


def test_corrupt_registry_is_diagnostic_and_cannot_be_overwritten(
    tmp_path: Path,
) -> None:
    source = _pi_package(tmp_path / "source")
    store = ExtensionStore(tmp_path / "extensions")
    installed = store.install_local(source)
    original = "{broken"
    store.registry_path.write_text(original)

    discovery = store.discover()

    assert discovery.diagnostics[0].code == "invalid_extension_registry"
    assert not discovery.candidates[0].trusted
    with pytest.raises(ValueError, match="invalid extension registry"):
        store.set_trusted(installed.record.id, True)
    assert store.registry_path.read_text() == original


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"version": 2, "extensions": []},
        {"version": 1, "extensions": {}},
        {
            "version": 1,
            "extensions": [
                {
                    "id": "duplicate",
                    "version": "1.0.0",
                    "source": "npm",
                    "source_ref": "duplicate",
                    "integrity": "sha256:test",
                    "installed_at": "2026-01-01T00:00:00Z",
                },
                {
                    "id": "duplicate",
                    "version": "1.0.0",
                    "source": "npm",
                    "source_ref": "duplicate",
                    "integrity": "sha256:test",
                    "installed_at": "2026-01-01T00:00:00Z",
                },
            ],
        },
    ],
)
def test_store_rejects_invalid_registry_schema(
    tmp_path: Path,
    payload: object,
) -> None:
    store = ExtensionStore(tmp_path / "extensions")
    store.registry_path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="invalid extension registry"):
        store.records(strict=True)


def test_store_updates_and_uninstalls_atomically(tmp_path: Path) -> None:
    source = _pi_package(tmp_path / "source")
    store = ExtensionStore(tmp_path / "extensions")
    first = store.install_local(source, trusted=True)
    package_json = source / "package.json"
    payload = json.loads(package_json.read_text())
    payload["version"] = "2.0.0"
    package_json.write_text(json.dumps(payload))
    manifest_path = source / "nanobot.extension.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["version"] = "2.0.0"
    manifest_path.write_text(json.dumps(manifest))

    second = store.install_local(source)

    assert second.record.version == "2.0.0"
    assert not second.record.trusted
    store.uninstall(first.record.id)
    assert store.records() == {}
    assert not (store.root / first.record.id).exists()


def test_store_preserves_trust_only_for_identical_reinstall(tmp_path: Path) -> None:
    source = _pi_package(tmp_path / "source")
    store = ExtensionStore(tmp_path / "extensions")
    first = store.install_local(source, trusted=True)
    store.set_permissions(first.record.id, {"network"})

    second = store.install_local(source)

    assert second.record.trusted
    assert second.record.granted_permissions == ("network",)


def test_store_revokes_effective_trust_when_package_changes_on_disk(
    tmp_path: Path,
) -> None:
    source = _pi_package(tmp_path / "source")
    store = ExtensionStore(tmp_path / "extensions")
    installed = store.install_local(source, trusted=True)
    target = store.root / installed.record.id
    (target / "index.mjs").write_text("export default function changed() {}")

    discovery = store.discover()

    assert not discovery.candidates[0].trusted
    assert not discovery.candidates[0].integrity_valid
    assert any(
        item.code == "extension_integrity_mismatch"
        for item in discovery.diagnostics
    )


def test_store_ignores_interrupted_transaction_directories(tmp_path: Path) -> None:
    store = ExtensionStore(tmp_path / "extensions")
    hidden = _pi_package(store.root / ".install-interrupted")

    discovery = store.discover()

    assert hidden.is_dir()
    assert discovery.candidates == ()


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


def test_store_accepts_internal_node_dependency_links(tmp_path: Path) -> None:
    source = _pi_package(tmp_path / "source")
    store = ExtensionStore(tmp_path / "extensions")

    def install_dependencies(root: Path, _manifest) -> None:
        executable = root / "node_modules" / "tool" / "cli.js"
        executable.parent.mkdir(parents=True)
        executable.write_text("export {}")
        bin_dir = root / "node_modules" / ".bin"
        bin_dir.mkdir()
        (bin_dir / "tool").symlink_to("../tool/cli.js")

    with patch(
        "nanobot.extensions.store._install_node_dependencies",
        side_effect=install_dependencies,
    ):
        installed = store.install_local(source)

    candidate = store.discover().candidates[0]
    assert candidate.manifest.id == installed.record.id
    assert candidate.integrity_valid


def test_store_rejects_node_dependency_links_outside_package(tmp_path: Path) -> None:
    source = _pi_package(tmp_path / "source")
    outside = tmp_path / "outside.js"
    outside.write_text("export {}")
    store = ExtensionStore(tmp_path / "extensions")

    def install_dependencies(root: Path, _manifest) -> None:
        bin_dir = root / "node_modules" / ".bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "tool").symlink_to(outside)

    with patch(
        "nanobot.extensions.store._install_node_dependencies",
        side_effect=install_dependencies,
    ):
        with pytest.raises(ValueError, match="symlink"):
            store.install_local(source)


def test_store_only_grants_permissions_requested_by_current_manifest(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    dump_manifest(
        ExtensionManifest(
            id="permission-test",
            name="Permission test",
            version="1.0.0",
            runtime=ExtensionRuntime.DECLARATIVE,
            permissions=(ExtensionPermission(name="network.http"),),
        ),
        source / "nanobot.extension.json",
    )
    store = ExtensionStore(tmp_path / "extensions")
    store.install_local(source)

    granted = store.set_permissions("permission-test", {"network.http"})

    assert granted.granted_permissions == ("network.http",)
    with pytest.raises(ValueError, match="not requested"):
        store.set_permissions("permission-test", {"workspace.write"})


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


def test_store_preserves_previous_package_when_backup_rename_fails(
    tmp_path: Path,
) -> None:
    source = _pi_package(tmp_path / "source")
    store = ExtensionStore(tmp_path / "extensions")
    first = store.install_local(source)
    target = store.root / first.record.id
    original_rename = Path.rename

    def fail_backup_rename(path: Path, destination: Path) -> Path:
        if path == target:
            raise OSError("rename failed")
        return original_rename(path, destination)

    with patch.object(Path, "rename", fail_backup_rename):
        with pytest.raises(OSError, match="rename failed"):
            store.install_local(source)

    assert target.is_dir()
    assert first.record.id in store.records(strict=True)


def test_store_removes_first_package_when_registry_write_fails(
    tmp_path: Path,
) -> None:
    source = _pi_package(tmp_path / "source")
    store = ExtensionStore(tmp_path / "extensions")

    with patch.object(store, "_write_records", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            store.install_local(source)

    assert not (store.root / "pi.store-test").exists()


def test_store_restores_package_when_uninstall_registry_write_fails(
    tmp_path: Path,
) -> None:
    source = _pi_package(tmp_path / "source")
    store = ExtensionStore(tmp_path / "extensions")
    installed = store.install_local(source)
    target = store.root / installed.record.id

    with patch.object(store, "_write_records", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            store.uninstall(installed.record.id)

    assert target.exists()
    assert installed.record.id in store.records()


def test_store_installs_declared_npm_runtime_dependency(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "index.mjs").write_text("export default function () {}")
    (source / "package.json").write_text("{}")
    dump_manifest(
        ExtensionManifest(
            id="openclaw.test",
            name="OpenClaw test",
            version="1.0.0",
            runtime=ExtensionRuntime.OPENCLAW,
            entry="./index.mjs",
            dependencies=(
                ExtensionDependency(
                    kind=DependencyKind.NPM,
                    name="openclaw",
                    specifier="2026.7.1",
                ),
            ),
        ),
        source / "nanobot.extension.json",
    )
    store = ExtensionStore(tmp_path / "extensions")
    runtime_package: dict[str, object] = {}

    def capture_runtime_package(
        _command: list[str],
        *,
        cwd: Path | None = None,
    ) -> str:
        assert cwd is not None
        runtime_package.update(json.loads((cwd / "package.json").read_text()))
        return ""

    with patch(
        "nanobot.extensions.store._run",
        side_effect=capture_runtime_package,
    ) as run:
        store.install_local(source)

    command = run.call_args.args[0]
    assert "--omit=dev" in command
    assert "--package-lock=false" in command
    assert runtime_package["dependencies"] == {"openclaw": "2026.7.1"}
    assert json.loads((store.root / "openclaw.test" / "package.json").read_text()) == {}


def test_git_install_fetches_branch_tag_or_commit_ref(tmp_path: Path) -> None:
    store = ExtensionStore(tmp_path / "extensions")
    result = object()

    with (
        patch("nanobot.extensions.store._run") as run,
        patch.object(store, "_install_from_directory", return_value=result),
    ):
        installed = store.install_git(
            "https://example.com/acme/extension.git",
            ref="abc123",
        )

    assert installed is result
    commands = [call.args[0] for call in run.call_args_list]
    assert commands[0][:4] == ["git", "clone", "--filter=blob:none", "--no-checkout"]
    assert commands[1][-5:] == ["--depth", "1", "--", "origin", "abc123"]
    assert commands[2][-3:] == ["checkout", "--detach", "FETCH_HEAD"]


@pytest.mark.parametrize(
    "url",
    [
        "ext::sh -c touch /tmp/owned",
        "file:///tmp/extension",
        "/tmp/extension",
        "https://token@example.com/acme/extension.git",
        "https://example.com/acme/extension.git?token=secret",
        "git@example.com:acme/extension.git#main",
    ],
)
def test_git_install_rejects_unsafe_or_local_sources(
    tmp_path: Path,
    url: str,
) -> None:
    store = ExtensionStore(tmp_path / "extensions")

    with patch("nanobot.extensions.store._run") as run:
        with pytest.raises(ValueError):
            store.install_git(url)

    run.assert_not_called()


@pytest.mark.parametrize(
    "spec",
    (
        "file:/tmp/private",
        "../local-package",
        "https://example.com/package.tgz",
        "git+ssh://git@example.com/package.git",
        "npm:safe-package@1.0.0",
    ),
)
def test_install_npm_rejects_non_registry_package_source(
    tmp_path: Path,
    spec: str,
) -> None:
    store = ExtensionStore(tmp_path / "extensions")

    with patch("nanobot.extensions.store._run") as run:
        with pytest.raises(ValueError, match="registry package name"):
            store.install_npm(spec)

    run.assert_not_called()


@pytest.mark.parametrize(
    "spec",
    ("safe-package", "safe-package@latest", "@scope/safe-package@1.2.3"),
)
def test_install_npm_accepts_registry_package_source(
    tmp_path: Path,
    spec: str,
) -> None:
    store = ExtensionStore(tmp_path / "extensions")

    with patch(
        "nanobot.extensions.store._run",
        side_effect=RuntimeError("validation passed"),
    ) as run:
        with pytest.raises(RuntimeError, match="validation passed"):
            store.install_npm(spec)

    assert run.call_args.args[0][-1] == spec


def test_install_npm_rejects_invalid_pack_metadata(tmp_path: Path) -> None:
    store = ExtensionStore(tmp_path / "extensions")

    with patch("nanobot.extensions.store._run", return_value="[{}]"):
        with pytest.raises(ValueError, match="invalid package metadata"):
            store.install_npm("safe-package")


def test_npm_archive_rejects_extracted_size_over_limit(tmp_path: Path) -> None:
    archive = tmp_path / "package.tgz"
    payload = b"too-large"
    with tarfile.open(archive, "w:gz") as bundle:
        member = tarfile.TarInfo("package/index.mjs")
        member.size = len(payload)
        bundle.addfile(member, BytesIO(payload))

    with patch("nanobot.extensions.store._MAX_EXTRACTED_BYTES", len(payload) - 1):
        with pytest.raises(ValueError, match="extracted limit"):
            _extract_tar(archive, tmp_path / "checkout")


def test_node_dependency_install_rejects_non_registry_specs(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "index.mjs").write_text("export default function () {}")
    (source / "package.json").write_text(
        json.dumps({"dependencies": {"unsafe": "file:/tmp/package"}})
    )
    dump_manifest(
        ExtensionManifest(
            id="pi.unsafe-dependency",
            name="Unsafe dependency",
            version="1.0.0",
            runtime=ExtensionRuntime.PI,
            entry="./index.mjs",
        ),
        source / "nanobot.extension.json",
    )
    store = ExtensionStore(tmp_path / "extensions")

    with patch("nanobot.extensions.store._run") as run:
        with pytest.raises(ValueError, match="npm registry"):
            store.install_local(source)

    run.assert_not_called()


def test_node_dependency_install_includes_required_peers_only(tmp_path: Path) -> None:
    source = _pi_package(tmp_path / "source")
    package_path = source / "package.json"
    package = json.loads(package_path.read_text())
    package.update(
        {
            "peerDependencies": {
                "required-peer": "^1.0.0",
                "optional-peer": "^2.0.0",
            },
            "peerDependenciesMeta": {
                "optional-peer": {"optional": True},
            },
        }
    )
    package_path.write_text(json.dumps(package))
    store = ExtensionStore(tmp_path / "extensions")

    def inspect_install(command: list[str], *, cwd: Path | None = None) -> str:
        assert command[:2] == ["npm", "install"]
        assert cwd is not None
        runtime_package = json.loads((cwd / "package.json").read_text())
        assert runtime_package["dependencies"]["required-peer"] == "^1.0.0"
        assert "optional-peer" not in runtime_package["dependencies"]
        return ""

    with patch("nanobot.extensions.store._run", side_effect=inspect_install):
        store.install_local(source)
