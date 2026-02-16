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

    _SCRIPT_INTERPRETER_TOKENS = (
        "python",
        "python3",
        "py",
        "node",
        "deno",
        "ruby",
        "perl",
        "php",
        "pwsh",
        "powershell",
        "bash",
        "sh",
        "zsh",
        "fish",
        "cmd",
        "cmd.exe",
    )
    _SCRIPT_DELETE_PATTERNS = (
        r"\bshutil\.rmtree\s*\(",
        r"\bos\.(?:remove|unlink|rmdir)\s*\(",
        r"\bpathlib\.path\s*\([^)]*\)\.(?:unlink|rmdir)\s*\(",
        r"\bfs\.(?:rm|rmdir|unlink|rmsync|unlinksync)\s*\(",
        r"\bremove-item\b[^\n]*\b(?:-recurse|-force)\b",
        r"\bsubprocess\.(?:run|call|popen)\s*\([^)]*?\brm\s+-",
    )
    _SCRIPT_FILE_SUFFIXES = {".py", ".js", ".ts", ".mjs", ".cjs", ".sh", ".bash", ".zsh", ".ps1"}

    def __init__(
        self,
        timeout: int = 60,
        working_dir: str | None = None,
        deny_patterns: list[str] | None = None,
        allow_patterns: list[str] | None = None,
        block_destructive_scripts: bool = True,
        restrict_to_workspace: bool = False,
    ):
        self.timeout = timeout
        self.working_dir = working_dir
        self.deny_patterns = deny_patterns or [
            r"\brm\s+-[rf]{1,2}\b",  # rm -r, rm -rf, rm -fr
            r"\bdel\s+/[fq]\b",  # del /f, del /q
            r"\brmdir\s+/s\b",  # rmdir /s
            r"\bremove-item\b[^\n]*\b(?:-recurse|-force)\b",  # PowerShell recursive delete
            r"\b(format|mkfs|diskpart)\b",  # disk operations
            r"\bdd\s+if=",  # dd
            r">\s*/dev/sd",  # write to disk
            r"\bfind\b[^\n]*\s-delete\b",  # find ... -delete
            r"\b(shutdown|reboot|poweroff)\b",  # system power
            r":\(\)\s*\{.*\};\s*:",  # fork bomb
        ]
        self.allow_patterns = allow_patterns or []
        self.block_destructive_scripts = block_destructive_scripts
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
                    "description": "The shell command to execute",
                },
                "working_dir": {
                    "type": "string",
                    "description": "Optional working directory for the command",
                },
            },
            "required": ["command"],
        }

    async def execute(self, command: str, working_dir: str | None = None, **kwargs: Any) -> str:
        cwd = working_dir or self.working_dir or os.getcwd()
        guard_error = self._guard_command(command, cwd)
        if guard_error:
            return guard_error

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout,
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
        """Best-effort safety guard for potentially destructive commands."""
        cmd = command.strip()
        lower = cmd.lower()

        for pattern in self.deny_patterns:
            if re.search(pattern, lower):
                return "Error: Command blocked by safety guard (dangerous pattern detected)"

        if self.block_destructive_scripts and self._contains_destructive_script(cmd, cwd):
            return "Error: Command blocked by safety guard (destructive script detected)"

        if self.allow_patterns:
            if not any(re.search(p, lower) for p in self.allow_patterns):
                return "Error: Command blocked by safety guard (not in allowlist)"

        if self.restrict_to_workspace:
            if "..\\" in cmd or "../" in cmd:
                return "Error: Command blocked by safety guard (path traversal detected)"

            cwd_path = Path(cwd).resolve()

            win_paths = re.findall(r"[A-Za-z]:\\[^\\\"']+", cmd)
            # Only match absolute paths to avoid false positives on relative
            # paths like ".venv/bin/python" where "/bin/python" would be
            # incorrectly extracted by the old pattern.
            posix_paths = re.findall(r"(?:^|[\s|>])(/[^\s\"'>]+)", cmd)

            for raw in win_paths + posix_paths:
                try:
                    p = Path(raw.strip()).resolve()
                except Exception:
                    continue
                if p.is_absolute() and cwd_path not in p.parents and p != cwd_path:
                    return "Error: Command blocked by safety guard (path outside working dir)"

        return None

    def _contains_destructive_script(self, command: str, cwd: str) -> bool:
        """Detect destructive file operations embedded in interpreter commands."""
        lower_command = command.lower()
        if not any(token in lower_command for token in self._SCRIPT_INTERPRETER_TOKENS):
            return False

        # Split only on explicit shell-chain operators/newlines.
        # Do not split on ';' because it appears frequently inside
        # interpreter inline scripts (e.g. python -c "...; ...").
        segments = re.split(r"\s*(?:&&|\|\||\n)\s*", command)
        for segment in segments:
            if not segment:
                continue
            invocation = self._extract_interpreter_invocation(segment)
            if invocation is None:
                continue
            _, args = invocation
            lower_segment = segment.lower()
            if any(re.search(pattern, lower_segment) for pattern in self._SCRIPT_DELETE_PATTERNS):
                return True

            script_target = self._find_script_target(args)
            if script_target is None:
                continue
            if self._script_contains_dangerous_ops(script_target, cwd):
                return True
        return False

    @staticmethod
    def _safe_split(command: str) -> list[str]:
        try:
            return shlex.split(command, posix=(os.name != "nt"))
        except ValueError:
            return command.split()

    def _extract_interpreter_invocation(self, command: str) -> tuple[str, list[str]] | None:
        tokens = self._safe_split(command)
        if not tokens:
            return None

        first = Path(tokens[0]).name.lower()
        if first in self._SCRIPT_INTERPRETER_TOKENS:
            return first, tokens[1:]

        # Support wrappers like "uv run python -c ..." or "poetry run python ...".
        if first in {"uv", "uvx", "poetry", "pipenv", "npm", "npx"}:
            for index, token in enumerate(tokens[1:4], start=1):
                if token in {"run", "exec", "--"}:
                    continue
                name = Path(token).name.lower()
                if name in self._SCRIPT_INTERPRETER_TOKENS:
                    return name, tokens[index + 1 :]
                return None
        return None

    def _find_script_target(self, args: list[str]) -> str | None:
        """Find the script path argument for interpreter invocations, if present."""
        if not args:
            return None
        fallback: str | None = None
        index = 0
        while index < len(args):
            token = self._normalize_arg(args[index])
            if token in {"-c", "-m", "-"}:
                return None
            if token.startswith("-"):
                index += 1
                continue
            p = Path(token)
            if p.suffix.lower() in self._SCRIPT_FILE_SUFFIXES or p.exists():
                return token
            if fallback is None:
                fallback = token
            index += 1
        return fallback

    @staticmethod
    def _normalize_arg(arg: str) -> str:
        return arg.strip().strip("\"'")

    def _script_contains_dangerous_ops(self, script_target: str, cwd: str) -> bool:
        script_path = Path(script_target)
        if not script_path.is_absolute():
            script_path = Path(cwd) / script_path

        # If the command points to a likely script file we cannot inspect, block it.
        # This closes an easy bypass: write script + execute script.
        suffix = script_path.suffix.lower()
        likely_script = suffix in self._SCRIPT_FILE_SUFFIXES
        if not script_path.exists():
            return likely_script

        if not script_path.is_file():
            return False

        try:
            content = script_path.read_text(encoding="utf-8", errors="ignore").lower()
        except Exception:
            return True

        return any(re.search(pattern, content) for pattern in self._SCRIPT_DELETE_PATTERNS)
