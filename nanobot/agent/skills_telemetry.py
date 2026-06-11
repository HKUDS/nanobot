"""Skill view/use/patch telemetry with two-layer locking and RMW merge."""

from __future__ import annotations

import json
import os
import sys
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, TypedDict

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
        except OSError:
            pass
        logger.warning(
            "telemetry: corrupt JSON at {} (kind=json_corruption): {}; backed up to {}",
            path,
            exc,
            backup,
        )
        return None


def _epoch_ms() -> float:
    import time

    return time.time() * 1000


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
