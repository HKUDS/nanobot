"""Per-file async locks + atomic writes for session file tools.

Shared by ``filesystem`` (write_file/edit_file) and ``apply_patch`` so
concurrent sessions serializing on the same resolved absolute path cannot
interleave bytes or silently lose updates. Locking fixes lost updates;
tmp+fsync+os.replace fixes torn files — both are needed.
"""

from __future__ import annotations

import os
import stat as stat_module
import uuid
from contextlib import suppress
from pathlib import Path

from filelock import AsyncFileLock
from filelock import Timeout as FileLockTimeout

__all__ = [
    "FILE_WRITE_LOCK_TIMEOUT_S",
    "FileLockTimeout",
    "_write_bytes_atomic",
    "_write_lock_for",
    "_write_text_atomic",
]

FILE_WRITE_LOCK_TIMEOUT_S = 30


def _write_lock_for(path: Path) -> AsyncFileLock:
    """Return a per-file async lock keyed on the resolved absolute path."""
    return AsyncFileLock(str(path) + ".lock", timeout=FILE_WRITE_LOCK_TIMEOUT_S)


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    """Write bytes via tmp file + fsync + os.replace (mirrors _write_text_atomic)."""
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    existing_mode: int | None = None
    with suppress(OSError):
        existing_mode = stat_module.S_IMODE(path.stat().st_mode)
    try:
        with open(tmp, "wb") as f:
            if existing_mode is not None:
                os.chmod(tmp, existing_mode)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        with suppress(OSError, NotImplementedError):
            dfd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _write_text_atomic(path: Path, content: str) -> None:
    _write_bytes_atomic(path, content.encode("utf-8"))
