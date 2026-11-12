"""Filesystem primitives shared by configuration and runtime storage."""

import os
import stat
import uuid
from contextlib import suppress
from pathlib import Path


def ensure_dir(path: Path) -> Path:
    """Ensure directory exists, return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_text_atomic(path: Path, content: str) -> None:
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    existing_mode: int | None = None
    with suppress(OSError):
        existing_mode = stat.S_IMODE(path.stat().st_mode)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            if existing_mode is not None:
                os.chmod(tmp, existing_mode)
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)
        with suppress(OSError, NotImplementedError):
            dfd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
