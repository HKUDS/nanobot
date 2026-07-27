"""Atomic installation store and trust state for external extensions."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from filelock import FileLock
from pydantic import BaseModel, ConfigDict, field_validator

from nanobot.extensions.codec import MANIFEST_FILENAME, load_manifest
from nanobot.extensions.discovery import (
    ExtensionDiscoveryResult,
    discover_manifest_root,
)
from nanobot.extensions.manifest import ExtensionManifest, validate_extension_id
from nanobot.extensions.registry import ExtensionDiagnostic

_REGISTRY_FILENAME = ".registry.json"
_GIT_SCHEMES = frozenset({"git", "http", "https", "ssh"})
_SCP_GIT_URL = re.compile(
    r"(?:[A-Za-z0-9._-]+@)?[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?:\S+"
)
_SHA256_INTEGRITY = re.compile(r"sha256:[0-9a-f]{64}")


class ExtensionSourceKind(str, Enum):
    LOCAL = "local"
    GIT = "git"


class InstalledExtension(BaseModel):
    """Persistent installation and policy record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    version: str
    source: ExtensionSourceKind
    source_ref: str
    integrity: str
    installed_at: str
    enabled: bool = True
    trusted: bool = False
    granted_permissions: tuple[str, ...] = ()

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return validate_extension_id(value)

    @field_validator("version", "source_ref", "installed_at")
    @classmethod
    def validate_metadata(cls, value: str) -> str:
        if not value:
            raise ValueError("extension registry metadata must use non-empty strings")
        return value

    @field_validator("integrity")
    @classmethod
    def validate_integrity(cls, value: str) -> str:
        if _SHA256_INTEGRITY.fullmatch(value) is None:
            raise ValueError("extension registry integrity must be a sha256 digest")
        return value

    @field_validator("granted_permissions")
    @classmethod
    def reject_duplicate_permissions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("extension granted permissions cannot contain duplicates")
        return value


@dataclass(frozen=True, slots=True)
class InstallResult:
    """Installed package metadata."""

    record: InstalledExtension
    manifest: ExtensionManifest


