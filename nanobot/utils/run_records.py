"""Durable JSON run records for automation executions."""

from __future__ import annotations

import errno
import json
import os
import time
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any


def safe_run_record_name(run_id: str) -> str:
    """Return a filesystem-safe filename stem for a run ID."""
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in run_id)


def write_run_record(runs_dir: Path, run_id: str, record: dict[str, Any]) -> Path:
    """Write or replace one durable automation run audit record."""
    name = safe_run_record_name(run_id) or str(uuid.uuid4())
    path = runs_dir / f"{name}.json"
    payload = {
        **record,
        "run_id": run_id,
        "updated_at_ms": _now_ms(),
    }
    _atomic_write(path, json.dumps(payload, indent=2, ensure_ascii=False))
    return path


def _now_ms() -> int:
    return int(time.time() * 1000)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        with suppress(PermissionError):
            fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                try:
                    os.fsync(fd)
                except OSError as exc:
                    if exc.errno != errno.EINVAL:
                        raise
            finally:
                os.close(fd)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
