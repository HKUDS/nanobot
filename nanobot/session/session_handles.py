"""Persistent, globally unique handles for sessions.

The directory is the trusted seam between public ``@name`` handles and private
session keys. Titles and transcript text never participate in handle allocation.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import threading
import unicodedata
import uuid
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TypedDict, cast, runtime_checkable

from filelock import FileLock

from nanobot.security.workspace_access import WORKSPACE_SCOPE_METADATA_KEY
from nanobot.session.manager import SessionManager

SESSION_HANDLE_DIRECTORY_VERSION = 1
SESSION_HANDLE_COLOR_SLOTS = 8

_STORE_FILENAME = ".session-handles.json"
_LOCK_FILENAME = ".session-handles.lock"
_MAX_STORE_BYTES = 512 * 1024
_MAX_HANDLES = 2_000
_MAX_SESSION_KEY_CHARS = 512
_MAX_NAME_CHARS = 24
_HANDLE_ID_RE = re.compile(r"^handle_[0-9a-f]{32}$")
_HANDLE_RE = re.compile(r"^[a-z]{2,16}(?:-(?:[2-9]|[1-9][0-9]+))?$")

# Short, pronounceable names are easier to remember and type than conversation
# title slugs. The UUID-backed starting offset keeps allocation varied while the
# circular scan and file lock make it deterministic and collision-free.
_HANDLE_NAMES = tuple(
    """
    ada abby abel adan adil aiko alba alex alia alma amir amos anil anja ari arlo
    asha ava bea ben blair bo bruno cal cam cara carl cato celia chen chloe clara
    cleo cora dahlia daisy dana dante dara dario dev dina drew eden eira eli elio
    ella elsa emil emma enzo eric esme eva farah felix finn flora freya gabe gia
    gwen hana harper hazel heidi hugo ida ila iman ines iris ivan ivo jade jamie
    joel jona jude jules juno kai ken kira lana lara leif lena leo lia liam lila
    lina liv lois lola luca lucy mabel mae malik mara marco maya mila mina mira
    nadia nate neve nico nina noah nora omar oren orla otto owen pablo piper priya
    quinn rafi remy ren rhea rio robin rosa ruby sage sami sara sena shay silas
    sofia sol sora tariq tavi tess theo timo uma val vera vida wes will wren xena
    yara yasmin yuki zara zeno zoe
    """.split()
)


class SessionHandleDirectoryError(RuntimeError):
    """The persisted session-handle directory could not be used safely."""


class SessionHandlePayload(TypedDict):
    """Public handle fields safe to return to a client or model boundary."""

    id: str
    name: str
    color_slot: int


@dataclass(frozen=True, slots=True)
class SessionHandle:
    """Trusted handle for one persisted session.

    ``session_key`` and ``workspace`` remain backend-only routing fields.
    """

    id: str
    name: str
    color_slot: int
    session_key: str
    workspace: Path

    def public_payload(self) -> SessionHandlePayload:
        return {
            "id": self.id,
            "name": self.name,
            "color_slot": self.color_slot,
        }


@dataclass(frozen=True, slots=True)
class SessionHandleSnapshot:
    """Trusted session fields used to provision handles in one batch."""

    session_key: str
    workspace: Path


@runtime_checkable
class SessionHandleDirectoryProtocol(Protocol):
    """Narrow directory contract consumed by session-message delivery."""

    def handle_for_session(self, key: str) -> SessionHandle | None: ...

    def resolve(self, name: str) -> SessionHandle | None: ...


@dataclass(frozen=True, slots=True)
class _StoredHandle:
    id: str
    session_key: str
    workspace: str
    name: str


@dataclass(frozen=True, slots=True)
class _SessionDescriptor:
    workspace: Path


class SessionHandleDirectory:
    """Atomically persist globally unique ``@name`` handles for sessions."""

    def __init__(self, sessions: SessionManager) -> None:
        self._sessions = sessions
        self.store_path = sessions.sessions_dir / _STORE_FILENAME
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self._thread_lock = threading.RLock()
        self._file_lock = FileLock(str(sessions.sessions_dir / _LOCK_FILENAME))

    def ensure_many(self, session_keys: list[str]) -> dict[str, SessionHandle]:
        """Provision persisted sessions with at most one atomic store write."""
        keys = list(dict.fromkeys(_clean_session_key(key) for key in session_keys))
        descriptors = {
            key: descriptor
            for key in keys
            if (descriptor := self._session_descriptor(key)) is not None
        }
        return self._ensure_descriptors(keys, descriptors)

    def ensure_snapshot_many(
        self,
        snapshots: list[SessionHandleSnapshot],
    ) -> dict[str, SessionHandle]:
        """Provision trusted index snapshots without rereading session files."""
        keys: list[str] = []
        descriptors: dict[str, _SessionDescriptor] = {}
        for snapshot in snapshots:
            key = _clean_session_key(snapshot.session_key)
            if key in descriptors:
                continue
            keys.append(key)
            descriptors[key] = _SessionDescriptor(
                workspace=_canonical_workspace(snapshot.workspace),
            )
        return self._ensure_descriptors(keys, descriptors)

    def _ensure_descriptors(
        self,
        keys: list[str],
        descriptors: dict[str, _SessionDescriptor],
    ) -> dict[str, SessionHandle]:
        with self._thread_lock, self._file_lock:
            records = self._load_unlocked()
            by_key = {item.session_key: item for item in records}
            changed = False
            handles: dict[str, SessionHandle] = {}
            for key in keys:
                descriptor = descriptors.get(key)
                if descriptor is None:
                    continue
                existing = by_key.get(key)
                workspace = str(descriptor.workspace)
                if existing is not None and _same_workspace(existing.workspace, workspace):
                    handles[key] = _handle(existing, descriptor)
                    continue

                if existing is not None:
                    records.remove(existing)
                handle_id = existing.id if existing is not None else f"handle_{uuid.uuid4().hex}"
                record = _StoredHandle(
                    id=handle_id,
                    session_key=key,
                    workspace=workspace,
                    name=_allocate_name(
                        handle_id,
                        records,
                        preferred=existing.name if existing is not None else None,
                    ),
                )
                records.append(record)
                by_key[key] = record
                handles[key] = _handle(record, descriptor)
                changed = True
            if changed:
                self._save_unlocked(records)
            return handles

    def handle_for_session(self, key: str) -> SessionHandle | None:
        """Return (and lazily provision) the trusted handle for *key*."""
        clean_key = _clean_session_key(key)
        handle = self.ensure_many([clean_key]).get(clean_key)
        if handle is None:
            self.remove_many([clean_key])
        return handle

    def resolve(self, name: str) -> SessionHandle | None:
        """Resolve a globally unique bare or ``@``-prefixed handle."""
        try:
            clean_name = normalize_session_handle(name)
        except ValueError:
            return None

        with self._thread_lock, self._file_lock:
            candidate = next(
                (
                    item
                    for item in self._load_unlocked()
                    if item.name == clean_name
                ),
                None,
            )
        if candidate is None:
            return None

        current = self.handle_for_session(candidate.session_key)
        if current is None or current.name != clean_name:
            return None
        return current

    def list_all(self) -> list[SessionHandle]:
        """List all live handles, ordered by handle."""
        with self._thread_lock, self._file_lock:
            keys = [item.session_key for item in self._load_unlocked()]
        handles = [self.handle_for_session(key) for key in keys]
        return sorted(
            (handle for handle in handles if handle is not None),
            key=lambda handle: handle.name,
        )

    def remove_many(self, session_keys: Iterable[str]) -> int:
        """Atomically remove handles bound to *session_keys*."""
        keys = {_clean_session_key(key) for key in session_keys}
        if not keys:
            return 0
        with self._thread_lock, self._file_lock:
            records = self._load_unlocked()
            remaining = [item for item in records if item.session_key not in keys]
            removed = len(records) - len(remaining)
            if removed == 0:
                return 0
            self._save_unlocked(remaining)
            return removed

    def _session_descriptor(self, session_key: str) -> _SessionDescriptor | None:
        payload = self._sessions.read_session_metadata(session_key)
        if payload is None:
            return None
        raw_metadata = cast(object, payload.get("metadata"))
        metadata = cast(dict[str, Any], raw_metadata) if isinstance(raw_metadata, dict) else {}
        return _SessionDescriptor(
            workspace=_workspace_from_metadata(metadata, default=self._sessions.workspace),
        )

    def _load_unlocked(self) -> list[_StoredHandle]:
        if not self.store_path.is_file():
            return []
        try:
            if self.store_path.stat().st_size > _MAX_STORE_BYTES:
                raise SessionHandleDirectoryError("session handle store is too large")
            raw: object = json.loads(self.store_path.read_text(encoding="utf-8"))
        except SessionHandleDirectoryError:
            raise
        except (OSError, json.JSONDecodeError) as exc:
            raise SessionHandleDirectoryError(
                f"session handle store could not be read: {self.store_path}"
            ) from exc
        if not isinstance(raw, dict):
            raise SessionHandleDirectoryError("session handle store must be a JSON object")
        data = cast(dict[str, Any], raw)
        version = data.get("version")
        raw_records = data.get("handles")
        if version != SESSION_HANDLE_DIRECTORY_VERSION or not isinstance(raw_records, list):
            raise SessionHandleDirectoryError("unsupported session handle store format")
        record_values = cast(list[object], raw_records)
        if len(record_values) > _MAX_HANDLES:
            raise SessionHandleDirectoryError("session handle store has too many records")

        records = [_parse_record(raw_record) for raw_record in record_values]
        _validate_unique_records(records, globally_unique_names=False)
        records, repaired = _repair_globally_duplicate_names(records)
        _validate_unique_records(records)
        if repaired:
            self._save_unlocked(records)
        return records

    def _save_unlocked(self, records: list[_StoredHandle]) -> None:
        if len(records) > _MAX_HANDLES:
            raise SessionHandleDirectoryError("session handle store has too many records")
        _validate_unique_records(records)
        payload = {
            "version": SESSION_HANDLE_DIRECTORY_VERSION,
            "handles": [
                {
                    "id": item.id,
                    "session_key": item.session_key,
                    "workspace": item.workspace,
                    "name": item.name,
                }
                for item in sorted(records, key=lambda item: item.session_key)
            ],
        }
        encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if len(encoded) > _MAX_STORE_BYTES:
            raise SessionHandleDirectoryError("session handle store is too large")
        _atomic_write(self.store_path, encoded)


def normalize_session_handle(value: str) -> str:
    """Return the canonical bare session handle accepted by the directory."""
    name = unicodedata.normalize("NFKC", value.strip())
    if name.startswith("@"):
        name = name[1:]
    name = name.casefold()
    if not name or len(name) > _MAX_NAME_CHARS or _HANDLE_RE.fullmatch(name) is None:
        raise ValueError("session handle must be a short ASCII name, optionally with a number")
    return name


def _parse_record(raw: object) -> _StoredHandle:
    if not isinstance(raw, dict):
        raise SessionHandleDirectoryError("session handle records must be JSON objects")
    data = cast(dict[str, Any], raw)
    handle_id = data.get("id")
    session_key = data.get("session_key")
    raw_workspace = data.get("workspace")
    raw_name = data.get("name")
    if (
        not isinstance(handle_id, str)
        or _HANDLE_ID_RE.fullmatch(handle_id) is None
        or not isinstance(session_key, str)
        or not isinstance(raw_workspace, str)
        or not isinstance(raw_name, str)
    ):
        raise SessionHandleDirectoryError("invalid session handle record")
    try:
        clean_key = _clean_session_key(session_key)
        workspace = _canonical_workspace(Path(raw_workspace))
        name = normalize_session_handle(raw_name)
    except ValueError as exc:
        raise SessionHandleDirectoryError("invalid session handle record") from exc
    if clean_key != session_key or str(workspace) != raw_workspace or name != raw_name:
        raise SessionHandleDirectoryError("session handle record is not canonical")
    return _StoredHandle(
        id=handle_id,
        session_key=clean_key,
        workspace=str(workspace),
        name=name,
    )


def _validate_unique_records(
    records: list[_StoredHandle],
    *,
    globally_unique_names: bool = True,
) -> None:
    ids: set[str] = set()
    session_keys: set[str] = set()
    scoped_names: set[tuple[str, str]] = set()
    for item in records:
        name_scope = "" if globally_unique_names else _workspace_key(item.workspace)
        scoped_name = (name_scope, item.name.casefold())
        if item.id in ids or item.session_key in session_keys or scoped_name in scoped_names:
            raise SessionHandleDirectoryError("session handle store contains duplicate records")
        ids.add(item.id)
        session_keys.add(item.session_key)
        scoped_names.add(scoped_name)


def _repair_globally_duplicate_names(
    records: list[_StoredHandle],
) -> tuple[list[_StoredHandle], bool]:
    repaired = list(records)
    seen: set[str] = set()
    changed = False
    for index, item in enumerate(repaired):
        folded = item.name.casefold()
        if folded not in seen:
            seen.add(folded)
            continue
        replacement = _StoredHandle(
            id=item.id,
            session_key=item.session_key,
            workspace=item.workspace,
            name=_allocate_name(item.id, repaired[:index] + repaired[index + 1 :]),
        )
        repaired[index] = replacement
        seen.add(replacement.name.casefold())
        changed = True
    return repaired, changed


def _workspace_from_metadata(metadata: dict[str, Any], *, default: Path) -> Path:
    raw_scope = metadata.get(WORKSPACE_SCOPE_METADATA_KEY)
    if not isinstance(raw_scope, dict):
        return default.expanduser().resolve(strict=False)
    raw_path = cast(dict[str, Any], raw_scope).get("project_path")
    if raw_path is None:
        return default.expanduser().resolve(strict=False)
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise SessionHandleDirectoryError("session workspace scope has an invalid project path")
    try:
        return _canonical_workspace(Path(raw_path))
    except ValueError as exc:
        raise SessionHandleDirectoryError("session workspace scope has an invalid project path") from exc


def _canonical_workspace(path: Path) -> Path:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        raise ValueError("workspace path must be absolute")
    return expanded.resolve(strict=False)


def _clean_session_key(value: str) -> str:
    key = value.strip()
    if not key or len(key) > _MAX_SESSION_KEY_CHARS:
        raise ValueError("session key is invalid")
    return key


def _allocate_name(
    handle_id: str,
    records: list[_StoredHandle],
    *,
    preferred: str | None = None,
) -> str:
    used = {item.name.casefold() for item in records}
    if preferred is not None and preferred.casefold() not in used:
        return normalize_session_handle(preferred)

    offset = int.from_bytes(
        hashlib.sha256(handle_id.encode("ascii")).digest()[:4],
        "big",
    ) % len(_HANDLE_NAMES)
    ordered = _HANDLE_NAMES[offset:] + _HANDLE_NAMES[:offset]
    for name in ordered:
        if name not in used:
            return name

    suffix = 2
    while suffix <= _MAX_HANDLES + 1:
        for base in ordered:
            candidate = f"{base}-{suffix}"
            if candidate not in used:
                return candidate
        suffix += 1
    raise SessionHandleDirectoryError("could not allocate a unique session handle")


def _handle(record: _StoredHandle, descriptor: _SessionDescriptor) -> SessionHandle:
    color_slot = int.from_bytes(
        hashlib.sha256(record.id.encode("ascii")).digest()[:2],
        "big",
    ) % SESSION_HANDLE_COLOR_SLOTS
    return SessionHandle(
        id=record.id,
        name=record.name,
        color_slot=color_slot,
        session_key=record.session_key,
        workspace=descriptor.workspace,
    )


def _workspace_key(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _same_workspace(left: str, right: str) -> bool:
    return _workspace_key(left) == _workspace_key(right)


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp_path, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp_path, path)
        with suppress(PermissionError):
            directory_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                try:
                    os.fsync(directory_fd)
                except OSError as exc:
                    if exc.errno != errno.EINVAL:
                        raise
            finally:
                os.close(directory_fd)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
