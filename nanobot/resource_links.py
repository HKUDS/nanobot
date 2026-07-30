"""Stable filesystem aliases for resources exposed to the agent.

The aliases in this module are a compatibility view, not a new source of
filesystem permissions.  Callers should keep canonical paths for persistence
and authorization, and use a non-None alias only when presenting a shorter
path to the model.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from filelock import FileLock, Timeout

_LOCK_TIMEOUT_SECONDS = 2
_JUNCTION_TIMEOUT_SECONDS = 2
_NAMESPACE_MARKER = ".nanobot-resource-views.json"
_VIEW_MARKER = ".nanobot-resource-view.json"
_MARKER_VERSION = 1


@dataclass(frozen=True, slots=True)
class ResourceView:
    """The healthy aliases in one immutable resource view."""

    root: Path | None = None
    agent: Path | None = None
    media: Path | None = None
    package: Path | None = None
    warnings: tuple[str, ...] = ()


def ensure_resource_view(
    *,
    data_dir: Path,
    config_path: Path,
    agent_workspace: Path,
    package_root: Path | None = None,
) -> ResourceView:
    """Create, or validate, a stable resource view.

    Expected filesystem failures are deliberately non-fatal.  A caller can
    use each non-None alias and fall back to its canonical path for any alias
    that could not be prepared.
    """

    warnings: list[str] = []
    try:
        canonical_data_dir = _canonical(data_dir)
        canonical_config_path = _canonical(config_path)
        canonical_agent_workspace = _canonical(agent_workspace)
        canonical_package_root = _canonical(
            package_root if package_root is not None else Path(__file__).parent
        )
    except (OSError, RuntimeError) as exc:
        return ResourceView(warnings=(f"Could not resolve resource paths: {_error_text(exc)}",))

    view_id = _resource_view_id(
        config_path=canonical_config_path,
        agent_workspace=canonical_agent_workspace,
        package_root=canonical_package_root,
    )
    namespace_root = canonical_data_dir / "resources"
    view_root = namespace_root / view_id
    media_root = canonical_data_dir / "media"

    for label, target in (
        ("agent", canonical_agent_workspace),
        ("package", canonical_package_root),
    ):
        if _paths_overlap(target, view_root):
            warnings.append(
                f"Resource view overlaps the {label} target and would make recursive "
                f"traversal unsafe: {view_root}"
            )
            return ResourceView(warnings=tuple(warnings))

    try:
        canonical_data_dir.mkdir(parents=True, exist_ok=True)
        if not canonical_data_dir.is_dir():
            warnings.append(f"Resource data directory is not a directory: {canonical_data_dir}")
            return ResourceView(warnings=tuple(warnings))
    except OSError as exc:
        warnings.append(
            f"Could not prepare resource data directory {canonical_data_dir}: {_error_text(exc)}"
        )
        return ResourceView(warnings=tuple(warnings))

    lock_path = canonical_data_dir / ".nanobot-resource-links.lock"
    try:
        with FileLock(str(lock_path), timeout=_LOCK_TIMEOUT_SECONDS):
            return _ensure_resource_view_locked(
                namespace_root=namespace_root,
                view_root=view_root,
                view_id=view_id,
                config_path=canonical_config_path,
                agent_workspace=canonical_agent_workspace,
                media_root=media_root,
                package_root=canonical_package_root,
                warnings=warnings,
            )
    except Timeout:
        warnings.append(f"Timed out waiting for resource view lock: {lock_path}")
    except OSError as exc:
        warnings.append(f"Could not lock resource view {lock_path}: {_error_text(exc)}")

    return ResourceView(warnings=tuple(warnings))


def _ensure_resource_view_locked(
    *,
    namespace_root: Path,
    view_root: Path,
    view_id: str,
    config_path: Path,
    agent_workspace: Path,
    media_root: Path,
    package_root: Path,
    warnings: list[str],
) -> ResourceView:
    namespace_marker = {
        "kind": "nanobot-resource-views",
        "version": _MARKER_VERSION,
    }
    if not _ensure_owned_directory(
        namespace_root,
        marker_name=_NAMESPACE_MARKER,
        marker_payload=namespace_marker,
        label="resource namespace",
        warnings=warnings,
    ):
        return ResourceView(warnings=tuple(warnings))

    view_marker = {
        "kind": "nanobot-resource-view",
        "version": _MARKER_VERSION,
        "view_id": view_id,
        "config_path": _path_identity(config_path),
        "targets": {
            "agent": _path_identity(agent_workspace),
            "media": _path_identity(media_root),
            "package": _path_identity(package_root),
        },
    }
    if not _ensure_owned_directory(
        view_root,
        marker_name=_VIEW_MARKER,
        marker_payload=view_marker,
        label="resource view",
        warnings=warnings,
    ):
        return ResourceView(warnings=tuple(warnings))

    try:
        media_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        warnings.append(f"Could not prepare media target {media_root}: {_error_text(exc)}")

    agent_alias = _ensure_alias(
        view_root / "agent",
        target=agent_workspace,
        view_root=view_root,
        label="agent",
        warnings=warnings,
    )
    media_alias = _ensure_alias(
        view_root / "media",
        target=media_root,
        view_root=view_root,
        label="media",
        warnings=warnings,
    )
    package_alias = _ensure_alias(
        view_root / "package",
        target=package_root,
        view_root=view_root,
        label="package",
        warnings=warnings,
    )
    return ResourceView(
        root=view_root,
        agent=agent_alias,
        media=media_alias,
        package=package_alias,
        warnings=tuple(warnings),
    )


def _resource_view_id(
    *,
    config_path: Path,
    agent_workspace: Path,
    package_root: Path,
) -> str:
    identities = (
        _path_identity(config_path),
        _path_identity(agent_workspace),
        _path_identity(package_root),
    )
    digest = hashlib.sha256(
        "\0".join(identities).encode("utf-8", errors="surrogatepass")
    ).hexdigest()
    return digest[:16]


def _canonical(path: Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _path_identity(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _ensure_owned_directory(
    directory: Path,
    *,
    marker_name: str,
    marker_payload: dict[str, Any],
    label: str,
    warnings: list[str],
) -> bool:
    created = False
    try:
        if os.path.lexists(directory):
            if _is_link_like(directory) or not directory.is_dir():
                warnings.append(f"Unmanaged {label} collision at {directory}")
                return False
        else:
            directory.mkdir()
            created = True
    except OSError as exc:
        warnings.append(f"Could not prepare {label} {directory}: {_error_text(exc)}")
        return False

    marker_path = directory / marker_name
    if not created:
        actual = _read_marker(marker_path, label=label, warnings=warnings)
        if actual is None:
            return False
        if actual != marker_payload:
            warnings.append(f"Ownership marker does not match expected {label}: {marker_path}")
            return False
        return True

    try:
        _write_marker(marker_path, marker_payload)
    except OSError as exc:
        warnings.append(f"Could not write {label} marker {marker_path}: {_error_text(exc)}")
        # Only an empty directory can be removed here.  Never recursively
        # clean a path that another process may have populated.
        try:
            directory.rmdir()
        except OSError:
            pass
        return False
    return True


def _read_marker(
    marker_path: Path,
    *,
    label: str,
    warnings: list[str],
) -> dict[str, Any] | None:
    try:
        if not os.path.lexists(marker_path):
            warnings.append(f"Unmanaged {label} at {marker_path.parent}: ownership marker missing")
            return None
        if _is_link_like(marker_path) or not stat.S_ISREG(marker_path.lstat().st_mode):
            warnings.append(f"Invalid {label} ownership marker: {marker_path}")
            return None
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        warnings.append(f"Could not read {label} marker {marker_path}: {_error_text(exc)}")
        return None

    if not isinstance(payload, dict):
        warnings.append(f"Invalid {label} ownership marker: {marker_path}")
        return None
    return cast(dict[str, Any], payload)


def _write_marker(marker_path: Path, payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    with marker_path.open("x", encoding="utf-8", newline="\n") as marker_file:
        marker_file.write(serialized)
        marker_file.flush()
        os.fsync(marker_file.fileno())


def _ensure_alias(
    alias: Path,
    *,
    target: Path,
    view_root: Path,
    label: str,
    warnings: list[str],
) -> Path | None:
    try:
        if not target.is_dir():
            warnings.append(f"Resource target for {label} is not a directory: {target}")
            return None
    except OSError as exc:
        warnings.append(f"Could not inspect resource target for {label} {target}: {_error_text(exc)}")
        return None

    if _paths_overlap(target, view_root):
        warnings.append(
            f"Resource target for {label} overlaps its view and would create a cycle: {target}"
        )
        return None

    try:
        if os.path.lexists(alias):
            if _is_directory_link(alias) and _link_points_to(alias, target):
                return alias
            warnings.append(f"Resource alias collision for {label} at {alias}")
            return None

        _create_directory_link(alias, target)
        if not _is_directory_link(alias) or not _link_points_to(alias, target):
            warnings.append(f"Created resource alias for {label} could not be verified: {alias}")
            _remove_created_link(alias, label=label, warnings=warnings)
            return None
    except OSError as exc:
        warnings.append(f"Could not create resource alias for {label} at {alias}: {_error_text(exc)}")
        return None

    return alias


def _paths_overlap(first: Path, second: Path) -> bool:
    return first.is_relative_to(second) or second.is_relative_to(first)


def _is_link_like(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        reparse_point = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        return bool(attributes & reparse_point)
    except OSError:
        return False


def _is_directory_link(path: Path) -> bool:
    if not _is_link_like(path):
        return False
    try:
        return path.is_dir()
    except OSError:
        return False


def _link_points_to(alias: Path, target: Path) -> bool:
    try:
        resolved_alias = alias.resolve(strict=True)
        resolved_target = target.resolve(strict=True)
    except (OSError, RuntimeError):
        return False
    return _path_identity(resolved_alias) == _path_identity(resolved_target)


def _remove_created_link(alias: Path, *, label: str, warnings: list[str]) -> None:
    """Remove only a link-like entry created during the current call."""

    if not os.path.lexists(alias) or not _is_link_like(alias):
        return
    try:
        alias.unlink()
        return
    except OSError:
        # Directory junctions on Python 3.11 may require rmdir.  os.rmdir on a
        # reparse point removes the junction itself and does not traverse it.
        try:
            os.rmdir(alias)
            return
        except OSError as exc:
            warnings.append(
                f"Could not remove unverified resource alias for {label} at "
                f"{alias}: {_error_text(exc)}"
            )


def _create_directory_link(alias: Path, target: Path) -> None:
    try:
        alias.symlink_to(target, target_is_directory=True)
        return
    except OSError:
        if not _is_windows():
            raise
    _create_windows_junction(alias, target)


def _is_windows() -> bool:
    return os.name == "nt"


def _create_windows_junction(alias: Path, target: Path) -> None:
    alias_text = str(alias)
    target_text = str(target)
    if any(character in alias_text + target_text for character in ('"', "\r", "\n")):
        raise OSError("Path cannot be safely passed to the Windows junction command")

    # Keep user-controlled paths out of the command string.  Expanding fixed,
    # quoted environment variables also protects cmd metacharacters in paths.
    command_env = os.environ.copy()
    command_env["NANOBOT_RESOURCE_ALIAS"] = alias_text
    command_env["NANOBOT_RESOURCE_TARGET"] = target_text
    command = 'mklink /J "%NANOBOT_RESOURCE_ALIAS%" "%NANOBOT_RESOURCE_TARGET%"'
    try:
        completed = subprocess.run(
            f"cmd.exe /d /v:off /c {command}",
            capture_output=True,
            text=True,
            errors="replace",
            env=command_env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=_JUNCTION_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise OSError(
            f"Timed out creating Windows junction after {_JUNCTION_TIMEOUT_SECONDS}s"
        ) from exc
    if completed.returncode == 0:
        return

    details = (completed.stderr or completed.stdout or "").strip()
    suffix = f": {details}" if details else ""
    raise OSError(f"mklink /J failed with exit code {completed.returncode}{suffix}")


def _error_text(exc: BaseException) -> str:
    return str(exc) or exc.__class__.__name__
