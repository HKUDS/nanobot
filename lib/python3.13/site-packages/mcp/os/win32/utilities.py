"""
Windows-specific functionality for stdio client operations.
"""

import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import BinaryIO, TextIO, cast

import anyio
from anyio import to_thread
from anyio.abc import Process
from anyio.streams.file import FileReadStream, FileWriteStream
from typing_extensions import deprecated

logger = logging.getLogger("client.stdio.win32")

# Windows-specific imports for Job Objects
if sys.platform == "win32":
    import pywintypes
    import win32api
    import win32con
    import win32job
else:
    # Type stubs for non-Windows platforms
    win32api = None
    win32con = None
    win32job = None
    pywintypes = None

JobHandle = int


def get_windows_executable_command(command: str) -> str:
    """
    Get the correct executable command normalized for Windows.

    On Windows, commands might exist with specific extensions (.exe, .cmd, etc.)
    that need to be located for proper execution.

    Args:
        command: Base command (e.g., 'uvx', 'npx')

    Returns:
        str: Windows-appropriate command path
    """
    try:
        # First check if command exists in PATH as-is
        if command_path := shutil.which(command):
            return command_path

        # Check for Windows-specific extensions
        for ext in [".cmd", ".bat", ".exe", ".ps1"]:
            ext_version = f"{command}{ext}"
            if ext_path := shutil.which(ext_version):
                return ext_path

        # For regular commands or if we couldn't find special versions
        return command
    except OSError:
        # Handle file system errors during path resolution
        # (permissions, broken symlinks, etc.)
        return command


