"""Atomic installation store and trust state for external extensions."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from nanobot.extensions.codec import MANIFEST_FILENAME, dump_manifest
from nanobot.extensions.discovery import (
    ExtensionDiscoveryResult,
    discover_manifest_root,
)
from nanobot.extensions.manifest import DependencyKind, ExtensionManifest
from nanobot.extensions.package_adapter import AdaptedPackage, adapt_package
from nanobot.extensions.registry import ExtensionScope

_REGISTRY_FILENAME = ".registry.json"


class ExtensionSourceKind(str, Enum):
    LOCAL = "local"
    GIT = "git"
    NPM = "npm"


@dataclass(frozen=True, slots=True)
class InstalledExtension:
    """Persistent installation and policy record."""

    id: str
    version: str
    source: ExtensionSourceKind
    source_ref: str
    integrity: str
    installed_at: str
    enabled: bool = True
    trusted: bool = False
    granted_permissions: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: object) -> InstalledExtension:
        if not isinstance(value, dict):
            raise ValueError("extension registry record must be an object")
        return cls(
            id=str(value["id"]),
            version=str(value["version"]),
            source=ExtensionSourceKind(value["source"]),
            source_ref=str(value["source_ref"]),
            integrity=str(value["integrity"]),
            installed_at=str(value["installed_at"]),
            enabled=bool(value.get("enabled", True)),
            trusted=bool(value.get("trusted", False)),
            granted_permissions=tuple(value.get("granted_permissions", ())),
        )


@dataclass(frozen=True, slots=True)
class InstallResult:
    """Installed package plus metadata-adapter notices."""

    record: InstalledExtension
    package: AdaptedPackage


class ExtensionStore:
    """Own the user extension directory and its atomic registry."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or Path.home() / ".nanobot" / "extensions").expanduser()
        self.registry_path = self.root / _REGISTRY_FILENAME

    def records(self) -> dict[str, InstalledExtension]:
        if not self.registry_path.is_file():
            return {}
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
            rows = data.get("extensions", []) if isinstance(data, dict) else []
            return {
                record.id: record
                for item in rows
                if (record := InstalledExtension.from_mapping(item))
            }
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, ValueError):
            return {}

    def discover(self) -> ExtensionDiscoveryResult:
        """Discover packages and apply persisted enable/trust state."""
        result = discover_manifest_root(self.root, scope=ExtensionScope.USER)
        records = self.records()
        candidates = tuple(
            replace(
                candidate,
                enabled=records.get(candidate.manifest.id, _DEFAULT_RECORD).enabled,
                trusted=records.get(candidate.manifest.id, _DEFAULT_RECORD).trusted,
                granted_permissions=frozenset(
                    records.get(
                        candidate.manifest.id,
                        _DEFAULT_RECORD,
                    ).granted_permissions
                ),
            )
            for candidate in result.candidates
        )
        return ExtensionDiscoveryResult(candidates, result.diagnostics)

    def install_local(
        self,
        source: Path,
        *,
        trusted: bool = False,
    ) -> InstallResult:
        return self._install_from_directory(
            source.resolve(),
            source_kind=ExtensionSourceKind.LOCAL,
            source_ref=str(source.resolve()),
            trusted=trusted,
        )

    def install_git(
        self,
        url: str,
        *,
        ref: str = "",
        trusted: bool = False,
    ) -> InstallResult:
        with tempfile.TemporaryDirectory(prefix="nanobot-extension-git-") as raw:
            checkout = Path(raw) / "checkout"
            command = ["git", "clone", "--depth", "1"]
            if ref:
                command.extend(["--branch", ref])
            command.extend(["--", url, str(checkout)])
            _run(command)
            return self._install_from_directory(
                checkout,
                source_kind=ExtensionSourceKind.GIT,
                source_ref=f"{url}#{ref}" if ref else url,
                trusted=trusted,
            )

    def install_npm(
        self,
        spec: str,
        *,
        trusted: bool = False,
    ) -> InstallResult:
        with tempfile.TemporaryDirectory(prefix="nanobot-extension-npm-") as raw:
            temp = Path(raw)
            output = _run(
                [
                    "npm",
                    "pack",
                    "--ignore-scripts",
                    "--json",
                    "--pack-destination",
                    str(temp),
                    spec,
                ]
            )
            rows = json.loads(output)
            if not isinstance(rows, list) or not rows:
                raise ValueError("npm pack did not return a package")
            archive = temp / rows[0]["filename"]
            checkout = temp / "checkout"
            checkout.mkdir()
            _extract_tar(archive, checkout)
            package_root = checkout / "package"
            return self._install_from_directory(
                package_root,
                source_kind=ExtensionSourceKind.NPM,
                source_ref=spec,
                trusted=trusted,
            )

    def set_enabled(self, extension_id: str, enabled: bool) -> InstalledExtension:
        return self._update_record(extension_id, enabled=enabled)

    def set_trusted(self, extension_id: str, trusted: bool) -> InstalledExtension:
        return self._update_record(extension_id, trusted=trusted)

    def set_permissions(
        self,
        extension_id: str,
        permissions: set[str] | frozenset[str],
    ) -> InstalledExtension:
        return self._update_record(
            extension_id,
            granted_permissions=tuple(sorted(permissions)),
        )

    def uninstall(self, extension_id: str) -> None:
        records = self.records()
        if extension_id not in records:
            raise KeyError(f"extension '{extension_id}' is not installed")
        target = self.root / extension_id
        if target.exists():
            shutil.rmtree(target)
        records.pop(extension_id)
        self._write_records(records)

    def _install_from_directory(
        self,
        source: Path,
        *,
        source_kind: ExtensionSourceKind,
        source_ref: str,
        trusted: bool,
    ) -> InstallResult:
        if not source.is_dir():
            raise ValueError(f"extension source is not a directory: {source}")
        _reject_unsafe_files(source)
        package = adapt_package(source)
        extension_id = package.manifest.id
        self.root.mkdir(parents=True, exist_ok=True)
        staging = self.root / f".install-{uuid4().hex}"
        target = self.root / extension_id
        backup = self.root / f".backup-{uuid4().hex}"
        records = self.records()
        previous = records.get(extension_id)
        try:
            shutil.copytree(
                source,
                staging,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
            )
            if package.generated:
                dump_manifest(package.manifest, staging / MANIFEST_FILENAME)
            _install_node_dependencies(staging, package.manifest)
            integrity = _tree_hash(staging)
            if target.exists():
                target.rename(backup)
            staging.rename(target)
            record = InstalledExtension(
                id=extension_id,
                version=package.manifest.version,
                source=source_kind,
                source_ref=source_ref,
                integrity=integrity,
                installed_at=datetime.now(UTC).isoformat(),
                enabled=previous.enabled if previous else True,
                trusted=trusted or bool(previous and previous.trusted),
                granted_permissions=(
                    previous.granted_permissions if previous else ()
                ),
            )
            records[extension_id] = record
            self._write_records(records)
            shutil.rmtree(backup, ignore_errors=True)
            return InstallResult(record, package)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            if backup.exists():
                shutil.rmtree(target, ignore_errors=True)
                backup.rename(target)
            raise

    def _update_record(
        self,
        extension_id: str,
        **changes: Any,
    ) -> InstalledExtension:
        records = self.records()
        try:
            record = replace(records[extension_id], **changes)
        except KeyError as exc:
            raise KeyError(f"extension '{extension_id}' is not installed") from exc
        records[extension_id] = record
        self._write_records(records)
        return record

    def _write_records(self, records: dict[str, InstalledExtension]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "extensions": [
                {
                    **asdict(record),
                    "source": record.source.value,
                }
                for record in sorted(records.values(), key=lambda item: item.id)
            ],
        }
        temp = self.registry_path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, self.registry_path)


