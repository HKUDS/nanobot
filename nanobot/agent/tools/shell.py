"""Shell execution tool."""

import asyncio
import os
import re
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool, ToolResult


class ExecTool(Tool):
    """Tool to execute shell commands."""

    def __init__(
        self,
        timeout: int = 60,
        working_dir: str | None = None,
        deny_patterns: list[str] | None = None,
        allow_patterns: list[str] | None = None,
        restrict_to_workspace: bool = False,
        path_append: str = "",
    ):
        self.timeout = timeout
        self.working_dir = working_dir
        self.deny_patterns = deny_patterns or [
            r"\brm\s+-[rf]{1,2}\b",          # rm -r, rm -rf, rm -fr
            r"\bdel\s+/[fq]\b",              # del /f, del /q
            r"\brmdir\s+/s\b",               # rmdir /s
            r"(?:^|[;&|]\s*)format\b",       # format (as standalone command only)
            r"\b(mkfs|diskpart)\b",          # disk operations
            r"\bdd\s+if=",                   # dd
            r">\s*/dev/sd",                  # write to disk
            r"\b(shutdown|reboot|poweroff)\b",  # system power
            r":\(\)\s*\{.*\};\s*:",          # fork bomb
        ]
        self.allow_patterns = allow_patterns or []
        self.restrict_to_workspace = restrict_to_workspace
        self.path_append = path_append

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

    async def execute(self, command: str, working_dir: str | None = None, **kwargs: Any) -> str | ToolResult:
        cwd = working_dir or self.working_dir or os.getcwd()
        guard_error = self._guard_command(command, cwd)
        if guard_error:
            return guard_error

        env = os.environ.copy()
        if self.path_append:
            env["PATH"] = env.get("PATH", "") + os.pathsep + self.path_append

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass

                return ToolResult(
                    content=f"Command timed out after {self.timeout} seconds",
                    display="",  # No output to show for timeout
                    display_type="exec_output",
                )

            # Decode output - keep exactly as command produced it
            stdout_text = stdout.decode("utf-8", errors="replace") if stdout else ""
            stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""

            # Combine stdout and stderr in their original form
            # No processing, no filtering, no adding labels
            combined = stdout_text
            if stderr_text:
                if combined:
                    combined += stderr_text
                else:
                    combined = stderr_text

            # Send raw output to LLM for context
            content = combined if combined else "Command completed with no output"

            return ToolResult(
                content=content,  # Raw output for LLM
                display=self._format_exec_output(combined),  # Formatted output for user
                display_type="exec_output",
            )

        except Exception as e:
            return f"Error executing command: {str(e)}"

    def _format_exec_output(self, output: str) -> str:
        """
        Format command output with full-width background color.

        Args:
            output: Raw command output.

        Returns:
            Formatted string with ANSI color codes for terminal display.
            Each line is padded with spaces to fill the terminal width.
        """
        if not output:
            return ""

        # ANSI color codes - dark gray background with dim foreground
        BG_COLOR = "\x1b[48;2;26;26;26m"   # #1a1a1a
        DIM_FG = "\x1b[38;2;150;150;150m"   # 暗灰色
        RESET = "\x1b[0m"

        # Get terminal width for full-line background
        try:
            terminal_width = os.get_terminal_size().columns
        except OSError:
            # Fallback if terminal size cannot be determined
            terminal_width = 100

        lines = []
        for line in output.splitlines():
            # Calculate visible content length (ANSI codes don't count)
            content_len = len(line)
            # Pad with spaces to fill terminal width
            remaining = max(0, terminal_width - content_len)
            # Apply background color and dim foreground, no trailing \n
            padded = f"{line}{' ' * remaining}"
            lines.append(f"{BG_COLOR}{DIM_FG}{padded}{RESET}")

        return "\n".join(lines) + "\n"

    def _guard_command(self, command: str, cwd: str) -> str | None:
        """Best-effort safety guard for potentially destructive commands."""
        cmd = command.strip()
        lower = cmd.lower()

        for pattern in self.deny_patterns:
            if re.search(pattern, lower):
                return "Error: Command blocked by safety guard (dangerous pattern detected)"

        if self.allow_patterns:
            if not any(re.search(p, lower) for p in self.allow_patterns):
                return "Error: Command blocked by safety guard (not in allowlist)"

        if self.restrict_to_workspace:
            if "..\\" in cmd or "../" in cmd:
                return "Error: Command blocked by safety guard (path traversal detected)"

            cwd_path = Path(cwd).resolve()

            for raw in self._extract_absolute_paths(cmd):
                try:
                    p = Path(raw.strip()).resolve()
                except Exception:
                    continue
                if p.is_absolute() and cwd_path not in p.parents and p != cwd_path:
                    return "Error: Command blocked by safety guard (path outside working dir)"

        return None

    @staticmethod
    def _extract_absolute_paths(command: str) -> list[str]:
        win_paths = re.findall(r"[A-Za-z]:\\[^\s\"'|><;]+", command)   # Windows: C:\...
        posix_paths = re.findall(r"(?:^|[\s|>])(/[^\s\"'>]+)", command) # POSIX: /absolute only
        return win_paths + posix_paths
