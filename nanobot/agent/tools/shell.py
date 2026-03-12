"""Shell execution tool with deny/allow security model.

``ExecTool`` runs shell commands in the agent's working directory with a
two-layer security model:

- **Denylist mode** (default): commands are checked against
  ``_DEFAULT_DENY_PATTERNS`` — regex patterns that block destructive
  operations (``rm -rf``, ``dd``, fork bombs, hex-escape bypasses, etc.).
  A blocked command returns ``ToolResult.fail`` without execution.
- **Allowlist mode** (``shell_mode='allowlist'``): only commands matching
  ``_DEFAULT_ALLOW_PATTERNS`` (git, python, curl, standard coreutils, …)
  are permitted.  Everything else is blocked.

The guard runs on lowercased input so case variations are caught.

Workspace restriction and configurable timeouts provide additional safety.
See ``tests/test_shell_safety.py`` for 40+ parametrized test cases covering
bypass attempts.
"""

import asyncio
import os
import re
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool, ToolResult
from nanobot.errors import ToolPermissionError, ToolTimeoutError

# Default deny patterns — designed to catch common destructive commands
# even through basic shell quoting / escaping tricks.
_DEFAULT_DENY_PATTERNS: list[str] = [
    r"\brm\s+-[rf]{1,2}\b",  # rm -r, rm -rf, rm -fr
    r"\bdel\s+/[fq]\b",  # del /f, del /q
    r"\brmdir\s+/s\b",  # rmdir /s
    r"(?:^|[;&|]\s*)format\b",  # format (as standalone command only)
    r"\b(mkfs|diskpart)\b",  # disk operations
    r"\bdd\s+if=",  # dd
    r">\s*/dev/sd",  # write to disk
    r"\b(shutdown|reboot|poweroff)\b",  # system power
    r":\(\)\s*\{.*\};\s*:",  # fork bomb
    # Hardened: catch variable-expansion / hex-escape / base64 bypass attempts
    r"\$['\"]\\x[0-9a-f]{2}",  # $'\x72\x6d' hex escape
    r"\bbase64\s.*\|\s*(sh|bash|zsh)\b",  # base64 decode | sh
    r"\beval\s+.*\$",  # eval with variable expansion
    r"\bchmod\s+[0-7]*777\b",  # chmod 777
    r"\bchown\s+-r\s+root\b",  # chown -R root (pattern lowercase; guard lowercases input)
    r"\bcurl\s+.*\|\s*(sh|bash|zsh)\b",  # curl | sh
    r"\bwget\s+.*\|\s*(sh|bash|zsh)\b",  # wget | sh
]

# Default allowlist (only used when shell_mode == "allowlist")
_DEFAULT_ALLOW_PATTERNS: list[str] = [
    r"^(ls|cat|head|tail|grep|awk|sed|wc|sort|uniq|find|file|stat|du|df|which|whereis|type)\b",
    r"^(echo|printf|date|cal|uname|hostname|whoami|env|printenv)\b",
    r"^(cd|pwd|pushd|popd|mkdir|touch|cp|mv|ln|readlink)\b",
    r"^(git|gh)\b",
    r"^(python|python3|pip|pip3|node|npm|npx|bun|deno|cargo|go|ruby|java|javac)\b",
    r"^(curl|wget|ssh|scp|rsync)\b",
    r"^(docker|docker-compose|podman)\b",
    r"^(make|cmake|ninja|gcc|g\+\+|clang)\b",
    r"^(tar|gzip|gunzip|zip|unzip|xz|bzip2)\b",
    r"^(systemctl|journalctl|service)\b",
    r"^(apt|apt-get|brew|yum|dnf|pacman|apk)\b",
    r"^(jq|yq|tree|less|more|diff|patch|tee|xargs)\b",
]


