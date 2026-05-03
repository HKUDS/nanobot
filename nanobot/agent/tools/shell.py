"""Shell execution tool."""

import asyncio
import os
import re
import shutil
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.sandbox import wrap_command
from nanobot.agent.tools.schema import IntegerSchema, StringSchema, tool_parameters_schema
from nanobot.config.paths import get_media_dir

_IS_WINDOWS = sys.platform == "win32"


class _ExecHardTimeoutError(TimeoutError):
    """Raised when a command exceeds its configured hard timeout."""


class _ExecIdleTimeoutError(TimeoutError):
    """Raised when a command stops producing output for too long."""


@tool_parameters(
    tool_parameters_schema(
        command=StringSchema("The shell command to execute"),
        working_dir=StringSchema("Optional working directory for the command"),
        timeout=IntegerSchema(
            60,
            description=(
                "Per-call timeout in seconds. Increase for long-running commands "
                "like compilation or installation (default 60, max 600). Configure "
                "tools.exec.timeout for longer default hard timeouts; tools.exec.idleTimeout "
                "still kills commands that stop producing output."
            ),
            minimum=1,
            maximum=600,
        ),
        required=["command"],
    )
)
class ExecTool(Tool):
    """Tool to execute shell commands."""

    def __init__(
        self,
        timeout: int = 60,
        idle_timeout: int = 300,
        working_dir: str | None = None,
        deny_patterns: list[str] | None = None,
        allow_patterns: list[str] | None = None,
        restrict_to_workspace: bool = False,
        sandbox: str = "",
        path_append: str = "",
        allowed_env_keys: list[str] | None = None,
    ):
        self.timeout = timeout
        self.idle_timeout = idle_timeout
        self.working_dir = working_dir
        self.sandbox = sandbox
        self.deny_patterns = (deny_patterns or []) + [
            r"\brm\s+-[rf]{1,2}\b",          # rm -r, rm -rf, rm -fr
            r"\bdel\s+/[fq]\b",              # del /f, del /q
            r"\brmdir\s+/s\b",               # rmdir /s
            r"(?:^|[;&|]\s*)format\b",       # format (as standalone command only)
            r"\b(mkfs|diskpart)\b",          # disk operations
            r"\bdd\s+if=",                   # dd
            r">\s*/dev/sd",                  # write to disk
            r"\b(shutdown|reboot|poweroff)\b",  # system power
            r":\(\)\s*\{.*\};\s*:",          # fork bomb
            # Block writes to nanobot internal state files (#2989).
            # history.jsonl / .dream_cursor are managed by append_history();
            # direct writes corrupt the cursor format and crash /dream.
            r">>?\s*\S*(?:history\.jsonl|\.dream_cursor)",            # > / >> redirect
            r"\btee\b[^|;&<>]*(?:history\.jsonl|\.dream_cursor)",     # tee / tee -a
            r"\b(?:cp|mv)\b(?:\s+[^\s|;&<>]+)+\s+\S*(?:history\.jsonl|\.dream_cursor)",  # cp/mv target
            r"\bdd\b[^|;&<>]*\bof=\S*(?:history\.jsonl|\.dream_cursor)",  # dd of=
            r"\bsed\s+-i[^|;&<>]*(?:history\.jsonl|\.dream_cursor)",  # sed -i
        ]
        self.allow_patterns = allow_patterns or []
        self.restrict_to_workspace = restrict_to_workspace
        self.path_append = path_append
        self.allowed_env_keys = allowed_env_keys or []

    @property
    def name(self) -> str:
        return "exec"

    _MAX_TOOL_TIMEOUT = 600
    _MAX_OUTPUT = 10_000
    _STREAM_CHUNK_SIZE = 4096

    @property
    def description(self) -> str:
        return (
            "Execute a shell command and return its output. "
            "Prefer read_file/write_file/edit_file over cat/echo/sed, "
            "and grep/glob over shell find/grep. "
            "Use -y or --yes flags to avoid interactive prompts. "
            "Output is truncated at 10 000 chars; timeout defaults to 60s."
        )

    @property
    def exclusive(self) -> bool:
        return True

    async def execute(
        self, command: str, working_dir: str | None = None,
        timeout: int | None = None, **kwargs: Any,
    ) -> str:
        cwd = working_dir or self.working_dir or os.getcwd()

        # Prevent an LLM-supplied working_dir from escaping the configured
        # workspace when restrict_to_workspace is enabled (#2826). Without
        # this, a caller can pass working_dir="/etc" and then all absolute
        # paths under /etc would pass the _guard_command check that anchors
        # on cwd.
        if self.restrict_to_workspace and self.working_dir:
            try:
                requested = Path(cwd).expanduser().resolve()
                workspace_root = Path(self.working_dir).expanduser().resolve()
            except Exception:
                return "Error: working_dir could not be resolved"
            if requested != workspace_root and workspace_root not in requested.parents:
                return "Error: working_dir is outside the configured workspace"

        guard_error = self._guard_command(command, cwd)
        if guard_error:
            return guard_error

        if self.sandbox:
            if _IS_WINDOWS:
                logger.warning(
                    "Sandbox '{}' is not supported on Windows; running unsandboxed",
                    self.sandbox,
                )
            else:
                workspace = self.working_dir or cwd
                command = wrap_command(self.sandbox, command, workspace, cwd)
                cwd = str(Path(workspace).resolve())

        hard_timeout, idle_timeout = self._resolve_timeouts(timeout)
        env = self._build_env()

        if self.path_append:
            if _IS_WINDOWS:
                env["PATH"] = env.get("PATH", "") + os.pathsep + self.path_append
            else:
                env["NANOBOT_PATH_APPEND"] = self.path_append
                command = f'export PATH="$PATH{os.pathsep}$NANOBOT_PATH_APPEND"; {command}'

        try:
            process = await self._spawn(command, cwd, env)

            try:
                stdout, stderr = await self._communicate_with_timeouts(
                    process,
                    hard_timeout=hard_timeout,
                    idle_timeout=idle_timeout,
                )
            except _ExecHardTimeoutError:
                await self._kill_process(process)
                return f"Error: Command timed out after {hard_timeout} seconds"
            except _ExecIdleTimeoutError:
                await self._kill_process(process)
                return f"Error: Command produced no output for {idle_timeout} seconds"
            except asyncio.CancelledError:
                await self._kill_process(process)
                raise

            output_parts = []

            if stdout:
                output_parts.append(stdout.decode("utf-8", errors="replace"))

            if stderr:
                stderr_text = stderr.decode("utf-8", errors="replace")
                if stderr_text.strip():
                    output_parts.append(f"STDERR:\n{stderr_text}")

            output_parts.append(f"\nExit code: {process.returncode}")

            result = "\n".join(output_parts) if output_parts else "(no output)"

            max_len = self._MAX_OUTPUT
            if len(result) > max_len:
                half = max_len // 2
                result = (
                    result[:half]
                    + f"\n\n... ({len(result) - max_len:,} chars truncated) ...\n\n"
                    + result[-half:]
                )

            return result

        except Exception as e:
            return f"Error executing command: {str(e)}"

    def _resolve_timeouts(self, timeout: int | None) -> tuple[int | None, int | None]:
        """Resolve configured and per-call timeouts.

        The config-level timeout may be larger than the tool-call cap, and 0
        disables timeout entirely.  Explicit per-call timeouts remain capped by
        the tool schema/runtime guard and cannot disable the timeout.  The idle
        timeout is config-only and guards silent commands without punishing
        active long-running tasks.
        """
        if timeout is None:
            if self.timeout <= 0:
                hard_timeout = None
            else:
                hard_timeout = self.timeout
        elif timeout <= 0:
            hard_timeout = self._MAX_TOOL_TIMEOUT
        else:
            hard_timeout = min(timeout, self._MAX_TOOL_TIMEOUT)

        idle_timeout = self.idle_timeout if self.idle_timeout > 0 else None
        return hard_timeout, idle_timeout

    async def _communicate_with_timeouts(
        self,
        process: asyncio.subprocess.Process,
        *,
        hard_timeout: int | None,
        idle_timeout: int | None,
    ) -> tuple[bytes, bytes]:
        """Read process output while enforcing hard and idle deadlines."""
        stdout_stream = getattr(process, "stdout", None)
        stderr_stream = getattr(process, "stderr", None)
        if (
            not isinstance(stdout_stream, asyncio.StreamReader)
            or not isinstance(stderr_stream, asyncio.StreamReader)
        ):
            if hard_timeout is None:
                return await process.communicate()
            try:
                return await asyncio.wait_for(process.communicate(), timeout=hard_timeout)
            except asyncio.TimeoutError as exc:
                raise _ExecHardTimeoutError from exc

        loop = asyncio.get_running_loop()
        started_at = loop.time()
        last_activity = started_at
        hard_deadline = started_at + hard_timeout if hard_timeout is not None else None
        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []
        queue: asyncio.Queue[tuple[str, bytes, BaseException | None]] = asyncio.Queue()
        live_streams = {"stdout", "stderr"}

        async def _read_stream(label: str, stream: asyncio.StreamReader) -> None:
            try:
                while True:
                    data = await stream.read(self._STREAM_CHUNK_SIZE)
                    await queue.put((label, data, None))
                    if not data:
                        break
            except Exception as exc:
                await queue.put((label, b"", exc))

        readers = [
            asyncio.create_task(_read_stream("stdout", stdout_stream)),
            asyncio.create_task(_read_stream("stderr", stderr_stream)),
        ]

        try:
            while live_streams:
                now = loop.time()
                wait_timeout: float | None = None

                if hard_deadline is not None:
                    hard_remaining = hard_deadline - now
                    if hard_remaining <= 0:
                        raise _ExecHardTimeoutError
                    wait_timeout = hard_remaining

                if idle_timeout is not None:
                    idle_remaining = (last_activity + idle_timeout) - now
                    if idle_remaining <= 0:
                        raise _ExecIdleTimeoutError
                    wait_timeout = (
                        idle_remaining
                        if wait_timeout is None
                        else min(wait_timeout, idle_remaining)
                    )

                try:
                    label, data, error = await asyncio.wait_for(
                        queue.get(),
                        timeout=wait_timeout,
                    )
                except asyncio.TimeoutError as exc:
                    now = loop.time()
                    if hard_deadline is not None and now >= hard_deadline:
                        raise _ExecHardTimeoutError from exc
                    raise _ExecIdleTimeoutError from exc

                if error is not None:
                    raise RuntimeError(f"Error reading process {label}: {error}") from error

                if data:
                    last_activity = loop.time()
                    if label == "stdout":
                        stdout_chunks.append(data)
                    else:
                        stderr_chunks.append(data)
                else:
                    live_streams.discard(label)

            while process.returncode is None:
                now = loop.time()
                wait_timeout: float | None = None

                if hard_deadline is not None:
                    hard_remaining = hard_deadline - now
                    if hard_remaining <= 0:
                        raise _ExecHardTimeoutError
                    wait_timeout = hard_remaining

                if idle_timeout is not None:
                    idle_remaining = (last_activity + idle_timeout) - now
                    if idle_remaining <= 0:
                        raise _ExecIdleTimeoutError
                    wait_timeout = (
                        idle_remaining
                        if wait_timeout is None
                        else min(wait_timeout, idle_remaining)
                    )

                try:
                    await asyncio.wait_for(process.wait(), timeout=wait_timeout)
                except asyncio.TimeoutError as exc:
                    now = loop.time()
                    if hard_deadline is not None and now >= hard_deadline:
                        raise _ExecHardTimeoutError from exc
                    raise _ExecIdleTimeoutError from exc

            return b"".join(stdout_chunks), b"".join(stderr_chunks)
        finally:
            for reader in readers:
                if not reader.done():
                    reader.cancel()
            await asyncio.gather(*readers, return_exceptions=True)

    def _resolve_timeout(self, timeout: int | None) -> int | None:
        """Backward-compatible hard timeout resolver."""
        hard_timeout, _ = self._resolve_timeouts(timeout)
        return hard_timeout

    @staticmethod
    async def _spawn(
        command: str, cwd: str, env: dict[str, str],
    ) -> asyncio.subprocess.Process:
        """Launch *command* in a platform-appropriate shell."""
        if _IS_WINDOWS:
            comspec = env.get("COMSPEC", os.environ.get("COMSPEC", "cmd.exe"))
            return await asyncio.create_subprocess_exec(
                comspec, "/c", command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )
        bash = shutil.which("bash") or "/bin/bash"
        return await asyncio.create_subprocess_exec(
            bash, "-l", "-c", command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )

    @staticmethod
    async def _kill_process(process: asyncio.subprocess.Process) -> None:
        """Kill a subprocess and reap it to prevent zombies."""
        process.kill()
        try:
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=5.0)
        finally:
            if not _IS_WINDOWS:
                try:
                    os.waitpid(process.pid, os.WNOHANG)
                except (ProcessLookupError, ChildProcessError) as e:
                    logger.debug("Process already reaped or not found: {}", e)

    def _build_env(self) -> dict[str, str]:
        """Build a minimal environment for subprocess execution.

        On Unix, only HOME/LANG/TERM are passed; ``bash -l`` sources the
        user's profile which sets PATH and other essentials.

        On Windows, ``cmd.exe`` has no login-profile mechanism, so a curated
        set of system variables (including PATH) is forwarded.  API keys and
        other secrets are still excluded.
        """
        if _IS_WINDOWS:
            sr = os.environ.get("SYSTEMROOT", r"C:\Windows")
            env = {
                "SYSTEMROOT": sr,
                "COMSPEC": os.environ.get("COMSPEC", f"{sr}\\system32\\cmd.exe"),
                "USERPROFILE": os.environ.get("USERPROFILE", ""),
                "HOMEDRIVE": os.environ.get("HOMEDRIVE", "C:"),
                "HOMEPATH": os.environ.get("HOMEPATH", "\\"),
                "TEMP": os.environ.get("TEMP", f"{sr}\\Temp"),
                "TMP": os.environ.get("TMP", f"{sr}\\Temp"),
                "PATHEXT": os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD"),
                "PATH": os.environ.get("PATH", f"{sr}\\system32;{sr}"),
                "APPDATA": os.environ.get("APPDATA", ""),
                "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", ""),
                "ProgramData": os.environ.get("ProgramData", ""),
                "ProgramFiles": os.environ.get("ProgramFiles", ""),
                "ProgramFiles(x86)": os.environ.get("ProgramFiles(x86)", ""),
                "ProgramW6432": os.environ.get("ProgramW6432", ""),
            }
            for key in self.allowed_env_keys:
                val = os.environ.get(key)
                if val is not None:
                    env[key] = val
            return env
        home = os.environ.get("HOME", "/tmp")
        env = {
            "HOME": home,
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "TERM": os.environ.get("TERM", "dumb"),
        }
        for key in self.allowed_env_keys:
            val = os.environ.get(key)
            if val is not None:
                env[key] = val
        return env

    def _guard_command(self, command: str, cwd: str) -> str | None:
        """Best-effort safety guard for potentially destructive commands."""
        cmd = command.strip()
        lower = cmd.lower()

        # allow_patterns take priority over deny_patterns so that users can
        # exempt specific commands (e.g. "rm -rf" inside a build directory)
        # from the hardcoded deny list via configuration.
        explicitly_allowed = bool(self.allow_patterns) and any(
            re.search(p, lower) for p in self.allow_patterns
        )
        if not explicitly_allowed:
            for pattern in self.deny_patterns:
                if re.search(pattern, lower):
                    return "Error: Command blocked by deny pattern filter"

            if self.allow_patterns:
                return "Error: Command blocked by allowlist filter (not in allowlist)"

        from nanobot.security.network import contains_internal_url
        if contains_internal_url(cmd):
            return "Error: Command blocked by safety guard (internal/private URL detected)"

        if self.restrict_to_workspace:
            if "..\\" in cmd or "../" in cmd:
                return "Error: Command blocked by safety guard (path traversal detected)"

            cwd_path = Path(cwd).resolve()

            for raw in self._extract_absolute_paths(cmd):
                try:
                    expanded = os.path.expandvars(raw.strip())
                    p = Path(expanded).expanduser().resolve()
                except Exception:
                    continue

                media_path = get_media_dir().resolve()
                if (p.is_absolute()
                    and cwd_path not in p.parents
                    and p != cwd_path
                    and media_path not in p.parents
                    and p != media_path
                ):
                    return "Error: Command blocked by safety guard (path outside working dir)"

        return None

    @staticmethod
    def _extract_absolute_paths(command: str) -> list[str]:
        # Windows: match drive-root paths like `C:\` as well as `C:\path\to\file`
        # NOTE: `*` is required so `C:\` (nothing after the slash) is still extracted.
        win_paths = re.findall(r"[A-Za-z]:\\[^\s\"'|><;]*", command)
        posix_paths = re.findall(r"(?:^|[\s|>'\"])(/[^\s\"'>;|<]+)", command) # POSIX: /absolute only
        home_paths = re.findall(r"(?:^|[\s|>'\"])(~[^\s\"'>;|<]*)", command) # POSIX/Windows home shortcut: ~
        return win_paths + posix_paths + home_paths
