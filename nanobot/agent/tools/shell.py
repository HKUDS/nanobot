"""Shell execution tool."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import Field, field_validator

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.sandbox import wrap_command
from nanobot.agent.tools.schema import BooleanSchema, IntegerSchema, StringSchema, tool_parameters_schema
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import Base

_IS_WINDOWS = sys.platform == "win32"


# Policy note appended to recoverable workspace-boundary guard errors.
_WORKSPACE_BOUNDARY_NOTE = (
    "\n\nNote: this is a hard policy boundary, not a transient failure. "
    "Do NOT retry with shell tricks (symlinks, base64 piping, alternative "
    "tools, working_dir overrides). If the user genuinely needs this "
    "resource, tell them you cannot reach it under the current "
    "restrict_to_workspace policy and ask how to proceed."
)


class ApprovalRule(Base):
    """A single approval rule that maps a command pattern to a policy.

    Policies:
      - ``auto``: bypass deny-pattern checks for matching commands
      - ``ask``:  return a confirmation prompt instead of hard-blocking
      - ``deny``: hard-block regardless of other settings
    """

    pattern: str
    policy: str = "ask"  # auto | ask | deny

    @field_validator("policy")
    @classmethod
    def validate_policy(cls, v):
        if v not in {"auto", "ask", "deny"}:
            raise ValueError(f"Invalid policy: {v}, must be one of auto/ask/deny")
        return v


class ExecToolConfig(Base):
    """Shell exec tool configuration."""

    enable: bool = True
    timeout: int = 60
    path_append: str = ""
    sandbox: str = ""
    allowed_env_keys: list[str] = Field(default_factory=list)
    allow_patterns: list[str] = Field(default_factory=list)
    deny_patterns: list[str] = Field(default_factory=list)
    enable_user_confirmation: bool = False
    safe_binaries: list[str] = Field(default_factory=list)
    approval_rules: list[ApprovalRule] = Field(default_factory=list)


@tool_parameters(
    tool_parameters_schema(
        command=StringSchema("The shell command to execute"),
        working_dir=StringSchema("Optional working directory for the command"),
        timeout=IntegerSchema(
            60,
            description=(
                "Timeout in seconds. Increase for long-running commands "
                "like compilation or installation (default 60, max 600)."
            ),
            minimum=1,
            maximum=600,
        ),
        confirmed=BooleanSchema(
            description=(
                "Set to true to confirm execution of a command that was "
                "previously blocked and returned with a NEEDS_CONFIRMATION "
                "prompt. The user must explicitly approve before you set this."
            ),
            default=False,
        ),
        required=["command"],
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
            sandbox=cfg.sandbox,
            path_append=cfg.path_append,
            allowed_env_keys=cfg.allowed_env_keys,
            allow_patterns=cfg.allow_patterns,
            deny_patterns=cfg.deny_patterns,
            enable_user_confirmation=cfg.enable_user_confirmation,
            safe_binaries=cfg.safe_binaries,
            approval_rules=cfg.approval_rules,
        )

    def __init__(
        self,
        timeout: int = 60,
        working_dir: str | None = None,
        deny_patterns: list[str] | None = None,
        allow_patterns: list[str] | None = None,
        restrict_to_workspace: bool = False,
        sandbox: str = "",
        path_append: str = "",
        allowed_env_keys: list[str] | None = None,
        enable_user_confirmation: bool = False,
        safe_binaries: list[str] | None = None,
        approval_rules: list[ApprovalRule] | None = None,
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
        self.path_append = path_append
        self.allowed_env_keys = allowed_env_keys or []
        self.enable_user_confirmation = enable_user_confirmation
        self.safe_binaries = safe_binaries or []
        self.approval_rules = approval_rules or []
        # Pending command state for user confirmation flow.
        self._pending_command: str | None = None
        self._pending_cwd: str | None = None
        self._pending_timeout: int | None = None

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
        timeout: int | None = None, confirmed: bool = False, **kwargs: Any,
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
                return (
                    "Error: working_dir could not be resolved"
                    + _WORKSPACE_BOUNDARY_NOTE
                )
            if requested != workspace_root and workspace_root not in requested.parents:
                return (
                    "Error: working_dir is outside the configured workspace"
                    + _WORKSPACE_BOUNDARY_NOTE
                )

        # --- User confirmation flow ---
        # If the user confirmed a previously pending command, execute it
        # directly (skip the guard for that specific command).
        if confirmed and self._pending_command is not None:
            saved_cmd = self._pending_command
            saved_cwd = self._pending_cwd
            saved_timeout = self._pending_timeout
            self._pending_command = None
            self._pending_cwd = None
            self._pending_timeout = None
            # Only execute if the confirmed command matches the current one.
            if command.strip() == saved_cmd.strip():
                logger.info("exec: user confirmed pending command: {}", saved_cmd)
                return await self._run_command(saved_cmd, saved_cwd or cwd, saved_timeout or timeout)
            # Mismatch: the confirmed command differs from the pending one.
            logger.warning("exec: confirmed command mismatch, pending={!r}, current={!r}", saved_cmd, command)
            # Fall through to normal guard check for the new command.

        guard_error = self._guard_command(command, cwd)
        if guard_error:
            # If user confirmation is enabled and the block is from a deny
            # pattern (not a hard policy like SSRF or workspace boundary),
            # return a confirmation prompt instead of a hard block.
            if self.enable_user_confirmation and "deny pattern" in guard_error:
                self._pending_command = command
                self._pending_cwd = cwd
                self._pending_timeout = timeout
                logger.info("exec: command needs user confirmation: {}", command)
                return (
                    f"NEEDS_CONFIRMATION: {command}\n\n"
                    "This command was blocked by the safety guard because it "
                    "matches a dangerous pattern. If you want to proceed, "
                    "tell the user what the command does and ask for their "
                    "explicit approval. If they approve, re-run the exec tool "
                    "with confirmed=true."
                )
            return guard_error

        return await self._run_command(command, cwd, timeout)

    async def _run_command(
        self, command: str, cwd: str, timeout: int | None = None,
    ) -> str:
        """Execute *command* in *cwd* after all guard checks have passed."""
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

        effective_timeout = min(timeout or self.timeout, self._MAX_TIMEOUT)
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
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=effective_timeout,
                )
            except asyncio.TimeoutError:
                await self._kill_process(process)
                return f"Error: Command timed out after {effective_timeout} seconds"
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

    @staticmethod
    async def _spawn(
        command: str, cwd: str, env: dict[str, str],
    ) -> asyncio.subprocess.Process:
        """Launch *command* in a platform-appropriate shell."""
        if _IS_WINDOWS:
            # create_subprocess_exec re-quotes args via list2cmdline, which
            # breaks commands containing paths with spaces (e.g. "D:\Program
            # Files\python.exe" "script.py"). create_subprocess_shell passes
            # the raw command string to COMSPEC without re-quoting.
            return await asyncio.create_subprocess_shell(
                command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )
        bash = shutil.which("bash") or "/bin/bash"
        return await asyncio.create_subprocess_exec(
            bash, "-l", "-c", command,
            stdin=asyncio.subprocess.DEVNULL,
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

    def _match_approval_policy(self, command: str) -> str | None:
        """Return the approval policy for *command*, or None if no rule matches.

        Checks approval_rules first (first match wins), then safe_binaries.
        Returns one of ``"auto"``, ``"ask"``, ``"deny"``, or ``None``.
        """
        lower = command.strip().lower()

        # 1. Check explicit approval_rules (first match wins).
        for rule in self.approval_rules:
            if re.search(rule.pattern, lower):
                return rule.policy

        # 2. Check safe_binaries — commands starting with a safe binary
        #    are auto-approved.
        if self.safe_binaries:
            first_token = lower.split()[0] if lower.split() else ""
            # Strip common path prefix to get the binary name.
            binary_name = first_token.rsplit("/", 1)[-1]
            if binary_name in self.safe_binaries:
                return "auto"

        return None

    @staticmethod
    def _check_user_confirmation(response: str) -> bool:
        """Return True if *response* is an affirmative confirmation."""
        affirmative = {"yes", "y", "ok", "approve", "同意", "是的", "执行吧"}
        normalized = response.strip().lower()
        if normalized in affirmative:
            return True
        # Only check multi-character keywords in substring to avoid
        # false positives (e.g. "deny" contains "y").
        return any(kw in normalized for kw in affirmative if len(kw) > 1)

    def _guard_command(self, command: str, cwd: str) -> str | None:
        """Best-effort safety guard for potentially destructive commands."""
        cmd = command.strip()
        lower = cmd.lower()

        # --- Approval rules take highest priority ---
        policy = self._match_approval_policy(cmd)
        if policy == "auto":
            # Explicitly auto-approved — skip all deny checks.
            logger.info("exec: command auto-approved by approval rule: {}", cmd)
        elif policy == "deny":
            logger.warning("exec: command blocked by approval policy (deny): {}", cmd)
            return "Error: Command blocked by approval policy"
        else:
            # No matching approval rule (or policy="ask").
            # allow_patterns take priority over deny_patterns so that users can
            # exempt specific commands (e.g. "rm -rf" inside a build directory)
            # from the hardcoded deny list via configuration.
            explicitly_allowed = bool(self.allow_patterns) and any(
                re.search(p, lower) for p in self.allow_patterns
            )
            if not explicitly_allowed:
                for pattern in self.deny_patterns:
                    if re.search(pattern, lower):
                        logger.warning("exec: command blocked by deny pattern: {} (matched: {})", cmd, pattern)
                        return "Error: Command blocked by deny pattern filter"

                if self.allow_patterns:
                    logger.warning("exec: command blocked by allowlist filter: {}", cmd)
                    return "Error: Command blocked by allowlist filter (not in allowlist)"
            else:
                logger.info("exec: command allowed by allow_patterns: {}", cmd)

        from nanobot.security.network import contains_internal_url
        if contains_internal_url(cmd):
            # The runner turns this marker into a non-retryable security hint.
            return "Error: Command blocked by safety guard (internal/private URL detected)"

        if self.restrict_to_workspace:
            if "..\\" in cmd or "../" in cmd:
                return (
                    "Error: Command blocked by safety guard (path traversal detected)"
                    + _WORKSPACE_BOUNDARY_NOTE
                )

            cwd_path = Path(cwd).resolve()

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
                if (p.is_absolute()
                    and cwd_path not in p.parents
                    and p != cwd_path
                    and media_path not in p.parents
                    and p != media_path
                ):
                    return (
                        "Error: Command blocked by safety guard (path outside working dir)"
                        + _WORKSPACE_BOUNDARY_NOTE
                    )

        return None

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
            r"(?:[A-Za-z]:[^\s\"'|><;]*|\\\\[^\s\"'|><;]+(?:\\[^\s\"'|><;]+)*)",
            command
        )
        posix_paths = re.findall(r"(?:^|[\s|>'\"])(/[^\s\"'>;|<]+)", command) # POSIX: /absolute only
        home_paths = re.findall(r"(?:^|[\s>'\"])(~[^\s\"'>;|<]*)", command) # POSIX/Windows home shortcut: ~
        return win_paths + posix_paths + home_paths
