"""Platform subprocess launch and process-tree cleanup for exec sessions."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import signal
import sys
from contextlib import suppress
from pathlib import Path, PureWindowsPath
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.execution._windows_job import WindowsJob

_IS_WINDOWS = sys.platform == "win32"


class ProcessTree:
    """Keep the root's streams and its native process-tree ownership together."""

    __slots__ = ("process", "_job")

    def __init__(self, process: asyncio.subprocess.Process, job: WindowsJob | None = None) -> None:
        self.process = process
        self._job = job

    async def terminate(self) -> None:
        """Stop descendants even if the root has already exited."""
        try:
            if self._job is not None:
                self._job.terminate()
            else:
                with suppress(ProcessLookupError):
                    os.killpg(self.process.pid, signal.SIGKILL)
            await _stop_root(self.process)
        finally:
            _reap_pid(self.process.pid)

    def finish(self) -> None:
        """Release native ownership once the session has drained the streams."""
        if self._job is not None:
            self._job.release()
        _reap_pid(self.process.pid)


async def spawn_process_tree(
    command: str | list[str],
    cwd: str,
    env: dict[str, str],
    shell_program: str | None = None,
    login: bool = False,
    *,
    stdin: int = asyncio.subprocess.DEVNULL,
) -> ProcessTree:
    """Start a prepared command in its own process group or Windows job."""
    if isinstance(command, list):
        executable = shutil.which(command[0], path=env.get("PATH", ""))
        if executable is None:
            raise FileNotFoundError(f"Executable not found: {command[0]}")
        launch = [executable, *command[1:]]
    elif _IS_WINDOWS:
        program = shell_program or shutil.which("pwsh") or shutil.which("powershell") or "powershell"
        if PureWindowsPath(program).name.lower() in ("cmd", "cmd.exe"):
            env = {**env, "COMSPEC": program}
            launch = command
        else:
            command = _normalize_powershell_command(command)
            command = (
                "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)\n"
                "if ($PSVersionTable.PSVersion.Major -lt 6) { $OutputEncoding = [Console]::OutputEncoding }\n"
                "$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'\n"
                f"{command}\n"
                "if ($LASTEXITCODE -ne $null) { exit $LASTEXITCODE }"
            )
            launch = [program, "-NoProfile", "-NonInteractive", "-Command", command]
    else:
        program = shell_program or shutil.which("bash") or "/bin/bash"
        launch = [program]
        if login and Path(program).name.lower() in {"bash", "bash.exe", "zsh", "zsh.exe"}:
            launch.append("-l")
        launch.extend(["-c", command])

    job = _create_windows_job() if _IS_WINDOWS else None
    creationflags = job.creation_flags if job is not None else 0
    process = None
    try:
        if isinstance(launch, str):
            process = await asyncio.create_subprocess_shell(
                launch, stdin=stdin, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, cwd=cwd, env=env,
                creationflags=creationflags,
            )
        else:
            process = await asyncio.create_subprocess_exec(
                *launch, stdin=stdin, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, cwd=cwd, env=env,
                creationflags=creationflags,
                start_new_session=not _IS_WINDOWS,
            )
        if job is not None:
            job.assign_and_resume(process.pid)
        return ProcessTree(process, job)
    except BaseException:
        if job is not None:
            job.terminate()
        if process is not None:
            try:
                with suppress(asyncio.TimeoutError):
                    await _stop_root(process)
            finally:
                _reap_pid(process.pid)
        raise


def _normalize_powershell_command(command: str) -> str:
    stripped = command.lstrip()
    if not stripped or stripped[0] not in {"'", '"'}:
        return command

    quote = stripped[0]
    end = stripped.find(quote, 1)
    if end == -1 or (end + 1 < len(stripped) and not stripped[end + 1].isspace()):
        return command

    executable = stripped[1:end]
    looks_like_windows_executable = (
        bool(re.match(r"^[A-Za-z]:[\\/]", executable))
        or executable.startswith(r"\\")
        or executable.lower().endswith((".exe", ".cmd", ".bat", ".ps1"))
    )
    if not looks_like_windows_executable:
        return command

    leading = command[: len(command) - len(stripped)]
    return f"{leading}& {stripped}"


def _reap_pid(pid: int) -> None:
    """Best-effort ``waitpid`` to reap a child and prevent zombies.

    Call this after killing or after normal completion of any subprocess
    as a safety net if asyncio has not reaped it.
    """
    waitpid = getattr(os, "waitpid", None)
    wnohang = getattr(os, "WNOHANG", None)
    if waitpid is None or wnohang is None:
        return
    try:
        waitpid(pid, wnohang)
    except (ProcessLookupError, ChildProcessError):
        # Already reaped, or not our child — both are fine.
        pass
    except OSError as exc:
        logger.debug("_reap_pid({}): {}", pid, exc)


async def _stop_root(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        with suppress(ProcessLookupError):
            process.kill()
    await asyncio.wait_for(process.wait(), timeout=5.0)


def _create_windows_job() -> WindowsJob:
    from nanobot.execution._windows_job import WindowsJob

    return WindowsJob.create()