class ExecTool(Tool):
    """Tool to execute shell commands."""

    readonly = False

    def __init__(
        self,
        timeout: int = 60,
        working_dir: str | None = None,
        deny_patterns: list[str] | None = None,
        allow_patterns: list[str] | None = None,
        restrict_to_workspace: bool = False,
        shell_mode: str = "denylist",
    ):
        self.timeout = timeout
        self.working_dir = working_dir
        self.shell_mode = shell_mode  # "allowlist" | "denylist"
        self.deny_patterns = deny_patterns or list(_DEFAULT_DENY_PATTERNS)
        self.allow_patterns = allow_patterns or (
            list(_DEFAULT_ALLOW_PATTERNS) if shell_mode == "allowlist" else []
        )
        self.restrict_to_workspace = restrict_to_workspace

    @property
    def name(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
        return "Execute a shell command and return its output. Use with caution."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute (alias: cmd)",
                },
                "working_dir": {
                    "type": "string",
                    "description": "Optional working directory for the command",
                },
            },
            "required": ["command"],
        }

    async def execute(
        self,
        command: str | None = None,
        cmd: str | None = None,
        working_dir: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        # Accept 'cmd' as alias for 'command' (models frequently use it)
        command = command or cmd
        if not command:
            return ToolResult.fail("Error: 'command' (or 'cmd') parameter is required")
        cwd = working_dir or self.working_dir or os.getcwd()
        guard_error = self._guard_command(command, cwd)
        if guard_error:
            raise ToolPermissionError("exec", guard_error)

        env = os.environ.copy()
        self._inject_node_ca_bundle(env)

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
            except asyncio.TimeoutError:
                process.kill()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
                raise ToolTimeoutError("exec", self.timeout)

            output_parts = []

            if stdout:
                output_parts.append(stdout.decode("utf-8", errors="replace"))

            if stderr:
                stderr_text = stderr.decode("utf-8", errors="replace")
                if stderr_text.strip():
                    output_parts.append(f"STDERR:\n{stderr_text}")

            if process.returncode != 0:
                output_parts.append(f"\nExit code: {process.returncode}")

            result = "\n".join(output_parts) if output_parts else "(no output)"

            # Truncate very long output
            max_len = 10000
            was_truncated = len(result) > max_len
            if was_truncated:
                result = result[:max_len] + f"\n... (truncated, {len(result) - max_len} more chars)"

            is_success = process.returncode == 0
            if is_success:
                return ToolResult.ok(result, truncated=was_truncated)
            else:
                return ToolResult(
                    output=result,
                    success=False,
                    error=f"Command exited with code {process.returncode}",
                    truncated=was_truncated,
                    metadata={"exit_code": process.returncode},
                )

        except Exception as e:  # crash-barrier: subprocess + asyncio produce varied errors
            return ToolResult.fail(f"Error executing command: {str(e)}")

    @staticmethod
    def _inject_node_ca_bundle(env: dict[str, str]) -> None:
        """Ensure Node-based CLIs can validate TLS cert chains on Linux hosts."""
        if env.get("NODE_EXTRA_CA_CERTS"):
            return

        candidates = [
            "/etc/ssl/certs/ca-certificates.crt",  # Debian/Ubuntu
            "/etc/pki/tls/certs/ca-bundle.crt",  # RHEL/CentOS/Fedora
            "/etc/ssl/cert.pem",  # Alpine/macOS common path
        ]

        for bundle_path in candidates:
            if Path(bundle_path).is_file():
                env["NODE_EXTRA_CA_CERTS"] = bundle_path
                return

    def _guard_command(self, command: str, cwd: str) -> str | None:
        """Best-effort safety guard for potentially destructive commands."""
        cmd = command.strip()
        lower = cmd.lower()

        # Normalize common evasion tricks for pattern matching
        # Decode \\xHH hex sequences to their characters
        normalized = re.sub(
            r"\\x([0-9a-fA-F]{2})",
            lambda m: chr(int(m.group(1), 16)),
            lower,
        )

        for pattern in self.deny_patterns:
            if re.search(pattern, lower) or re.search(pattern, normalized):
                return "Error: Command blocked by safety guard (dangerous pattern detected)"

        if self.allow_patterns:
            # In allowlist mode, the first "word" of each command in a pipeline / chain
            # must match at least one allow pattern.
            segments = re.split(r"[;&|]+", lower)
            for segment in segments:
                segment = segment.strip()
                if not segment:
                    continue
                if not any(re.search(p, segment) for p in self.allow_patterns):
                    return "Error: Command blocked by safety guard (not in allowlist)"

        if self.restrict_to_workspace:
            if "..\\" in cmd or "../" in cmd:
                return "Error: Command blocked by safety guard (path traversal detected)"

            cwd_path = Path(cwd).resolve()

            win_paths = re.findall(r"[A-Za-z]:[\\][^\s\"']+", cmd)
            # Only match absolute paths — avoid false positives on relative
            # paths like ".venv/bin/python" where "/bin/python" would be
            # incorrectly extracted by the old pattern.
            posix_paths = re.findall(r"(?:^|[\s|>])(/[^\s\"'>]+)", cmd)

            for raw in win_paths + posix_paths:
                try:
                    p = Path(raw.strip()).resolve()
                except (OSError, ValueError):
                    continue
                if p.is_absolute() and cwd_path not in p.parents and p != cwd_path:
                    return "Error: Command blocked by safety guard (path outside working dir)"

        return None