class ExtensionStore:
    """Own the user extension directory and its atomic registry."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or Path.home() / ".nanobot" / "extensions").expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.root / _REGISTRY_FILENAME
        self._lock = FileLock(str(self.root / ".lock"))

    def records(self, *, strict: bool = False) -> dict[str, InstalledExtension]:
        if not self.registry_path.is_file():
            return {}
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("version") != 1:
                raise ValueError("extension registry must be a version 1 object")
            rows = data.get("extensions")
            if not isinstance(rows, list):
                raise ValueError("extension registry extensions must be an array")
            records: dict[str, InstalledExtension] = {}
            for item in rows:
                record = InstalledExtension.model_validate(item)
                if record.id in records:
                    raise ValueError(
                        f"extension registry contains duplicate id: {record.id}"
                    )
                records[record.id] = record
            return records
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            KeyError,
            ValueError,
        ) as exc:
            if strict:
                raise ValueError(
                    f"invalid extension registry {self.registry_path}: {exc}"
                ) from exc
            return {}

    def discover(self) -> ExtensionDiscoveryResult:
        """Discover packages and apply persisted enable/trust state."""
        result = discover_manifest_root(self.root)
        diagnostics = list(result.diagnostics)
        try:
            records = self.records(strict=True)
        except ValueError as exc:
            records = {}
            diagnostics.append(
                ExtensionDiagnostic(
                    code="invalid_extension_registry",
                    extension_id="",
                    message=str(exc),
                )
            )
        candidates = []
        for candidate in result.candidates:
            record = records.get(candidate.manifest.id)
            trusted = record.trusted if record else False
            integrity_valid = True
            if candidate.location is not None and record is not None:
                try:
                    _reject_unsafe_files(candidate.location)
                    actual_integrity = _tree_hash(candidate.location)
                except (OSError, ValueError) as exc:
                    actual_integrity = ""
                    diagnostics.append(
                        ExtensionDiagnostic(
                            code="extension_integrity_error",
                            extension_id=candidate.manifest.id,
                            message=f"Could not verify installed package: {exc}",
                        )
                    )
                if actual_integrity != record.integrity:
                    trusted = False
                    integrity_valid = False
                    diagnostics.append(
                        ExtensionDiagnostic(
                            code="extension_integrity_mismatch",
                            extension_id=candidate.manifest.id,
                            message=(
                                "Installed package contents changed after installation; "
                                "reinstall it before trusting it again"
                            ),
                        )
                    )
            candidates.append(
                replace(
                    candidate,
                    enabled=record.enabled if record else True,
                    trusted=trusted,
                    integrity_valid=integrity_valid,
                    granted_permissions=frozenset(
                        record.granted_permissions if record else ()
                    ),
                )
            )
        return ExtensionDiscoveryResult(tuple(candidates), tuple(diagnostics))

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
        _validate_git_url(url)
        with tempfile.TemporaryDirectory(prefix="nanobot-extension-git-") as raw:
            checkout = Path(raw) / "checkout"
            if ref:
                _run(
                    [
                        "git",
                        "clone",
                        "--filter=blob:none",
                        "--no-checkout",
                        "--",
                        url,
                        str(checkout),
                    ]
                )
                _run(
                    [
                        "git",
                        "-C",
                        str(checkout),
                        "fetch",
                        "--depth",
                        "1",
                        "--",
                        "origin",
                        ref,
                    ]
                )
                _run(
                    [
                        "git",
                        "-C",
                        str(checkout),
                        "checkout",
                        "--detach",
                        "FETCH_HEAD",
                    ]
                )
            else:
                _run(["git", "clone", "--depth", "1", "--", url, str(checkout)])
            return self._install_from_directory(
                checkout,
                source_kind=ExtensionSourceKind.GIT,
                source_ref=f"{url}#{ref}" if ref else url,
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
        with self._lock:
            records = self.records(strict=True)
            if extension_id not in records:
                raise KeyError(f"extension '{extension_id}' is not installed")
            manifest = load_manifest(
                self.root / extension_id / MANIFEST_FILENAME
            )
            requested = {
                permission.name for permission in manifest.permissions
            }
            unknown = sorted(set(permissions) - requested)
            if unknown:
                raise ValueError(
                    "Cannot grant permissions not requested by the extension: "
                    + ", ".join(unknown)
                )
            return self._update_record_locked(
                records,
                extension_id,
                granted_permissions=tuple(sorted(permissions)),
            )

    def uninstall(self, extension_id: str) -> None:
        with self._lock:
            records = self.records(strict=True)
            if extension_id not in records:
                raise KeyError(f"extension '{extension_id}' is not installed")
            target = self.root / extension_id
            backup = self.root / f".uninstall-{uuid4().hex}"
            if target.exists():
                target.rename(backup)
            try:
                records.pop(extension_id)
                self._write_records(records)
            except Exception:
                if backup.exists():
                    backup.rename(target)
                raise
            shutil.rmtree(backup, ignore_errors=True)

    def _install_from_directory(
        self,
        source: Path,
        *,
        source_kind: ExtensionSourceKind,
        source_ref: str,
        trusted: bool,
    ) -> InstallResult:
        with self._lock:
            return self._install_from_directory_locked(
                source,
                source_kind=source_kind,
                source_ref=source_ref,
                trusted=trusted,
            )

    def _install_from_directory_locked(
        self,
        source: Path,
        *,
        source_kind: ExtensionSourceKind,
        source_ref: str,
        trusted: bool,
    ) -> InstallResult:
        if not source.is_dir():
            raise ValueError(f"extension source is not a directory: {source}")
        if self.root.resolve().is_relative_to(source.resolve()):
            raise ValueError("extension source cannot contain the extension store")
        _reject_unsafe_files(source)
        manifest = load_manifest(source / MANIFEST_FILENAME)
        extension_id = manifest.id
        self.root.mkdir(parents=True, exist_ok=True)
        staging = self.root / f".install-{uuid4().hex}"
        target = self.root / extension_id
        backup = self.root / f".backup-{uuid4().hex}"
        records = self.records(strict=True)
        previous = records.get(extension_id)
        backup_created = False
        target_installed = False
        try:
            shutil.copytree(
                source,
                staging,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
            )
            _reject_unsafe_files(staging)
            integrity = _tree_hash(staging)
            if target.exists():
                target.rename(backup)
                backup_created = True
            staging.rename(target)
            target_installed = True
            requested_permissions = {
                permission.name for permission in manifest.permissions
            }
            unchanged = bool(previous and previous.integrity == integrity)
            record = InstalledExtension(
                id=extension_id,
                version=manifest.version,
                source=source_kind,
                source_ref=source_ref,
                integrity=integrity,
                installed_at=datetime.now(UTC).isoformat(),
                enabled=previous.enabled if previous else True,
                trusted=trusted or bool(unchanged and previous and previous.trusted),
                granted_permissions=(
                    tuple(
                        permission
                        for permission in previous.granted_permissions
                        if permission in requested_permissions
                    )
                    if previous
                    else ()
                ),
            )
            records[extension_id] = record
            self._write_records(records)
            shutil.rmtree(backup, ignore_errors=True)
            return InstallResult(record, manifest)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            if target_installed:
                shutil.rmtree(target, ignore_errors=True)
            if backup_created:
                backup.rename(target)
            raise

    def _update_record(
        self,
        extension_id: str,
        **changes: Any,
    ) -> InstalledExtension:
        with self._lock:
            records = self.records(strict=True)
            return self._update_record_locked(records, extension_id, **changes)

    def _update_record_locked(
        self,
        records: dict[str, InstalledExtension],
        extension_id: str,
        **changes: Any,
    ) -> InstalledExtension:
        try:
            record = records[extension_id].model_copy(update=changes)
        except KeyError as exc:
            raise KeyError(
                f"extension '{extension_id}' is not installed"
            ) from exc
        records[extension_id] = record
        self._write_records(records)
        return record

    def _write_records(self, records: dict[str, InstalledExtension]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "extensions": [
                record.model_dump(mode="json")
                for record in sorted(records.values(), key=lambda item: item.id)
            ],
        }
        temp = self.registry_path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, self.registry_path)


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


def _validate_git_url(url: str) -> None:
    if not isinstance(url, str) or not url.strip() or any(
        character in url for character in ("\0", "\r", "\n")
    ):
        raise ValueError("extension Git source must be a remote repository URL")
    value = url.strip()
    parsed = urlparse(value)
    if parsed.scheme:
        if parsed.scheme.lower() not in _GIT_SCHEMES or not parsed.hostname or not parsed.path:
            raise ValueError(
                "extension Git source must use git, http, https, or ssh"
            )
        if parsed.password or (
            parsed.scheme.lower() in {"http", "https"} and parsed.username
        ):
            raise ValueError(
                "extension Git URLs cannot contain credentials; use a Git credential helper"
            )
        if parsed.query or parsed.fragment:
            raise ValueError(
                "extension Git URLs cannot contain query parameters or fragments; "
                "pass the revision separately"
            )
        return
    if _SCP_GIT_URL.fullmatch(value) is None or any(
        character in value for character in ("?", "#")
    ):
        raise ValueError("extension Git source must be a remote repository URL")


def _reject_unsafe_files(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"extension packages cannot contain symlinks: {path}")
        if not path.is_file() and not path.is_dir():
            raise ValueError(f"extension package contains a special file: {path}")


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(
        item
        for item in root.rglob("*")
        if (item.is_file() or item.is_symlink())
        and "__pycache__" not in item.parts
        and item.suffix not in {".pyc", ".pyo"}
    ):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(b"link\0")
            digest.update(os.fsencode(os.readlink(path)))
            continue
        digest.update(b"file\0")
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"