class FallbackProcess:
    """
    A fallback process wrapper for Windows to handle async I/O
    when using subprocess.Popen, which provides sync-only FileIO objects.

    This wraps stdin and stdout into async-compatible
    streams (FileReadStream, FileWriteStream),
    so that MCP clients expecting async streams can work properly.
    """

    def __init__(self, popen_obj: subprocess.Popen[bytes]):
        self.popen: subprocess.Popen[bytes] = popen_obj
        self.stdin_raw = popen_obj.stdin  # type: ignore[assignment]
        self.stdout_raw = popen_obj.stdout  # type: ignore[assignment]
        self.stderr = popen_obj.stderr  # type: ignore[assignment]

        self.stdin = FileWriteStream(cast(BinaryIO, self.stdin_raw)) if self.stdin_raw else None
        self.stdout = FileReadStream(cast(BinaryIO, self.stdout_raw)) if self.stdout_raw else None

    async def __aenter__(self):
        """Support async context manager entry."""
        return self

    async def __aexit__(
        self,
        exc_type: BaseException | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        """Terminate and wait on process exit inside a thread."""
        self.popen.terminate()
        await to_thread.run_sync(self.popen.wait)

        # Close the file handles to prevent ResourceWarning
        if self.stdin:
            await self.stdin.aclose()
        if self.stdout:
            await self.stdout.aclose()
        if self.stdin_raw:
            self.stdin_raw.close()
        if self.stdout_raw:
            self.stdout_raw.close()
        if self.stderr:
            self.stderr.close()

    async def wait(self):
        """Async wait for process completion."""
        return await to_thread.run_sync(self.popen.wait)

    def terminate(self):
        """Terminate the subprocess immediately."""
        return self.popen.terminate()

    def kill(self) -> None:
        """Kill the subprocess immediately (alias for terminate)."""
        self.terminate()

    @property
    def pid(self) -> int:
        """Return the process ID."""
        return self.popen.pid


# ------------------------
# Updated function
# ------------------------


async def create_windows_process(
    command: str,
    args: list[str],
    env: dict[str, str] | None = None,
    errlog: TextIO | None = sys.stderr,
    cwd: Path | str | None = None,
) -> Process | FallbackProcess:
    """
    Creates a subprocess in a Windows-compatible way with Job Object support.

    Attempt to use anyio's open_process for async subprocess creation.
    In some cases this will throw NotImplementedError on Windows, e.g.
    when using the SelectorEventLoop which does not support async subprocesses.
    In that case, we fall back to using subprocess.Popen.

    The process is automatically added to a Job Object to ensure all child
    processes are terminated when the parent is terminated.

    Args:
        command (str): The executable to run
        args (list[str]): List of command line arguments
        env (dict[str, str] | None): Environment variables
        errlog (TextIO | None): Where to send stderr output (defaults to sys.stderr)
        cwd (Path | str | None): Working directory for the subprocess

    Returns:
        Process | FallbackProcess: Async-compatible subprocess with stdin and stdout streams
    """
    job = _create_job_object()
    process = None

    try:
        # First try using anyio with Windows-specific flags to hide console window
        process = await anyio.open_process(
            [command, *args],
            env=env,
            # Ensure we don't create console windows for each process
            creationflags=subprocess.CREATE_NO_WINDOW  # type: ignore
            if hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0,
            stderr=errlog,
            cwd=cwd,
        )
    except NotImplementedError:
        # If Windows doesn't support async subprocess creation, use fallback
        process = await _create_windows_fallback_process(command, args, env, errlog, cwd)
    except Exception:
        # Try again without creation flags
        process = await anyio.open_process(
            [command, *args],
            env=env,
            stderr=errlog,
            cwd=cwd,
        )

    _maybe_assign_process_to_job(process, job)
    return process


async def _create_windows_fallback_process(
    command: str,
    args: list[str],
    env: dict[str, str] | None = None,
    errlog: TextIO | None = sys.stderr,
    cwd: Path | str | None = None,
) -> FallbackProcess:
    """
    Create a subprocess using subprocess.Popen as a fallback when anyio fails.

    This function wraps the sync subprocess.Popen in an async-compatible interface.
    """
    try:
        # Try launching with creationflags to avoid opening a new console window
        popen_obj = subprocess.Popen(
            [command, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=errlog,
            env=env,
            cwd=cwd,
            bufsize=0,  # Unbuffered output
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        # If creationflags failed, fallback without them
        popen_obj = subprocess.Popen(
            [command, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=errlog,
            env=env,
            cwd=cwd,
            bufsize=0,
        )
    return FallbackProcess(popen_obj)


def _create_job_object() -> int | None:
    """
    Create a Windows Job Object configured to terminate all processes when closed.
    """
    if sys.platform != "win32" or not win32job:
        return None

    try:
        job = win32job.CreateJobObject(None, "")
        extended_info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)

        extended_info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, extended_info)
        return job
    except Exception as e:
        logger.warning(f"Failed to create Job Object for process tree management: {e}")
        return None


def _maybe_assign_process_to_job(process: Process | FallbackProcess, job: JobHandle | None) -> None:
    """
    Try to assign a process to a job object. If assignment fails
    for any reason, the job handle is closed.
    """
    if not job:
        return

    if sys.platform != "win32" or not win32api or not win32con or not win32job:
        return

    try:
        process_handle = win32api.OpenProcess(
            win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, process.pid
        )
        if not process_handle:
            raise Exception("Failed to open process handle")

        try:
            win32job.AssignProcessToJobObject(job, process_handle)
            process._job_object = job
        finally:
            win32api.CloseHandle(process_handle)
    except Exception as e:
        logger.warning(f"Failed to assign process {process.pid} to Job Object: {e}")
        if win32api:
            win32api.CloseHandle(job)


async def terminate_windows_process_tree(process: Process | FallbackProcess, timeout_seconds: float = 2.0) -> None:
    """
    Terminate a process and all its children on Windows.

    If the process has an associated job object, it will be terminated.
    Otherwise, falls back to basic process termination.

    Args:
        process: The process to terminate
        timeout_seconds: Timeout in seconds before force killing (default: 2.0)
    """
    if sys.platform != "win32":
        return

    job = getattr(process, "_job_object", None)
    if job and win32job:
        try:
            win32job.TerminateJobObject(job, 1)
        except Exception:
            # Job might already be terminated
            pass
        finally:
            if win32api:
                try:
                    win32api.CloseHandle(job)
                except Exception:
                    pass

    # Always try to terminate the process itself as well
    try:
        process.terminate()
    except Exception:
        pass


@deprecated(
    "terminate_windows_process is deprecated and will be removed in a future version. "
    "Process termination is now handled internally by the stdio_client context manager."
)
async def terminate_windows_process(process: Process | FallbackProcess):
    """
    Terminate a Windows process.

    Note: On Windows, terminating a process with process.terminate() doesn't
    always guarantee immediate process termination.
    So we give it 2s to exit, or we call process.kill()
    which sends a SIGKILL equivalent signal.

    Args:
        process: The process to terminate
    """
    try:
        process.terminate()
        with anyio.fail_after(2.0):
            await process.wait()
    except TimeoutError:
        # Force kill if it doesn't terminate
        process.kill()
