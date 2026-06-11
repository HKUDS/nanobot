"""Skill view/use/patch telemetry with two-layer locking and RMW merge."""

from __future__ import annotations

import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, TypedDict

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


_KIND_TO_COUNTER = {"view": "views", "use": "uses", "patch": "patches"}
_KIND_TO_LAST_TS = {"view": "last_view", "use": "last_use", "patch": None}


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
        last_ts_key = _KIND_TO_LAST_TS[kind]
        now = _now_iso()
        with self._lock:
            entry = self._entries.setdefault(name, _zero_entry_with_unknown_origin())
            entry[counter_key] = entry[counter_key] + 1  # type: ignore[literal-required]
            if last_ts_key is not None:
                entry[last_ts_key] = now  # type: ignore[literal-required]
            self._dirty = True
