"""PID-based lock to prevent duplicate gateway instances.

When the gateway starts, it writes its PID to a lock file in the data
directory.  If a lock file already exists and the recorded PID is still
alive, the new instance aborts with a clear error message instead of
silently corrupting sessions, cron jobs, or channel connections.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from loguru import logger


def _is_pid_alive(pid: int) -> bool:
    """Check whether a process with the given PID is still running."""
    try:
        if sys.platform == "win32":
            # os.kill on Windows sends TerminateProcess, so we use the
            # Win32 API to probe without side-effects.
            import ctypes

            kernel32 = ctypes.windll.kernel32
            SYNCHRONIZE = 0x00100000
            handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        else:
            os.kill(pid, 0)  # signal 0: check existence only
            return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists but we lack permission to signal it
    except Exception:
        return False


def acquire_gateway_lock() -> Path:
    """Acquire a PID lock file; abort if another gateway is already running.

    Returns the lock file path so the caller can pass it to
    ``release_gateway_lock`` during shutdown.
    """
    from nanobot.config.paths import get_data_dir

    lock_file = get_data_dir() / "gateway.pid"

    if lock_file.exists():
        try:
            old_pid = int(lock_file.read_text().strip())
            if _is_pid_alive(old_pid):
                from rich.console import Console

                console = Console()
                console.print(
                    f"[red]Error: Another gateway instance is already running "
                    f"(PID {old_pid})[/red]"
                )
                console.print(f"[dim]Lock file: {lock_file}[/dim]")
                console.print(
                    "[dim]If this is incorrect, delete the lock file and "
                    "try again.[/dim]"
                )
                raise SystemExit(1)
            else:
                logger.debug(
                    "Stale gateway lock found (PID {} no longer running), "
                    "taking over",
                    old_pid,
                )
        except (ValueError, OSError):
            pass  # corrupt lock file — safe to overwrite

    lock_file.write_text(str(os.getpid()))
    logger.debug("Gateway lock acquired: {} (PID {})", lock_file, os.getpid())
    return lock_file


def release_gateway_lock(lock_file: Path) -> None:
    """Remove the PID lock file during clean shutdown."""
    try:
        if lock_file.exists():
            # Only remove if we still own it (guard against race conditions)
            try:
                stored_pid = int(lock_file.read_text().strip())
            except (ValueError, OSError):
                stored_pid = None
            if stored_pid == os.getpid():
                lock_file.unlink()
                logger.debug("Gateway lock released: {}", lock_file)
    except Exception:
        pass  # best-effort cleanup — don't crash on shutdown