_DEFAULT_RECORD = InstalledExtension(
    id="",
    version="",
    source=ExtensionSourceKind.LOCAL,
    source_ref="",
    integrity="",
    installed_at="",
    enabled=True,
    trusted=False,
    granted_permissions=(),
)


def _install_node_dependencies(root: Path, manifest: ExtensionManifest) -> None:
    package_path = root / "package.json"
    if not package_path.is_file():
        return
    package = json.loads(package_path.read_text(encoding="utf-8"))
    dependencies = package.get("dependencies") if isinstance(package, dict) else None
    if dependencies:
        _run(
            [
                "npm",
                "install",
                "--omit=dev",
                "--ignore-scripts",
                "--no-audit",
                "--no-fund",
            ],
            cwd=root,
        )
    for dependency in manifest.dependencies:
        if dependency.kind is not DependencyKind.NPM or dependency.optional:
            continue
        spec = (
            f"{dependency.name}@{dependency.specifier}"
            if dependency.specifier
            else dependency.name
        )
        _run(
            [
                "npm",
                "install",
                "--save-prod",
                "--save-exact",
                "--ignore-scripts",
                "--no-audit",
                "--no-fund",
                "--",
                spec,
            ],
            cwd=root,
        )


def _run(command: list[str], *, cwd: Path | None = None) -> str:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except FileNotFoundError as exc:
        raise RuntimeError(f"required executable not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(f"{command[0]} failed: {detail}") from exc


def _reject_unsafe_files(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"extension packages cannot contain symlinks: {path}")
        if not path.is_file() and not path.is_dir():
            raise ValueError(f"extension package contains a special file: {path}")


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _extract_tar(archive: Path, target: Path) -> None:
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            destination = (target / member.name).resolve()
            if not destination.is_relative_to(target.resolve()):
                raise ValueError("npm package archive contains a path traversal")
            if member.issym() or member.islnk():
                raise ValueError("npm package archive contains a link")
        bundle.extractall(target)
