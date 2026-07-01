"""Shell execution tool."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import Field

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.context import current_request_session_key
from nanobot.agent.tools.exec_session import (
    DEFAULT_EXEC_SESSION_MANAGER,
    DEFAULT_MAX_OUTPUT_CHARS,
    DEFAULT_YIELD_MS,
    MAX_OUTPUT_CHARS,
    MAX_YIELD_MS,
    clamp_session_int,
    format_session_poll,
)
from nanobot.agent.tools.sandbox import wrap_command
from nanobot.agent.tools.schema import (
    BooleanSchema,
    IntegerSchema,
    StringSchema,
    tool_parameters_schema,
)
from nanobot.config.paths import get_media_dir
from nanobot.config_base import Base
from nanobot.security.workspace_access import current_scope_allows_loopback, current_tool_workspace
from nanobot.security.workspace_policy import is_path_within

_IS_WINDOWS = sys.platform == "win32"


# Policy note appended to recoverable workspace-boundary guard errors.
_WORKSPACE_BOUNDARY_NOTE = (
    "\n\nNote: this is a hard policy boundary, not a transient failure. "
    "Do NOT retry with shell tricks (symlinks, base64 piping, alternative "
    "tools, working_dir overrides). If the user genuinely needs this "
    "resource, tell them you cannot reach it under the current "
    "restrict_to_workspace policy and ask how to proceed."
)


class ExecToolConfig(Base):
    """Shell exec tool configuration."""
    enable: bool = True
    timeout: int = Field(default=60, ge=0)  # Hard timeout (s); 0 = no limit. Not capped by the per-call max.
    path_prepend: str = ""
    path_append: str = ""
    sandbox: str = ""
    allowed_env_keys: list[str] = Field(default_factory=list)
    allow_patterns: list[str] = Field(default_factory=list)
    deny_patterns: list[str] = Field(default_factory=list)


@dataclass(slots=True)
class _PreparedCommand:
    command: str
    cwd: str
    env: dict[str, str]
    timeout: int | None
    shell_program: str | None
    login: bool


@tool_parameters(
    tool_parameters_schema(
        command=StringSchema("The shell command to execute"),
        cmd=StringSchema("Compatibility alias for command"),
        working_dir=StringSchema("Optional working directory for the command"),
        workdir=StringSchema("Compatibility alias for working_dir"),
        timeout=IntegerSchema(
            60,
            description=(
                "Timeout in seconds. Increase for long-running commands "
                "like compilation or installation (default 60, max 600)."
            ),
            minimum=1,
            maximum=600,
        ),
        shell=StringSchema(
            "Optional shell binary to launch. On Unix, supports sh, bash, or zsh.",
            nullable=True,
        ),
        login=BooleanSchema(
            description="Whether to run bash/zsh with login shell semantics (default false).",
            default=False,
            nullable=True,
        ),
        yield_time_ms=IntegerSchema(
            description=(
                "Optional milliseconds to wait before returning output. "
                "When set, a still-running command returns a session_id that "
                "can be polled or written to with write_stdin. Omit this field "
                "to keep one-shot exec behavior."
            ),
            minimum=0,
            maximum=MAX_YIELD_MS,
            nullable=True,
        ),
        max_output_chars=IntegerSchema(
            description=(
                "Maximum output characters to return when yield_time_ms is used "
                "(default 10000, max 50000)."
            ),
            minimum=1000,
            maximum=MAX_OUTPUT_CHARS,
            nullable=True,
        ),
        max_output_tokens=IntegerSchema(
            description=(
                "Compatibility alias for max_output_chars. The current runtime "
                "uses a character budget."
            ),
            minimum=1000,
            maximum=MAX_OUTPUT_CHARS,
            nullable=True,
        ),
    )
)
class ExecTool(Tool):
    """Tool to execute shell commands."""
    _scopes = {"core", "subagent"}

    config_key = "exec"

    @classmethod
    def config_cls(cls):
        return ExecToolConfig

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return ctx.config.exec.enable

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        cfg = ctx.config.exec
        return cls(
            working_dir=ctx.workspace,
            timeout=cfg.timeout,
            restrict_to_workspace=ctx.config.restrict_to_workspace,
            webui_allow_local_service_access=ctx.config.webui_allow_local_service_access,
            sandbox=cfg.sandbox,
            path_prepend=cfg.path_prepend,
            path_append=cfg.path_append,
            allowed_env_keys=cfg.allowed_env_keys,
            allow_patterns=cfg.allow_patterns,
            deny_patterns=cfg.deny_patterns,
        )

    def __init__(
        self,
        timeout: int = 60,
        working_dir: str | None = None,
        deny_patterns: list[str] | None = None,
        allow_patterns: list[str] | None = None,
        restrict_to_workspace: bool = False,
        webui_allow_local_service_access: bool = True,
        allow_local_preview_access: bool | None = None,
        sandbox: str = "",
        path_prepend: str = "",
        path_append: str = "",
        allowed_env_keys: list[str] | None = None,
        session_manager: Any | None = None,
    ):
        self.timeout = timeout
        self.working_dir = working_dir
        self.sandbox = sandbox
        self.deny_patterns = (deny_patterns or []) + [
            r"\brm\s+-[rf]{1,2}\b",          # rm -r, rm -rf, rm -fr
            r"\bdel\s+/[fq]\b",              # del /f, del /q
            r"\brmdir\s+/s\b",               # rmdir /s
            r"(?:^|[;&|]\s*)format(?!=)\b",   # format (as standalone command only)
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
        if allow_local_preview_access is not None:
            webui_allow_local_service_access = allow_local_preview_access
        self.webui_allow_local_service_access = webui_allow_local_service_access
        self.path_prepend = path_prepend
        self.path_append = path_append
        self.allowed_env_keys = allowed_env_keys or []
        self._session_manager = session_manager or DEFAULT_EXEC_SESSION_MANAGER

    @property
    def name(self) -> str:
        return "exec"

    _MAX_TIMEOUT = 600
    _MAX_OUTPUT = 10_000

    # Kernel device files safe as stdio redirect targets (#3599).
    _BENIGN_DEVICE_PATHS: frozenset[str] = frozenset({
        "/dev/null",
        "/dev/zero",
        "/dev/full",
        "/dev/random",
        "/dev/urandom",
        "/dev/stdin",
        "/dev/stdout",
        "/dev/stderr",
        "/dev/tty",
    })

    @property
    def description(self) -> str:
        return (
            "Execute a shell command and return its output. "
            "Use this for tests, builds, package commands, git commands, and "
            "other process execution. Prefer read_file/find_files/grep for "
            "inspection and apply_patch/write_file/edit_file for file changes "
            "instead of cat, shell find/grep, echo, or sed. "
            "Use -y or --yes flags to avoid interactive prompts. "
            "For long-running or interactive commands, pass yield_time_ms; "
            "if the command keeps running, exec returns a session_id that can "
            "be polled or written to with write_stdin. Output is truncated at "
            "10 000 chars; timeout defaults to 60s."
        )

    @property
    def exclusive(self) -> bool:
        return True

    async def execute(
        self, command: str | None = None, cmd: str | None = None,
        working_dir: str | None = None, workdir: str | None = None,
        timeout: int | None = None, shell: str | None = None,
        login: bool | None = None, yield_time_ms: int | None = None,
        max_output_chars: int | None = None,
        max_output_tokens: int | None = None,
        **kwargs: Any,
    ) -> str:
        command = command or cmd
        working_dir = working_dir or workdir
        if not command:
            return "Error: Missing command. Provide command or cmd."
        if max_output_chars is None:
            max_output_chars = max_output_tokens

        prepared = self._prepare_command(command, working_dir, timeout, shell, login)
        if isinstance(prepared, str):
            return prepared

        if yield_time_ms is not None:
            return await self._execute_session(prepared, yield_time_ms, max_output_chars)

        try:
            process = await self._spawn(
                prepared.command,
                prepared.cwd,
                prepared.env,
                prepared.shell_program,
                prepared.login,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=prepared.timeout,
                )
            except asyncio.TimeoutError:
                await self._kill_process(process)
                return f"Error: Command timed out after {prepared.timeout} seconds"
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

            max_len = clamp_session_int(max_output_chars, self._MAX_OUTPUT, 1000, MAX_OUTPUT_CHARS)
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

    async def _execute_session(
        self,
        prepared: _PreparedCommand,
        yield_time_ms: int | None,
        max_output_chars: int | None,
    ) -> str:
        try:
            session_id, poll = await self._session_manager.start(
                command=prepared.command,
                cwd=prepared.cwd,
                env=prepared.env,
                timeout=prepared.timeout,
                shell_program=prepared.shell_program,
                login=prepared.login,
                yield_time_ms=clamp_session_int(yield_time_ms, DEFAULT_YIELD_MS, 0, MAX_YIELD_MS),
                owner_session_key=current_request_session_key(),
                max_output_chars=clamp_session_int(
                    max_output_chars,
                    DEFAULT_MAX_OUTPUT_CHARS,
                    1000,
                    MAX_OUTPUT_CHARS,
                ),
            )
            return format_session_poll(session_id, poll)
        except Exception as exc:
            return f"Error executing command: {exc}"

    def _resolve_timeout(self, timeout: int | None) -> int | None:
        """Resolve the effective hard timeout in seconds (None = no limit).

        A per-call timeout supplied by the model stays capped at _MAX_TIMEOUT so
        the LLM cannot request unbounded execution. The config-level default
        (self.timeout) may exceed that cap, and 0 disables the limit entirely
        for trusted long-running tasks (#3595).
        """
        if timeout:
            return min(timeout, self._MAX_TIMEOUT)
        if self.timeout and self.timeout > 0:
            return self.timeout
        return None

    def _prepare_command(
        self,
        command: str,
        working_dir: str | None = None,
        timeout: int | None = None,
        shell: str | None = None,
        login: bool | None = None,
    ) -> _PreparedCommand | str:
        access = current_tool_workspace(
            self.working_dir,
            restrict_to_workspace=self.restrict_to_workspace,
            sandbox_restricts_workspace=bool(self.sandbox),
        )
        workspace_root = str(access.project_path) if access.project_path is not None else self.working_dir
        cwd = working_dir or workspace_root or os.getcwd()

        # Prevent an LLM-supplied working_dir from escaping the configured
        # workspace when restrict_to_workspace is enabled (#2826). Without
        # this, a caller can pass working_dir="/etc" and then all absolute
        # paths under /etc would pass the _guard_command check that anchors
        # on cwd.
        if access.restrict_to_workspace and workspace_root:
            try:
                requested = Path(cwd).expanduser().resolve()
                resolved_root = Path(workspace_root).expanduser().resolve()
            except Exception:
                return (
                    "Error: working_dir could not be resolved"
                    + _WORKSPACE_BOUNDARY_NOTE
                )
            if not is_path_within(requested, resolved_root):
                return (
                    "Error: working_dir is outside the configured workspace"
                    + _WORKSPACE_BOUNDARY_NOTE
                )

        guard_error = self._guard_command(
            command,
            cwd,
            restrict_to_workspace=access.restrict_to_workspace,
            workspace_root=workspace_root,
        )
        if guard_error:
            return guard_error

        if self.sandbox:
            if _IS_WINDOWS:
                logger.warning(
                    "Sandbox '{}' is not supported on Windows; running unsandboxed",
                    self.sandbox,
                )
            else:
                workspace = workspace_root or cwd
                command = wrap_command(self.sandbox, command, workspace, cwd)
                cwd = str(Path(workspace).resolve())

        effective_timeout = self._resolve_timeout(timeout)
        env = self._build_env()

        if self.path_prepend or self.path_append:
            if _IS_WINDOWS:
                env["PATH"] = self._compose_path(env.get("PATH", ""))
            else:
                command = self._wrap_path_export(command, env)

        shell_program, shell_error = self._resolve_shell(shell)
        if shell_error:
            return shell_error

        return _PreparedCommand(
            command=command,
            cwd=cwd,
            env=env,
            timeout=effective_timeout,
            shell_program=shell_program,
            login=False if login is None else login,
        )

    def _compose_path(self, current_path: str) -> str:
        parts = []
        if self.path_prepend:
            parts.append(self.path_prepend)
        if current_path:
            parts.append(current_path)
        if self.path_append:
            parts.append(self.path_append)
        return os.pathsep.join(parts)

    def _wrap_path_export(self, command: str, env: dict[str, str]) -> str:
        segments = []
        if self.path_prepend:
            env["NANOBOT_PATH_PREPEND"] = self.path_prepend
            segments.append("$NANOBOT_PATH_PREPEND")
        segments.append("$PATH")
        if self.path_append:
            env["NANOBOT_PATH_APPEND"] = self.path_append
            segments.append("$NANOBOT_PATH_APPEND")
        path_expr = os.pathsep.join(segments)
        return f'export PATH="{path_expr}"; {command}'

    @staticmethod
    async def _spawn(
        command: str, cwd: str, env: dict[str, str],
        shell_program: str | None = None,
        login: bool = False,
        *,
        stdin: int = asyncio.subprocess.DEVNULL,
    ) -> asyncio.subprocess.Process:
        """Launch *command* in a platform-appropriate shell."""
        if _IS_WINDOWS:
            if "\n" in command:
                return await asyncio.create_subprocess_exec(
                    "powershell", "-NoProfile", "-Command", command,
                    stdin=stdin,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                    env=env,
                )
            return await asyncio.create_subprocess_shell(
                command,
                stdin=stdin,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )
        shell_program = shell_program or shutil.which("bash") or "/bin/bash"
        args = [shell_program]
        shell_name = Path(shell_program).name.lower()
        if login and shell_name in {"bash", "bash.exe", "zsh", "zsh.exe"}:
            args.append("-l")
        args.extend(["-c", command])
        return await asyncio.create_subprocess_exec(
            *args,
            stdin=stdin,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )

    @staticmethod
    def _resolve_shell(shell: str | None) -> tuple[str | None, str | None]:
        if not shell:
            return None, None
        if _IS_WINDOWS:
            return None, "Error: shell parameter is not supported on Windows"
        if "\0" in shell or "\n" in shell or "\r" in shell:
            return None, "Error: shell contains invalid characters"
        allowed = {"sh", "bash", "zsh"}
        path = Path(shell).expanduser()
        if path.is_absolute():
            if path.name not in allowed:
                return None, f"Error: unsupported shell {shell!r}. Allowed: bash, sh, zsh"
            if not path.is_file() or not os.access(path, os.X_OK):
                return None, f"Error: shell is not executable: {shell}"
            return str(path), None
        if "/" in shell or "\\" in shell:
            return None, "Error: shell must be a shell name or absolute path"
        if shell not in allowed:
            return None, f"Error: unsupported shell {shell!r}. Allowed: bash, sh, zsh"
        resolved = shutil.which(shell)
        if not resolved:
            return None, f"Error: shell not found: {shell}"
        return resolved, None

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

        On Unix, only HOME/LANG/TERM are passed by default. If callers request
        ``login=True``, bash/zsh may source the user's profile and add PATH or
        other variables.

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
                "PYTHONUNBUFFERED": "1",
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
            "PYTHONUNBUFFERED": "1",
        }
        for key in self.allowed_env_keys:
            val = os.environ.get(key)
            if val is not None:
                env[key] = val
        return env

    def _guard_command(
        self,
        command: str,
        cwd: str,
        *,
        restrict_to_workspace: bool | None = None,
        workspace_root: str | None = None,
    ) -> str | None:
        """Best-effort safety guard for potentially destructive commands."""
        cmd = command.strip()
        lower = cmd.lower()

        # allow_patterns take priority over deny_patterns so that users can
        # exempt specific commands (e.g. "rm -rf" inside a build directory)
        # from the hardcoded deny list via configuration. A chained command is
        # only explicitly allowed when every top-level shell segment matches.
        segments = self._split_shell_segments(lower)
        explicitly_allowed = bool(self.allow_patterns) and bool(segments) and all(
            any(re.fullmatch(pattern, segment) for pattern in self.allow_patterns)
            for segment in segments
        )
        if not explicitly_allowed:
            for pattern in self.deny_patterns:
                if re.search(pattern, lower):
                    return "Error: Command blocked by deny pattern filter"

            if self.allow_patterns:
                return "Error: Command blocked by allowlist filter (not in allowlist)"

        from nanobot.security.network import contains_internal_url
        if contains_internal_url(
            cmd,
            allow_loopback=current_scope_allows_loopback(
                enabled=self.webui_allow_local_service_access,
            ),
        ):
            # The runner turns this marker into a non-retryable security hint.
            return "Error: Command blocked by safety guard (internal/private URL detected)"

        should_restrict = self.restrict_to_workspace if restrict_to_workspace is None else restrict_to_workspace
        if should_restrict:
            if "..\\" in cmd or "../" in cmd:
                return (
                    "Error: Command blocked by safety guard (path traversal detected)"
                    + _WORKSPACE_BOUNDARY_NOTE
                )

            cwd_path = Path(cwd).resolve()
            resolved_workspace = (
                Path(workspace_root).expanduser().resolve()
                if workspace_root
                else None
            )

            for raw in self._extract_absolute_paths(cmd):
                try:
                    expanded = os.path.expandvars(raw.strip())
                    # Match against the un-resolved path first.  On Linux,
                    # /dev/stderr is a symlink to /proc/self/fd/2 and
                    # ``Path.resolve()`` would mask the device-file intent.
                    if self._is_benign_device_path(expanded):
                        continue
                    p = Path(expanded).expanduser().resolve()
                except Exception:
                    continue

                if self._is_benign_device_path(str(p)):
                    continue

                media_path = get_media_dir().resolve()
                allowed = (
                    is_path_within(p, cwd_path)
                    or is_path_within(p, media_path)
                )
                if not allowed and resolved_workspace is not None:
                    allowed = is_path_within(p, resolved_workspace)
                if p.is_absolute() and not allowed:
                    return (
                        "Error: Command blocked by safety guard (path outside working dir)"
                        + _WORKSPACE_BOUNDARY_NOTE
                    )

        return None

    @staticmethod
    def _split_shell_segments(command: str) -> list[str]:
        """Split shell commands on top-level chaining operators."""
        segments: list[str] = []
        current: list[str] = []
        quote: str | None = None
        escaped = False
        paren_depth = 0
        i = 0

        while i < len(command):
            ch = command[i]

            if escaped:
                current.append(ch)
                escaped = False
                i += 1
                continue

            if ch == "\\" and quote != "'":
                current.append(ch)
                escaped = True
                i += 1
                continue

            if quote is not None:
                current.append(ch)
                if ch == quote:
                    quote = None
                i += 1
                continue

            if ch in {"'", '"', "`"}:
                current.append(ch)
                quote = ch
                i += 1
                continue

            if ch == "(":
                paren_depth += 1
                current.append(ch)
                i += 1
                continue

            if ch == ")" and paren_depth > 0:
                paren_depth -= 1
                current.append(ch)
                i += 1
                continue

            operator_len = 0
            if paren_depth == 0:
                if command.startswith(("&&", "||"), i):
                    operator_len = 2
                elif ch == "&" and not (
                    (i > 0 and command[i - 1] in "<>") or command.startswith("&>", i)
                ):
                    current.append(ch)
                    operator_len = 1
                elif ch in {";", "|"}:
                    operator_len = 1

            if operator_len:
                segment = "".join(current).strip()
                if segment:
                    segments.append(segment)
                current = []
                i += operator_len
                continue

            current.append(ch)
            i += 1

        segment = "".join(current).strip()
        if segment:
            segments.append(segment)
        return segments

    @classmethod
    def _is_benign_device_path(cls, path: str) -> bool:
        """Return True for kernel device files that should never be workspace-blocked."""
        if path in cls._BENIGN_DEVICE_PATHS:
            return True
        return path.startswith("/dev/fd/")

    @staticmethod
    def _extract_absolute_paths(command: str) -> list[str]:
        # Windows: match drive-root paths like `C:\` as well as `C:\path\to\file`, and UNC paths like `\\server\share`
        # NOTE: `*` is required so `C:\` (nothing after the slash) is still extracted.
        win_paths = re.findall(
            r"(?<![A-Za-z])(?:[A-Za-z]:[^\s\"'|><;]*|\\\\[^\s\"'|><;]+(?:\\[^\s\"'|><;]+)*)",
            command
        )
        posix_paths = re.findall(r"(?:^|[\s|>'\"])(/[^\s\"'>;|<]+)", command) # POSIX: /absolute only
        home_paths = re.findall(r"(?:^|[\s>'\"])(~[^\s\"'>;|<]*)", command) # POSIX/Windows home shortcut: ~
        return win_paths + posix_paths + home_paths
