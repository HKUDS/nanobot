"""Platform subprocess launch and process-tree cleanup for exec sessions."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import signal
import subprocess
import sys
from contextlib import suppress
from pathlib import Path, PureWindowsPath
from typing import TYPE_CHECKING, cast

from loguru import logger

if TYPE_CHECKING:
    from nanobot.execution._windows_job import WindowsJob

_IS_WINDOWS = sys.platform == "win32"
_PROCESS_TREE_OWNER_ATTR = "_nanobot_process_tree_owner"


async def spawn_process_tree(
    command: str | list[str],
    cwd: str,
    env: dict[str, str],
    shell_program: str | None = None,
    login: bool = False,
    *,
    stdin: int = asyncio.subprocess.DEVNULL,
) -> asyncio.subprocess.Process:
    """Start a prepared command in its own process group or Windows job."""
    shell_command: str | None = None
    if isinstance(command, list):
        executable = shutil.which(command[0], path=env.get("PATH", ""))
        if executable is None:
            raise FileNotFoundError(f"Executable not found: {command[0]}")
        argv = [executable, *command[1:]]
    elif _IS_WINDOWS:
        program = shell_program or shutil.which("pwsh") or shutil.which("powershell") or "powershell"
        if PureWindowsPath(program).name.lower() in ("cmd", "cmd.exe"):
            env = {**env, "COMSPEC": program}
            shell_command = command
            argv = []
        else:
            command = _normalize_powershell_command(command)
            command = (
                "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)\n"
                "if ($PSVersionTable.PSVersion.Major -lt 6) { $OutputEncoding = [Console]::OutputEncoding }\n"
                "$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'\n"
                f"{command}\n"
                "if ($LASTEXITCODE -ne $null) { exit $LASTEXITCODE }"
            )
            argv = [program, "-NoProfile", "-NonInteractive", "-Command", command]
    else:
        program = shell_program or shutil.which("bash") or "/bin/bash"
        argv = [program]
        if login and Path(program).name.lower() in {"bash", "bash.exe", "zsh", "zsh.exe"}:
            argv.append("-l")
        argv.extend(["-c", command])

    job = _create_windows_job() if _IS_WINDOWS else None
    process = None
    try:
        if shell_command is not None:
            process = await asyncio.create_subprocess_shell(
                shell_command, stdin=stdin, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, cwd=cwd, env=env,
                creationflags=job.creation_flags if job else 0,
            )
        else:
            process = await asyncio.create_subprocess_exec(
                *argv, stdin=stdin, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, cwd=cwd, env=env,
                creationflags=job.creation_flags if job else 0,
                start_new_session=not _IS_WINDOWS,
            )
        if job is not None:
            job.assign_and_resume(process.pid)
            setattr(process, _PROCESS_TREE_OWNER_ATTR, job)
        return process
    except BaseException:
        if job is not None:
            job.terminate()
        if process is not None:
            await _kill_process(process)
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


async def _kill_process(process: asyncio.subprocess.Process) -> None:
    """Clean up the root process if launch fails before it joins its job."""
    if process.returncode is not None:
        _reap_pid(process.pid)
        return
    try:
        with suppress(ProcessLookupError):
            process.kill()
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(process.wait(), timeout=5.0)
    finally:
        _reap_pid(process.pid)


async def terminate_process_tree(process: asyncio.subprocess.Process) -> None:
    """Kill a session process and descendants, then reap the root process."""
    owner = _process_tree_owner(process)
    try:
        if owner is not None:
            owner.terminate()
        elif _IS_WINDOWS:
            if process.returncode is None:
                with suppress(OSError, asyncio.TimeoutError):
                    await asyncio.wait_for(
                        asyncio.to_thread(
                            subprocess.run,
                            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                            check=False,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        ),
                        timeout=5.0,
                    )
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
        await asyncio.wait_for(process.wait(), timeout=5.0)
        if owner is not None:
            _drop_process_tree_owner(process)
    finally:
        _reap_pid(process.pid)


def _process_tree_owner(
    process: asyncio.subprocess.Process,
) -> WindowsJob | None:
    # spawn_process_tree is the only writer for this private ownership marker.
    return cast("WindowsJob | None", vars(process).get(_PROCESS_TREE_OWNER_ATTR))


def _create_windows_job() -> WindowsJob:
    from nanobot.execution._windows_job import WindowsJob

    return WindowsJob.create()


def _drop_process_tree_owner(process: asyncio.subprocess.Process) -> None:
    with suppress(AttributeError):
        delattr(process, _PROCESS_TREE_OWNER_ATTR)


def finish_process_tree(process: asyncio.subprocess.Process) -> None:
    """Release native ownership after the session finishes draining output."""
    if (owner := _process_tree_owner(process)) is not None:
        owner.release()
        _drop_process_tree_owner(process)
    _reap_pid(process.pid)
