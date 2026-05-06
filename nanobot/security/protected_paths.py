"""Filesystem-level defense for files only ``MemoryStore`` should write.

The shell-command guard (``nanobot.security.network.contains_internal_url``
and the ``_PROTECTED_TARGET_RE`` in ``agent/tools/shell.py``) is a heuristic:
regex on raw shell text cannot cover every expansion trick. Once a
compromised ``bash -c`` actually issues ``open(…, "w")`` on the canonical
resolved path, the kernel is the only layer left.

This module keeps the protected files at mode ``0o444`` so a write through
``bash -c "tee … / … .jsonl"`` — however cleverly the attacker split the
filename to bypass the regex — fails with ``EACCES``. ``MemoryStore`` wraps
its own writes in :func:`writable` to briefly flip the mode for a legitimate
internal update.

Residual risk: an attacker that can write in the parent directory can still
``rm`` and recreate the file. That requires a second bypass (the directory
write guard) and is left to a follow-up.
"""

from __future__ import annotations

import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from loguru import logger

PROTECTED_FILES: tuple[str, ...] = ("history.jsonl", ".dream_cursor")

_PROTECTED_MODE = 0o444
_WRITABLE_MODE = 0o644


def is_protected(path: Path | str) -> bool:
    """Return True if ``path``'s basename matches a protected file name."""
    return Path(path).name in PROTECTED_FILES


def is_hardened(path: Path) -> bool:
    """Return True if ``path`` exists and is set to the protected (read-only) mode.

    Public assertion helper: callers (tests, diagnostics) can check whether a
    file is currently in the hardened state without poking ``stat.S_IMODE`` and
    encoding the magic ``0o444`` value at every call site. Returns ``False`` if
    the path does not exist or cannot be stat'd.
    """
    try:
        return stat.S_IMODE(path.stat().st_mode) == _PROTECTED_MODE
    except OSError:
        return False


def harden(path: Path) -> None:
    """Mark ``path`` read-only at the OS level if it exists.

    Best-effort: a chmod failure (exotic filesystems, permission quirks on
    a bind-mounted volume) is logged at DEBUG and swallowed. L1 is a
    defense-in-depth layer, not an invariant — the caller keeps working
    either way.
    """
    try:
        if path.exists():
            os.chmod(path, _PROTECTED_MODE)
    except OSError as e:
        logger.debug("Could not harden {}: {}", path, e)


@contextmanager
def writable(path: Path) -> Iterator[None]:
    """Briefly allow writes to ``path`` for an internal update.

    On entry the file is flipped to ``0o644`` (if it already exists). On
    exit — whether the body raised or returned — the file is re-hardened
    back to ``0o444``. If the file does not yet exist, the body is expected
    to create it; the ``finally`` hardens the freshly-created file.
    """
    if path.exists():
        try:
            os.chmod(path, _WRITABLE_MODE)
        except OSError as e:
            logger.debug("Could not unharden {} before write: {}", path, e)
    try:
        yield
    finally:
        harden(path)
