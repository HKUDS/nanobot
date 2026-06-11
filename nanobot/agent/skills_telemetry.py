"""Skill view/use/patch telemetry with two-layer locking and RMW merge."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, TypedDict

import filelock
from loguru import logger

BumpKind = Literal["view", "use", "patch"]
Writer = Literal["bump", "reconcile"]


class SkillEntry(TypedDict):
    name: str
    effective_origin: Literal["user", "agent", "builtin"]
    shadowed_origins: list[str]
    path: str


class TelemetryEntrySnapshot(TypedDict):
    origin: Literal["user", "agent", "builtin", "unknown"]
    shadowed: list[str]
    views: int
    uses: int
    patches: int
    entry_created_at: str
    last_view: str | None
    last_use: str | None


class TelemetrySnapshot(TypedDict):
    schema_version: int
    updated_at: str
    entries: dict[str, TelemetryEntrySnapshot]


SCHEMA_VERSION = 1
TELEMETRY_FILENAME = ".telemetry.json"
LOCK_FILENAME = ".telemetry.json.lock"
TMP_GLOB = ".telemetry.json.tmp*"

COUNTER_KEYS: tuple[str, ...] = ("views", "uses", "patches")
FILELOCK_TIMEOUT_S = 0.2
FILELOCK_RETRIES = 3
WARN_COALESCE_EVERY = 100


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_KIND_TO_COUNTER: dict[BumpKind, Literal["views", "uses", "patches"]] = {
    "view": "views",
    "use": "uses",
    "patch": "patches",
}
_KIND_TO_LAST_TS: dict[BumpKind, Literal["last_view", "last_use"]] = {
    "view": "last_view",
    "use": "last_use",
}


def _atomic_write(path: Path, payload: dict) -> None:
    """tmp + fsync(tmp) + os.replace + fsync(parent_dir) on POSIX."""
    tmp = path.with_name(path.name + ".tmp")
    data = json.dumps(payload, indent=2, sort_keys=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, data.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    if sys.platform != "win32":
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


def _safe_read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        backup = path.with_suffix(path.suffix + f".corrupted.{int(_epoch_ms())}")
        try:
            path.rename(backup)
        except OSError as rename_exc:
            logger.warning(
                "telemetry: corrupt JSON at {} (kind=json_corruption): {}; "
                "backup rename failed ({}), original left in place",
                path,
                exc,
                rename_exc,
            )
        else:
            logger.warning(
                "telemetry: corrupt JSON at {} (kind=json_corruption): {}; backed up to {}",
                path,
                exc,
                backup,
            )
        return None


def _epoch_ms() -> float:
    return time.time() * 1000


def _max_iso(a: str | None, b: str | None) -> str | None:
    if a is None:
        return b
    if b is None:
        return a
    return a if a >= b else b


def _min_iso(a: str | None, b: str | None) -> str | None:
    if a is None:
        return b
    if b is None:
        return a
    return a if a <= b else b


def _rmw_merge(
    on_disk: dict | None,
    snapshot: dict,
    last_synced: dict,
    writer: Writer,
) -> dict:
    """Merge per spec §4.3 RMW table.

    on_disk: full telemetry doc as read from disk (None / corrupt → rebuild empty).
    snapshot: in-memory entries dict only ({name: entry}).
    last_synced: {name: {views, uses, patches}} previously flushed by this process.
    writer: "bump" or "reconcile" — controls origin/shadowed merge branch.
    """
    base = on_disk if isinstance(on_disk, dict) and "entries" in on_disk else {
        "schema_version": SCHEMA_VERSION,
        "updated_at": _now_iso(),
        "entries": {},
    }
    disk_entries: dict = dict(base.get("entries", {}))

    for name, snap_entry in snapshot.items():
        disk_entry = disk_entries.get(name)
        if disk_entry is None:
            # Branch: entry only in snapshot
            if writer == "bump" and name in last_synced:
                # We previously synced this entry; it's gone from disk →
                # reconcile killed it. Do not resurrect.
                continue
            # writer == "reconcile" OR first landing of a never-synced entry
            disk_entries[name] = dict(snap_entry)
            continue
        # Branch: entry in both
        merged_entry = dict(disk_entry)  # preserve unknown future fields
        last = last_synced.get(name, {"views": 0, "uses": 0, "patches": 0})
        for counter in COUNTER_KEYS:
            raw_delta = snap_entry.get(counter, 0) - last.get(counter, 0)
            if raw_delta < 0:
                logger.warning(
                    "telemetry: invariant violation last_synced > snapshot "
                    "(kind=telemetry_invariant_violation, name={}, counter={}, snap={}, last={})",
                    name, counter, snap_entry.get(counter, 0), last.get(counter, 0),
                )
            merged_entry[counter] = disk_entry.get(counter, 0) + max(raw_delta, 0)
        merged_entry["last_view"] = _max_iso(
            disk_entry.get("last_view"), snap_entry.get("last_view")
        )
        merged_entry["last_use"] = _max_iso(
            disk_entry.get("last_use"), snap_entry.get("last_use")
        )
        merged_entry["entry_created_at"] = _min_iso(
            disk_entry.get("entry_created_at"), snap_entry.get("entry_created_at")
        )
        if writer == "reconcile" and snap_entry.get("origin") != "unknown":
            merged_entry["origin"] = snap_entry["origin"]
            merged_entry["shadowed"] = list(snap_entry.get("shadowed", []))
        disk_entries[name] = merged_entry

    # Entries only on disk (snapshot didn't touch them) → keep as-is (already in disk_entries)
    base = dict(base)
    base["entries"] = disk_entries
    base["schema_version"] = max(int(base.get("schema_version", SCHEMA_VERSION)), SCHEMA_VERSION)
    base["updated_at"] = _now_iso()
    return base


def _zero_entry_with_unknown_origin() -> TelemetryEntrySnapshot:
    return {
        "origin": "unknown",
        "shadowed": [],
        "views": 0,
        "uses": 0,
        "patches": 0,
        "entry_created_at": _now_iso(),
        "last_view": None,
        "last_use": None,
    }


class SkillTelemetry:
    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace
        self._skills_dir = workspace / "skills"
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._skills_dir / TELEMETRY_FILENAME
        self._lock_path = self._skills_dir / LOCK_FILENAME
        self._lock = threading.Lock()
        self._flush_lock = threading.Lock()
        self._entries: dict[str, TelemetryEntrySnapshot] = {}
        self._last_synced_counts: dict[str, dict[str, int]] = {}
        self._dirty = False
        self._failure_counts: dict[str, int] = {}
        # .tmp residue cleanup happens before any reconcile
        for stale in self._skills_dir.glob(TMP_GLOB):
            try:
                stale.unlink()
            except OSError:
                pass

    def snapshot(self) -> TelemetrySnapshot:
        with self._lock:
            return {
                "schema_version": SCHEMA_VERSION,
                "updated_at": _now_iso(),
                "entries": deepcopy(self._entries),
            }

    def bump(self, name: str, kind: BumpKind) -> None:
        if kind not in _KIND_TO_COUNTER:
            raise ValueError(f"unknown bump kind: {kind!r}")
        counter_key = _KIND_TO_COUNTER[kind]
        last_ts_key = _KIND_TO_LAST_TS.get(kind)
        now = _now_iso()
        with self._lock:
            entry = self._entries.get(name)
            if entry is None:
                entry = _zero_entry_with_unknown_origin()
                self._entries[name] = entry
            entry[counter_key] = entry[counter_key] + 1
            if last_ts_key is not None:
                entry[last_ts_key] = now
            self._dirty = True

    def flush(self, writer: Writer = "bump") -> None:
        # ----- Single-flight gate -----
        if not self._flush_lock.acquire(blocking=False):
            return  # another flush already in flight → no-op
        try:
            # ----- Phase 1: snapshot under self._lock -----
            with self._lock:
                if not self._dirty:
                    return
                snapshot = deepcopy(self._entries)
                last_synced_snapshot = deepcopy(self._last_synced_counts)
            # ----- Phase 2: filelock + RMW + atomic write -----
            try:
                success = self._write_phase(snapshot, last_synced_snapshot, writer)
            except Exception:
                self._note_failure("atomic_write_io_error")
                return
            if not success:
                self._note_failure("filelock_timeout")
                return
            # ----- Phase 3: advance _last_synced_counts under self._lock -----
            with self._lock:
                for name, entry in snapshot.items():
                    slot = self._last_synced_counts.setdefault(
                        name, {"views": 0, "uses": 0, "patches": 0}
                    )
                    for k in COUNTER_KEYS:
                        slot[k] = entry[k]
                if self._entries == snapshot:
                    self._dirty = False
        finally:
            self._flush_lock.release()

    def _write_phase(self, snapshot, last_synced_snapshot, writer: Writer) -> bool:
        lock = filelock.FileLock(str(self._lock_path), timeout=FILELOCK_TIMEOUT_S)
        for _attempt in range(FILELOCK_RETRIES):
            try:
                with lock:
                    on_disk = _safe_read_json(self._path)
                    merged = _rmw_merge(on_disk, snapshot, last_synced_snapshot, writer)
                    _atomic_write(self._path, merged)
                return True
            except filelock.Timeout:
                continue
        return False

    def _note_failure(self, kind: str) -> None:
        bucket = self._failure_counts.setdefault(kind, 0) + 1
        self._failure_counts[kind] = bucket
        if bucket % WARN_COALESCE_EVERY == 0:
            logger.warning(
                "telemetry failure coalesced (kind={}, coalesced_count={})",
                kind, bucket,
            )
