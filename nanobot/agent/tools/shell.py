"""Shell execution tool."""

import asyncio
import os
import re
import shlex
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool


class ExecTool(Tool):
    """Tool to execute shell commands."""
    
    def __init__(
        self,
        timeout: int = 60,
        working_dir: str | None = None,
        deny_patterns: list[str] | None = None,
        allow_patterns: list[str] | None = None,
        restrict_to_workspace: bool = False,
        allowed_commands: set[str] | None = None,  # 新增：命令白名单
    ):
        self.timeout = timeout
        self.working_dir = working_dir
        # Built-in dangerous patterns (always active)
        built_in_patterns = [
            r"\brm\s+-[rf]{1,2}\b",          # rm -r, rm -rf, rm -fr
            r"\bdel\s+/[fq]\b",              # del /f, del /q
            r"\brmdir\s+/s\b",               # rmdir /s
            r"\b(format|mkfs|diskpart)\b",   # disk operations
            r"\bdd\s+if=",                   # dd
            r">\s*/dev/sd",                  # write to disk
            r"\b(shutdown|reboot|poweroff)\b",  # system power
            r":\(\)\s*\{.*\};\s*:",          # fork bomb
        ]
        # Merge built-in patterns with custom patterns
        self.deny_patterns = built_in_patterns + (deny_patterns or [])
        self.allow_patterns = allow_patterns or []
        self.restrict_to_workspace = restrict_to_workspace
        # 白名单模式，只允许执行指定的命令
        # 如果为 None，则允许所有安全命令
        # 如果设置，例如 {'ls', 'cat', 'echo', 'pwd'}，则只允许这些命令
        self.allowed_commands = allowed_commands
    
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
                    "description": "The shell command to execute"
                },
                "working_dir": {
                    "type": "string",
                    "description": "Optional working directory for the command"
                }
            },
            "required": ["command"]
        }
    
    async def execute(self, command: str, working_dir: str | None = None, **kwargs: Any) -> str:
        cwd = working_dir or self.working_dir or os.getcwd()

        # Validate command before execution
        guard_error = self._guard_command(command, cwd)
        if guard_error:
            return guard_error

        try:
            # Parse command safely using shlex.split()
            # This prevents command injection by splitting on spaces only,
            # respecting quotes and escaping
            try:
                args = shlex.split(command)
            except ValueError as e:
                return f"Error: Invalid command syntax - {str(e)}"

            if not args:
                return "Error: Empty command"

            # SECURITY: Use create_subprocess_exec instead of create_subprocess_shell
            # - exec: Direct program execution, arguments passed as array
            # - shell: Goes through /bin/sh, parses special characters (;|&$`<>() etc)
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                return f"Error: Command timed out after {self.timeout} seconds"
            
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
            if len(result) > max_len:
                result = result[:max_len] + f"\n... (truncated, {len(result) - max_len} more chars)"
            
            return result
            
        except Exception as e:
            return f"Error executing command: {str(e)}"

    def _guard_command(self, command: str, cwd: str) -> str | None:
        """
        Best-effort safety guard for potentially destructive commands.

        SECURITY NOTE: This is defense-in-depth. The primary protection is
        using create_subprocess_exec instead of create_subprocess_shell.
        """
        cmd = command.strip()
        lower = cmd.lower()

        # ===== NEW: Command whitelist check =====
        # Extract the command binary (first word before any space)
        cmd_binary = cmd.split()[0] if cmd.split() else ""

        # If whitelist is enabled, check if command is allowed
        if self.allowed_commands is not None:
            if cmd_binary not in self.allowed_commands:
                allowed_list = ", ".join(sorted(self.allowed_commands))
                return f"Error: Command '{cmd_binary}' is not allowed. Allowed commands: {allowed_list}"

        # Check for shell injection attempts (won't work with exec, but detect for logging)
        shell_operators = [
            r';\s*\w',           # command separator: cmd; other_cmd
            r'\|\|?\s*\w',       # pipes: cmd1 | cmd2, cmd1 || cmd2
            r'&&\s*\w',          # AND operator: cmd1 && cmd2
            r'\$\(',             # command substitution: $(cmd)
            r'`.*`',             # command substitution: `cmd`
            r'<\s*[^-\s]',       # input redirection: cmd < file
            r'>\s*[^-\s]',       # output redirection (we allow >- for stdout): cmd > file
            r'\{\s*\w',          # brace expansion attempts
        ]

        for pattern in shell_operators:
            if re.search(pattern, cmd):
                return f"Error: Shell operator not allowed. Only simple commands are supported."

        # Check deny patterns
        for pattern in self.deny_patterns:
            if re.search(pattern, lower):
                return "Error: Command blocked by safety guard (dangerous pattern detected)"

        # Additional dangerous commands not covered by patterns
        dangerous_binaries = [
            'chmod', 'chown', 'iptables', 'useradd', 'usermod',
            'userdel', 'nc -e', 'netcat', 'socat', 'telnet',
        ]

        if any(cmd_binary == d or cmd_binary.startswith(d + ' ') for d in dangerous_binaries):
            return f"Error: Command '{cmd_binary}' is blocked for security reasons"

        # Allowlist mode
        if self.allow_patterns:
            if not any(re.search(p, lower) for p in self.allow_patterns):
                return "Error: Command blocked by safety guard (not in allowlist)"

        # Workspace restriction
        if self.restrict_to_workspace:
            if "..\\" in cmd or "../" in cmd:
                return "Error: Command blocked by safety guard (path traversal detected)"

            cwd_path = Path(cwd).resolve()

            win_paths = re.findall(r"[A-Za-z]:\\[^\\\"']+", cmd)
            posix_paths = re.findall(r"/[^\s\"']+", cmd)

            for raw in win_paths + posix_paths:
                try:
                    p = Path(raw).resolve()
                except Exception:
                    continue
                if cwd_path not in p.parents and p != cwd_path:
                    return "Error: Command blocked by safety guard (path outside working dir)"

        return None
