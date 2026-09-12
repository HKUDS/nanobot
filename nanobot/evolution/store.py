"""Durable, append-only storage with private-by-default permissions."""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Iterable, cast

_RECORD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class EvolutionStore:
    """Filesystem repository for observations and immutable audit entries."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.RLock()
        self._prepare()

    @property
    def experiences_path(self) -> Path:
        return self.root / "observations" / "experiences.jsonl"

    @property
    def audit_path(self) -> Path:
        return self.root / "audit.jsonl"

    def _prepare(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        for name in (
            "observations",
            "proposals",
            "experiments",
            "evaluations",
            "accepted",
            "rejected",
            "reports",
        ):
            path = self.root / name
            path.mkdir(exist_ok=True, mode=0o700)
            os.chmod(path, 0o700)

    @staticmethod
    def _encode(value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def append_jsonl(self, path: Path, value: dict[str, Any]) -> None:
        line = self._encode(value) + "\n"
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
            try:
                os.write(fd, line.encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)

    def append_experience(self, value: dict[str, Any]) -> None:
        self.append_jsonl(self.experiences_path, value)

    def append_audit(self, value: dict[str, Any]) -> None:
        self.append_jsonl(self.audit_path, value)

    def read_jsonl(self, path: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    value = cast(object, json.loads(line))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if isinstance(value, dict):
                    rows.append(cast(dict[str, Any], value))
        return rows[-limit:] if limit is not None else rows

    def experiences(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        return self.read_jsonl(self.experiences_path, limit=limit)

    def write_record(self, area: str, record_id: str, value: dict[str, Any]) -> Path:
        if area not in {
            "proposals",
            "experiments",
            "evaluations",
            "accepted",
            "rejected",
            "reports",
        }:
            raise ValueError(f"unsupported evolution storage area: {area}")
        if not _RECORD_ID.fullmatch(record_id):
            raise ValueError("evolution record ID contains unsafe characters")
        target = self.root / area / f"{record_id}.json"
        payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        temporary = target.with_suffix(".tmp")
        with self._lock:
            fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
            try:
                os.write(fd, payload)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(temporary, target)
            os.chmod(target, 0o600)
        return target

    def records(self, area: str) -> Iterable[dict[str, Any]]:
        directory = self.root / area
        if not directory.exists():
            return ()
        result: list[dict[str, Any]] = []
        for path in sorted(directory.glob("*.json")):
            try:
                value = cast(object, json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                continue
            if isinstance(value, dict):
                result.append(cast(dict[str, Any], value))
        return result
