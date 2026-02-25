"""
POSIX-specific functionality for stdio client operations.
"""

import logging
import os
import signal

import anyio
from anyio.abc import Process

logger = logging.getLogger(__name__)


async def terminate_posix_process_tree(process: Process, timeout_seconds: float = 2.0) -> None:
    """
    Terminate a process and all its children on POSIX systems.

    Uses os.killpg() for atomic process group termination.

    Args:
        process: The process to terminate
        timeout_seconds: Timeout in seconds before force killing (default: 2.0)
    """
    pid = getattr(process, "pid", None) or getattr(getattr(process, "popen", None), "pid", None)
    if not pid:
        # No PID means there's no process to terminate - it either never started,
        # already exited, or we have an invalid process object
        return

    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGTERM)

        with anyio.move_on_after(timeout_seconds):
            while True:
                try:
                    # Check if process group still exists (signal 0 = check only)
                    os.killpg(pgid, 0)
                    await anyio.sleep(0.1)
                except ProcessLookupError:
                    return

        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    except (ProcessLookupError, PermissionError, OSError) as e:
        logger.warning(f"Process group termination failed for PID {pid}: {e}, falling back to simple terminate")
        try:
            process.terminate()
            with anyio.fail_after(timeout_seconds):
                await process.wait()
        except Exception:
            logger.warning(f"Process termination failed for PID {pid}, attempting force kill")
            try:
                process.kill()
            except Exception:
                logger.exception(f"Failed to kill process {pid}")
