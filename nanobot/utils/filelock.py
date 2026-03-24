"""Cross-platform file locking as a context manager."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import IO, Iterator


@contextmanager
def filelock(f: IO) -> Iterator[None]:
    """Acquire an exclusive lock on *f*, release on exit."""
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
