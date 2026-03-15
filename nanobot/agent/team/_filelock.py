"""Cross-platform file locking for board and mailbox."""

from __future__ import annotations

import sys

if sys.platform == "win32":
    import msvcrt

    def lock(f) -> None:
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)

    def unlock(f) -> None:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def lock(f) -> None:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)

    def unlock(f) -> None:
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
