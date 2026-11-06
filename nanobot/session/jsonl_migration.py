"""One-time JSONL import, introduced in 0.3.6 and removed in 0.5.0.

0.4.x is the final migration release line. Older installations must pass through
that line before upgrading to 0.5.0. Workspace sources move to private backups
after the import commits; failed imports leave their source files unchanged.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict, cast

from loguru import logger

from nanobot.providers.base import ProviderConversationState
from nanobot.session.location import SessionLocation
from nanobot.session.manager import Session

if TYPE_CHECKING:
    from nanobot.session.sqlite_store import SqliteSessionStore

INTRODUCED_VERSION = "0.3.6"
LAST_SUPPORTED_RELEASE_LINE = "0.4.x"
SUNSET_VERSION = "0.5.0"
WORKSPACE_BACKUP_DIR = "jsonl-backup"
_WORKSPACE_SOURCES_KEY = "jsonl_workspace_sources"


class _WorkspaceSource(TypedDict):
    name: str
    digest: str


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


@dataclass(frozen=True)
class _LegacyFile:
    path: Path
    content: bytes
    stat: os.stat_result

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


def _read_file(path: Path) -> _LegacyFile:
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f"JSONL migration requires a regular file: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"JSONL migration requires a regular file: {path}")
        content = handle.read()
        after = os.fstat(handle.fileno())
    if _file_identity(before) != _file_identity(after):
        raise ValueError(f"JSONL migration source changed while reading: {path}")
    return _LegacyFile(path, content, after)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key!r}")
        value[key] = item
    return value


def _record(line: str) -> dict[str, Any]:
    value: object = json.loads(line, object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise ValueError("JSONL records must be objects")
    return cast(dict[str, Any], value)


def read_jsonl(path: Path) -> tuple[Session, list[_LegacyFile]]:
    """Read a complete legacy session, failing without modifying malformed input."""
    source = _read_file(path)
    files = [source]
    header: dict[str, Any] | None = None
    messages: list[dict[str, Any]] = []
    provider: ProviderConversationState | None = None
    provider_seen = False
    # Unicode line separators are valid inside legacy JSON strings.
    for line in source.content.decode("utf-8").split("\n"):
        if not line.strip():
            continue
        item = _record(line)
        if item.get("_type") == "metadata":
            if header is not None:
                raise ValueError(f"multiple session headers: {path}")
            header = item
        elif item.get("_type") == "provider_state":
            if provider_seen:
                raise ValueError(f"multiple provider state records: {path}")
            provider_seen = True
            provider = ProviderConversationState.from_private_record(item.get("state"))
            if provider is None:
                raise ValueError(f"invalid private provider state: {path}")
        else:
            if not isinstance(item.get("role"), str):
                raise ValueError(f"invalid session message: {path}")
            messages.append(item)
    if header is None:
        raise ValueError(f"missing session header: {path}")
    key = header.get("key") or SessionLocation.session_key_from_path(path)
    if not isinstance(key, str) or not key:
        raise ValueError(f"cannot determine session key: {path}")
    metadata: object = header.get("metadata")
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValueError(f"invalid session metadata: {path}")
    fallback = datetime.fromtimestamp(source.stat.st_mtime).isoformat()
    session = Session(
        key=key, messages=messages, metadata=cast(dict[str, Any], metadata),
        created_at=datetime.fromisoformat(header.get("created_at") or fallback),
        updated_at=datetime.fromisoformat(header.get("updated_at") or fallback),
        last_consolidated=header.get("last_archived", header.get("last_consolidated", 0)),
        provider_state=provider,
    )
    checkpoint_path = path.with_suffix(".checkpoint.json")
    if checkpoint_path.exists() or checkpoint_path.is_symlink():
        checkpoint_source = _read_file(checkpoint_path)
        files.append(checkpoint_source)
        checkpoint = _record(checkpoint_source.content.decode("utf-8"))
        if (
            checkpoint_source.stat.st_mtime_ns >= source.stat.st_mtime_ns
            and checkpoint.get("version") == 1
            and checkpoint.get("session_key") == key
            and checkpoint.get("base_updated_at") == session.updated_at.isoformat()
            and checkpoint.get("base_message_count") == len(messages)
        ):
            if not isinstance(checkpoint.get("checkpoint"), dict):
                raise ValueError(f"invalid checkpoint: {checkpoint_path}")
            session.metadata["runtime_checkpoint"] = checkpoint["checkpoint"]
            raw_provider = checkpoint.get("provider_state")
            session.provider_state = ProviderConversationState.from_private_record(raw_provider)
            if raw_provider is not None and session.provider_state is None:
                raise ValueError(f"invalid checkpoint provider state: {checkpoint_path}")
    return session, files


def migrate_jsonl(store: SqliteSessionStore, workspace: Path) -> int:
    """Import atomically, then let the caller commit the durable completion marker.

    A malformed or conflicting source aborts the whole import. The committed
    workspace-source manifest lets startup finish isolation after a crash.
    """
    imported: dict[str, tuple[Path, tuple[str, ...]]] = {}
    workspace_sources: list[_WorkspaceSource] = []
    workspace_directory = workspace / "sessions"
    for directory in (store.path.parent, workspace_directory):
        if directory.is_symlink():
            raise ValueError(f"migration source must not be a symlink: {directory}")
        for path in sorted(directory.glob("*.jsonl")):
            try:
                session, files = read_jsonl(path)
                digests = tuple(source.digest for source in files)
                prior = imported.get(session.key)
                if prior is not None:
                    prior_path, prior_digests = prior
                    if prior_digests != digests or store.load(session.key) != session:
                        raise ValueError(f"duplicate JSONL session key: {prior_path} and {path}")
                else:
                    if store.load(session.key) is not None:
                        raise ValueError(f"session already exists in SQLite: {session.key}")
                    store.save(session)
                    imported[session.key] = path, digests
                if directory == workspace_directory:
                    workspace_sources.extend(
                        {"name": source.path.name, "digest": source.digest} for source in files
                    )
            except Exception as exc:
                raise RuntimeError(
                    f"JSONL migration failed for {path}; source files are unchanged. "
                    "Resolve the invalid or conflicting file and restart."
                ) from exc
    if workspace_sources:
        with store.transaction() as db:
            db.execute("INSERT INTO storage_meta (key, value) VALUES (?, ?)", (
                _WORKSPACE_SOURCES_KEY, json.dumps(workspace_sources),
            ))
    if imported:
        logger.info("Imported {} JSONL sessions into {}", len(imported), store.path)
    return len(imported)


def _workspace_sources(raw: str) -> list[_WorkspaceSource]:
    value: object = json.loads(raw)
    if not isinstance(value, list):
        raise ValueError("workspace migration manifest must be a list")
    sources: list[_WorkspaceSource] = []
    for item in cast(list[object], value):
        if not isinstance(item, dict):
            raise ValueError("workspace migration source must be an object")
        record = cast(dict[str, object], item)
        name, digest = record.get("name"), record.get("digest")
        if (
            not isinstance(name, str) or Path(name).name != name
            or not name.endswith((".jsonl", ".checkpoint.json"))
            or not isinstance(digest, str) or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ValueError("invalid workspace migration source")
        sources.append({"name": name, "digest": digest})
    return sources


def _write_backup(path: Path, source: _LegacyFile) -> None:
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        with os.fdopen(os.open(temporary, flags, 0o600), "wb") as handle:
            handle.write(source.content)
            handle.flush()
            os.utime(temporary, ns=(source.stat.st_atime_ns, source.stat.st_mtime_ns))
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def finish_workspace_migration(store: SqliteSessionStore, workspace: Path) -> None:
    """Durably back up every workspace source before removing any of them.

    The import and its manifest commit together. Cleanup holds the startup write
    lock and clears the manifest only after both backup and removal are durable.
    """
    source_directory = workspace / "sessions"
    backup_directory = store.path.parent / WORKSPACE_BACKUP_DIR
    with store.transaction() as db:
        pending = db.execute(
            "SELECT value FROM storage_meta WHERE key=?", (_WORKSPACE_SOURCES_KEY,),
        ).fetchone()
        if pending is None:
            return
        try:
            sources = _workspace_sources(pending[0])
            if source_directory.is_symlink() or backup_directory.is_symlink():
                raise ValueError("workspace migration directories must not be symlinks")
            backup_directory.mkdir(mode=0o700, exist_ok=True)
            SessionLocation.fsync_directory(backup_directory.parent)
            prepared: list[tuple[Path, os.stat_result]] = []
            for record in sources:
                source_path = source_directory / record["name"]
                backup_path = backup_directory / record["name"]
                source: _LegacyFile | None = None
                try:
                    source = _read_file(source_path)
                except FileNotFoundError:
                    pass
                if source is not None:
                    if source.digest != record["digest"]:
                        raise ValueError(f"workspace migration source changed: {source_path}")
                    prepared.append((source_path, source.stat))
                try:
                    backup = _read_file(backup_path)
                except FileNotFoundError:
                    if source is None:
                        raise ValueError(f"workspace migration source and backup are missing: {source_path}") from None
                    _write_backup(backup_path, source)
                else:
                    if backup.digest != record["digest"]:
                        raise ValueError(f"workspace migration backup differs from its source: {backup_path}")
            SessionLocation.fsync_directory(backup_directory)
            for path, expected in prepared:
                actual = path.lstat()
                if not stat.S_ISREG(actual.st_mode) or _file_identity(actual) != _file_identity(expected):
                    raise ValueError(f"workspace migration source changed: {path}")
            for path, _expected in prepared:
                path.unlink()
            if source_directory.exists():
                SessionLocation.fsync_directory(source_directory)
            db.execute("DELETE FROM storage_meta WHERE key=?", (_WORKSPACE_SOURCES_KEY,))
        except Exception as exc:
            raise RuntimeError(
                f"Could not move legacy sessions out of {source_directory}; "
                f"backups are in {backup_directory}. Resolve the file error and restart."
            ) from exc
