"""Private, scoped pre-update snapshots for the standalone update worker.

Only named nanobot stores are included, never the whole home or user project.
The caller must stop writers first; checking a stable inventory detects concurrent
changes but is not a substitute for that ownership handoff. This module deliberately
does not implement automatic restore or claim to snapshot external services.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import stat
import tempfile
import time
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, cast
from zipfile import ZIP_STORED, ZipFile

from nanobot.utils.atomic_file import atomic_write_lines

_MAX_ENTRIES = 100_000
_MAX_BYTES = 10 * 1024**3


@dataclass(frozen=True)
class BackupSource:
    path: str

    @classmethod
    def parse(cls, value: object) -> BackupSource:
        if not isinstance(value, dict):
            raise ValueError("Invalid backup source")
        path = cast(dict[object, object], value).get("path")
        if not isinstance(path, str) or not Path(path).is_absolute() or len(path) > 4096 or "\0" in path:
            raise ValueError("Backup sources must be bounded absolute paths")
        return cls(path)


def unique_sources(sources: list[BackupSource]) -> tuple[BackupSource, ...]:
    return tuple(BackupSource(path) for path in sorted({source.path for source in sources}))


@dataclass(frozen=True)
class _Entry:
    path: str
    kind: Literal["file", "directory", "missing"]
    size: int
    mode: int
    mtime_ns: int
    ctime_ns: int
    device: int
    inode: int


def _entry(path: Path) -> _Entry:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return _Entry(str(path), "missing", 0, 0, 0, 0, 0, 0)
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError("A backup store contains a symlink or reparse point; review its external data before updating")
    if not stat.S_ISREG(info.st_mode) and not stat.S_ISDIR(info.st_mode):
        raise ValueError("A backup store contains a special file; stop its owner before updating")
    if path.resolve() != path:
        raise ValueError("A backup store has a redirected parent path; review its data location before updating")
    kind = "directory" if stat.S_ISDIR(info.st_mode) else "file"
    return _Entry(str(path), kind, info.st_size if kind == "file" else 0, stat.S_IMODE(info.st_mode),
                  info.st_mtime_ns, info.st_ctime_ns, info.st_dev, info.st_ino)


def _inventory(sources: tuple[BackupSource, ...]) -> list[_Entry]:
    entries: dict[str, _Entry] = {}
    pending = [Path(source.path) for source in sources]
    total = 0
    while pending:
        path = pending.pop()
        if str(path) in entries:
            continue
        item = _entry(path)
        entries[item.path] = item
        total += item.size
        if len(entries) > _MAX_ENTRIES or total > _MAX_BYTES:
            raise ValueError("The managed backup exceeds 100,000 entries or 10 GiB; use an explicit maintenance backup")
        if item.kind == "directory":
            with os.scandir(path) as children:
                for child in children:
                    pending.append(Path(child.path))
                    if len(pending) + len(entries) > _MAX_ENTRIES:
                        raise ValueError("The managed backup has too many entries; use an explicit maintenance backup")
    return sorted(entries.values(), key=lambda entry: entry.path)


def _sources_digest(sources: tuple[BackupSource, ...]) -> str:
    return hashlib.sha256(json.dumps([asdict(source) for source in sources], sort_keys=True).encode()).hexdigest()


def _inventory_digest(entries: list[_Entry]) -> str:
    return hashlib.sha256(json.dumps([asdict(entry) for entry in entries], sort_keys=True).encode()).hexdigest()


def _file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def current_file_hashes(sources: tuple[BackupSource, ...]) -> dict[str, str]:
    """Compare user contents with a backup using the same bounded path policy."""
    entries = _inventory(sources)
    result = {item.path: _file_digest(Path(item.path)) for item in entries if item.kind == "file"}
    if _inventory(sources) != entries:
        raise ValueError("User data changed during recovery verification")
    return result


def verify_backup(directory: Path, sources: tuple[BackupSource, ...], request_sha256: str, *, unchanged: bool = False) -> Path:
    """Verify the original snapshot; before first mutation, require unchanged data."""
    root = directory / "backup"
    receipt, archive = root / "receipt.json", root / "data.zip"
    if root.is_symlink() or receipt.is_symlink() or receipt.stat().st_size > 16 * 1024:
        raise ValueError("Invalid pre-update backup receipt")
    raw: object = json.loads(receipt.read_bytes())
    if not isinstance(raw, dict):
        raise ValueError("Invalid pre-update backup receipt")
    record = cast(dict[str, object], raw)
    if (record.get("schema_version") != 1 or record.get("request_sha256") != request_sha256 or
            record.get("sources_sha256") != _sources_digest(sources)):
        raise ValueError("The pre-update backup belongs to a different update or data scope")
    info = archive.lstat()
    if not stat.S_ISREG(info.st_mode) or archive.is_symlink() or info.st_size != record.get("archive_size"):
        raise ValueError("The original pre-update backup is missing or changed; do not replace it with current data")
    if _file_digest(archive) != record.get("archive_sha256"):
        raise ValueError("The original pre-update backup checksum changed; installation is blocked")
    if unchanged and _inventory_digest(_inventory(sources)) != record.get("inventory_sha256"):
        raise ValueError("Data changed after backup but before installation; prepare a new update plan and preserve this backup")
    return archive


def ensure_backup(directory: Path, sources: tuple[BackupSource, ...], request_sha256: str, *, mutated: bool) -> Path:
    """Commit one complete backup, or retain it unchanged across exact-job retries."""
    final = directory / "backup"
    if final.exists() or final.is_symlink():
        return verify_backup(directory, sources, request_sha256, unchanged=not mutated)
    if mutated:
        raise ValueError("The original pre-update backup is missing; repair cannot snapshot already changed data")
    for source in sources:
        if directory.resolve().is_relative_to(Path(source.path)):
            raise ValueError("Backup scope includes the update job itself")
    entries = _inventory(sources)
    total = sum(item.size for item in entries)
    if shutil.disk_usage(directory).free < total + 16 * 1024**2 + len(entries) * 1024:
        raise ValueError("Not enough space for the required pre-update backup; no packages were changed")
    # A crash leaves a private incomplete attempt, never a plausible completed
    # backup. A retry uses a new attempt; no original recovery material is deleted.
    staging = Path(tempfile.mkdtemp(prefix=".backup-", dir=directory))
    archive = staging / "data.zip"
    records: list[dict[str, object]] = []
    with archive.open("xb") as output:
        os.chmod(archive, 0o600)
        with ZipFile(output, "w", compression=ZIP_STORED, allowZip64=True) as bundle:
            for index, item in enumerate(entries):
                record: dict[str, object] = {**asdict(item)}
                if item.kind == "file":
                    path = Path(item.path)
                    if _entry(path) != item:
                        raise ValueError("Data changed while preparing its backup; stop writers and retry")
                    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
                             | getattr(os, "O_BINARY", 0))
                    with os.fdopen(os.open(path, flags), "rb") as source:
                        opened = os.fstat(source.fileno())
                        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (item.device, item.inode):
                            raise ValueError("A backup file was replaced while opening it")
                        name, digest, copied = f"files/{index}", hashlib.sha256(), 0
                        with bundle.open(name, "w", force_zip64=True) as target:
                            while chunk := source.read(1024 * 1024):
                                copied += len(chunk)
                                if copied > item.size:
                                    raise ValueError("Data grew during backup; stop writers and retry")
                                digest.update(chunk)
                                target.write(chunk)
                        if copied != item.size or _entry(path) != item:
                            raise ValueError("Data changed during backup; stop writers and retry")
                    record.update(member=name, sha256=digest.hexdigest())
                records.append(record)
            if _inventory(sources) != entries:
                raise ValueError("Data changed during backup; stop writers and retry")
            bundle.writestr("manifest.json", json.dumps({
                "schema_version": 1, "scope": "named nanobot stores from recorded gateway profiles",
                "excluded": ["arbitrary project files", "installed integration binaries and caches", "external services and custom stores"],
                "sources": [asdict(s) for s in sources], "entries": records,
            }, separators=(",", ":")))
        output.flush()
        os.fsync(output.fileno())
    record = {"schema_version": 1, "request_sha256": request_sha256, "sources_sha256": _sources_digest(sources),
              "inventory_sha256": _inventory_digest(entries),
              "archive_size": archive.stat().st_size, "archive_sha256": _file_digest(archive),
              "entries": len(entries), "source_bytes": total, "created_at": int(time.time())}
    atomic_write_lines(staging / "receipt.json", [json.dumps(record, sort_keys=True)])
    (staging / "receipt.json").chmod(0o600)
    os.rename(staging, final)
    # Publish the directory durably; Windows may not permit directory fsync.
    with suppress(PermissionError):
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            try:
                os.fsync(descriptor)
            except OSError as exc:
                if exc.errno != errno.EINVAL:
                    raise
        finally:
            os.close(descriptor)
    return final / "data.zip"
