"""Coordinate nanobot entrypoints with updates of their shared Python installation.

This module uses only the standard library so startup and a detached update worker
can use the same lock without importing dependencies they are about to replace.
The OS releases leases on process exit, including a crash. Never unlink the lock
file: replacing its inode would let two processes acquire different locks.
"""

from __future__ import annotations

import errno
import hashlib
import os
import sys
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from nanobot.utils.atomic_file import io_path


class InstallationBusyError(RuntimeError):
    """Another runtime or updater holds an incompatible installation lease."""


@dataclass(frozen=True)
class FileLease:
    """An OS lease owned by the enclosing file_access context."""

    _handle: BinaryIO = field(repr=False)

    @contextmanager
    def inherit_for_exec(self) -> Generator[None]:
        """Keep a dedicated POSIX worker's lease when exec replaces its program.

        Enter only immediately around exec, not a spawned child or normal runtime
        work. The new program must retain the descriptors and must not delegate
        mutation to unprotected children. Windows byte-range locks do not provide
        this ownership transfer. A failed exec restores the original FD flags.
        """
        if os.name != "posix":
            raise OSError("Lease inheritance requires a POSIX exec handoff")
        descriptor = self._handle.fileno()
        original = os.get_inheritable(descriptor)
        os.set_inheritable(descriptor, True)
        try:
            yield
        finally:
            os.set_inheritable(descriptor, original)


def installation_id(environment: str | Path | None = None) -> str:
    return hashlib.sha256(os.fsencode(Path(environment or sys.prefix).resolve())).hexdigest()[:32]


def installation_state_dir(environment: str | Path | None = None) -> Path:
    # Deliberately independent of --home/config/workspace: profiles sharing this
    # interpreter must not get independent update locks.
    return Path.home() / ".nanobot" / "updates" / installation_id(environment)


def pending_update_path(environment: str | Path | None = None) -> Path:
    return Path.home() / ".nanobot" / "run" / f"update-{installation_id(environment)[:16]}.pending"


def _lock_windows(handle: BinaryIO, *, exclusive: bool) -> None:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class Overlapped(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
            ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    lock = kernel.LockFileEx
    lock.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                     wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(Overlapped)]
    lock.restype = wintypes.BOOL
    overlap = Overlapped()
    # LOCKFILE_FAIL_IMMEDIATELY, plus LOCKFILE_EXCLUSIVE_LOCK for an updater.
    if not lock(msvcrt.get_osfhandle(handle.fileno()), 1 | (2 if exclusive else 0),
                0, 1, 0, ctypes.byref(overlap)):
        code = ctypes.get_last_error()
        if code in {32, 33}:  # sharing/lock violation
            raise BlockingIOError(errno.EAGAIN, "Installation is in use")
        raise ctypes.WinError(code)


@contextmanager
def file_access(path: Path, *, exclusive: bool) -> Generator[FileLease]:
    """Hold a nonblocking OS lease; never replace or delete its file."""
    path = io_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "a+b") as handle:
        try:
            if sys.platform == "win32":
                _lock_windows(handle, exclusive=exclusive)
            else:
                import fcntl

                fcntl.flock(handle, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EAGAIN, errno.EACCES}:
                raise BlockingIOError(errno.EAGAIN, "The file lease is held") from exc
            raise
        yield FileLease(handle)


@contextmanager
def installation_access(*, updating: bool = False, allow_incomplete: bool = False,
                        environment: str | Path | None = None) -> Generator[FileLease]:
    """Hold a shared runtime lease, or refuse an update until all runtimes exit.

    This protects cooperating entrypoints in this account, not arbitrary Python
    imports or externally managed deployments. Process-owner shutdown/restart is
    still required before enabling an in-app installation handoff. Diagnostics and
    stop commands may allow an incomplete install; they still cannot race a writer.
    """
    acquired = False
    try:
        with file_access(installation_state_dir(environment) / "runtime.lock", exclusive=updating) as lease:
            acquired = True
            if not updating and not allow_incomplete and io_path(pending_update_path(environment)).exists():
                raise InstallationBusyError(
                    "A previous update did not finish. Check its saved update state at "
                    f"{installation_state_dir(environment)} before repairing this installation. "
                    "Do not start a different update. No automatic rollback was performed."
                )
            yield lease
    except BlockingIOError as exc:
        if not acquired:
            message = (
                "This installation is in use. Stop its nanobot gateways and clients before updating; "
                "no processes were stopped and no package files were changed."
                if updating else
                "This installation is being updated. Wait for the update to finish before starting nanobot."
            )
            raise InstallationBusyError(message) from exc
        raise
