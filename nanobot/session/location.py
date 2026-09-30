"""Stable workspace identity and private session storage locations."""

from __future__ import annotations

import base64
import errno
import os
import re
import secrets
from contextlib import suppress
from pathlib import Path

from filelock import FileLock

from nanobot.config.paths import get_runtime_subdir
from nanobot.utils.helpers import (
    ensure_dir,
    safe_filename,
)

_WORKSPACE_STATE_DIR = ".nanobot"
_WORKSPACE_ID_FILE = "workspace-id"
_WORKSPACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_SESSION_MIGRATION_LOCK_TIMEOUT_SECONDS = 30


class SessionLocation:
    def __init__(self, workspace: Path, *, sessions_root: Path | None = None):
        canonical_workspace = Path(workspace).expanduser().resolve(strict=False)
        ensure_dir(canonical_workspace)
        root = (
            Path(sessions_root).expanduser().resolve(strict=False)
            if sessions_root is not None
            else get_runtime_subdir("sessions").resolve(strict=False)
        )
        if root == canonical_workspace or root.is_relative_to(canonical_workspace):
            raise RuntimeError(
                "session storage must be outside the agent workspace; "
                "move --config outside --workspace or choose a nested workspace directory"
            )
        ensure_dir(root)
        with suppress(OSError):
            os.chmod(root, 0o700)
        self.workspace = canonical_workspace
        self._migration_lock = FileLock(
            str(root / ".workspace-migration.lock"),
            timeout=_SESSION_MIGRATION_LOCK_TIMEOUT_SECONDS,
        )
        with self._migration_lock:
            workspace_id = self._load_or_create_workspace_id(canonical_workspace, root)
            workspace_id = self._claim_workspace_namespace(
                root,
                canonical_workspace,
                workspace_id,
            )
            self.sessions_dir = ensure_dir(root / workspace_id)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        with suppress(PermissionError, NotImplementedError):
            fd = os.open(path, os.O_RDONLY)
            try:
                os.fsync(fd)
            except OSError as exc:
                if exc.errno != errno.EINVAL:
                    raise
            finally:
                os.close(fd)

    @classmethod
    def _write_text_atomic(cls, path: Path, content: str, *, mode: int = 0o600) -> None:
        tmp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        try:
            with open(tmp, "x", encoding="utf-8") as handle:
                os.chmod(tmp, mode)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
            cls._fsync_directory(path.parent)
        finally:
            tmp.unlink(missing_ok=True)

    @classmethod
    def _read_workspace_id(cls, marker: Path) -> str:
        if marker.is_symlink():
            raise RuntimeError(f"workspace identity marker must not be a symlink: {marker}")
        value = marker.read_text(encoding="utf-8").strip()
        if not _WORKSPACE_ID_RE.fullmatch(value):
            raise RuntimeError(
                f"workspace identity marker is invalid: {marker}; "
                "restore its original 32-character identifier before starting nanobot"
            )
        return value

    @staticmethod
    def _workspace_id_path(workspace: Path) -> Path:
        state_dir = workspace / _WORKSPACE_STATE_DIR
        if state_dir.is_symlink():
            raise RuntimeError(f"workspace state directory must not be a symlink: {state_dir}")
        ensure_dir(state_dir)
        return state_dir / _WORKSPACE_ID_FILE

    @classmethod
    def _find_workspace_namespace(cls, workspace: Path, root: Path) -> str | None:
        """Recover an identity marker removed by cleanup at the same workspace path."""
        matches: list[str] = []
        for sessions_dir in root.iterdir():
            if (
                not _WORKSPACE_ID_RE.fullmatch(sessions_dir.name)
                or sessions_dir.is_symlink()
                or not sessions_dir.is_dir()
            ):
                continue
            marker = sessions_dir / ".workspace"
            if marker.is_symlink() or not marker.is_file():
                continue
            try:
                recorded = Path(marker.read_text(encoding="utf-8").strip()).expanduser()
                recorded = recorded.resolve(strict=False)
                same_workspace = recorded == workspace or (
                    recorded.exists() and recorded.samefile(workspace)
                )
            except (OSError, UnicodeError, ValueError):
                continue
            if same_workspace:
                matches.append(sessions_dir.name)
        if len(matches) > 1:
            raise RuntimeError(
                f"multiple session namespaces claim workspace {workspace}; "
                "remove the stale namespace marker before starting nanobot"
            )
        return matches[0] if matches else None

    @classmethod
    def _load_or_create_workspace_id(cls, workspace: Path, root: Path) -> str:
        marker = cls._workspace_id_path(workspace)
        if marker.exists() or marker.is_symlink():
            return cls._read_workspace_id(marker)

        recovered = cls._find_workspace_namespace(workspace, root)
        if recovered is not None:
            cls._write_text_atomic(marker, f"{recovered}\n")
            return recovered

        workspace_id = secrets.token_hex(16)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(marker, flags, 0o600)
        except FileExistsError:
            return cls._read_workspace_id(marker)
        try:
            payload = f"{workspace_id}\n".encode("ascii")
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            os.fsync(fd)
        except BaseException:
            with suppress(OSError):
                marker.unlink()
            raise
        finally:
            os.close(fd)
        cls._fsync_directory(marker.parent)
        return workspace_id

    @classmethod
    def _replace_workspace_id(cls, workspace: Path, workspace_id: str) -> None:
        cls._write_text_atomic(cls._workspace_id_path(workspace), f"{workspace_id}\n")

    @classmethod
    def _write_workspace_marker(cls, sessions_dir: Path, workspace: Path) -> None:
        cls._write_text_atomic(sessions_dir / ".workspace", f"{workspace}\n")

    @classmethod
    def _claim_workspace_namespace(
        cls,
        root: Path,
        workspace: Path,
        workspace_id: str,
    ) -> str:
        """Bind a stable workspace ID, rotating copied live workspaces apart."""
        for _attempt in range(3):
            sessions_dir = root / workspace_id
            marker = sessions_dir / ".workspace"
            if sessions_dir.is_symlink():
                raise RuntimeError(f"session namespace must not be a symlink: {sessions_dir}")
            if not sessions_dir.exists():
                ensure_dir(sessions_dir)
                cls._write_workspace_marker(sessions_dir, workspace)
                return workspace_id
            if marker.is_symlink():
                raise RuntimeError(f"session workspace marker must not be a symlink: {marker}")
            if not marker.exists():
                if any(sessions_dir.iterdir()):
                    raise RuntimeError(
                        f"session namespace has data but no workspace marker: {sessions_dir}"
                    )
                cls._write_workspace_marker(sessions_dir, workspace)
                return workspace_id

            recorded_text = marker.read_text(encoding="utf-8").strip()
            if not recorded_text:
                raise RuntimeError(f"session workspace marker is empty: {marker}")
            recorded = Path(recorded_text).expanduser().resolve(strict=False)
            if recorded == workspace:
                return workspace_id
            try:
                same_workspace = recorded.exists() and recorded.samefile(workspace)
            except OSError:
                same_workspace = False
            if same_workspace:
                cls._write_workspace_marker(sessions_dir, workspace)
                return workspace_id
            if not recorded.exists():
                # The identity marker travelled with a renamed or moved workspace.
                cls._write_workspace_marker(sessions_dir, workspace)
                return workspace_id

            # Both paths exist and are different: this is a copy, not a move.
            workspace_id = secrets.token_hex(16)
            cls._replace_workspace_id(workspace, workspace_id)

        raise RuntimeError(f"could not allocate an isolated session namespace for {workspace}")

    @staticmethod
    def safe_key(key: str) -> str:
        return safe_filename(key.replace(":", "_"))

    @staticmethod
    def storage_key(key: str) -> str:
        return base64.urlsafe_b64encode(key.encode()).decode().rstrip("=")

    @staticmethod
    def decode_storage_key(stem: str) -> str | None:
        try:
            padding = 4 - len(stem) % 4
            if padding != 4:
                stem += "=" * padding
            return base64.urlsafe_b64decode(stem).decode("utf-8")
        except (ValueError, TypeError, AttributeError, KeyError):
            return None

    @classmethod
    def session_key_from_path(cls, path: Path) -> str | None:
        key = cls.decode_storage_key(path.stem)
        if key is None or cls.storage_key(key) != path.stem:
            return None
        return key
