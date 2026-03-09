"""Shell execution tool."""

import asyncio
import locale
import os
import re
import sys
import tempfile
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
    
    async def execute(self, command: str, working_dir: str | None = None, **kwargs: Any) -> str:
        cwd = working_dir or self.working_dir or os.getcwd()
        guard_error = self._guard_command(command, cwd)
        if guard_error:
            return guard_error
        
        env = os.environ.copy()
        if sys.platform == "win32":
            env["PYTHONIOENCODING"] = "utf-8"
        if self.path_append:
            env["PATH"] = env.get("PATH", "") + os.pathsep + self.path_append

        try:
            # On Windows, redirect to temp files instead of pipes.
            # Pipes hang when child processes (e.g. a spawned browser)
            # inherit the pipe handles and keep them open after the main
            # process exits.
            if sys.platform == "win32":
                stdout, stderr, returncode = await self._run_with_tempfiles(
                    command, cwd, env
                )
            else:
                stdout, stderr, returncode = await self._run_with_pipes(
                    command, cwd, env
                )
        except asyncio.TimeoutError:
            return f"Error: Command timed out after {self.timeout} seconds"
        except Exception as e:
            return f"Error executing command: {str(e)}"

        output_parts = []

        if stdout:
            output_parts.append(stdout)

        if stderr and stderr.strip():
            output_parts.append(f"STDERR:\n{stderr}")

        if returncode != 0:
            output_parts.append(f"\nExit code: {returncode}")

        result = "\n".join(output_parts) if output_parts else "(no output)"

        # Truncate very long output
        max_len = 10000
        if len(result) > max_len:
            result = result[:max_len] + f"\n... (truncated, {len(result) - max_len} more chars)"

        return result

    async def _run_with_pipes(
        self, command: str, cwd: str, env: dict[str, str]
    ) -> tuple[str, str, int | None]:
        """Run command using pipes for stdout/stderr (default on POSIX)."""
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=self.timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass
            raise
        stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
        return stdout, stderr, process.returncode

    async def _run_with_tempfiles(
        self, command: str, cwd: str, env: dict[str, str]
    ) -> tuple[str, str, int | None]:
        """Run command using temp files for stdout/stderr (Windows).

        On Windows, child processes inherit pipe handles.  If a long-lived
        grandchild (e.g. `agent-browser`) keeps the handles open,
        `process.communicate()` never returns.  Writing to temp files
        sidesteps the issue because we only `process.wait()` (which only
        waits for the direct child to exit) and then read the files.
        """
        fd_out = fd_err = None
        stdout_path = stderr_path = None
        try:
            fd_out, stdout_path = tempfile.mkstemp(prefix="nb_out_")
            fd_err, stderr_path = tempfile.mkstemp(prefix="nb_err_")

            process = await asyncio.create_subprocess_exec(
                "powershell", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass",
                "-Command", command,
                stdout=fd_out, stderr=fd_err,
                cwd=cwd, env=env,
            )
            # Close our copies so only the child holds the handles.
            os.close(fd_out)
            fd_out = None
            os.close(fd_err)
            fd_err = None

            try:
                await asyncio.wait_for(process.wait(), timeout=self.timeout)
            except asyncio.TimeoutError:
                process.kill()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
                raise

            stdout = self._decode_output(Path(stdout_path).read_bytes())
            stderr = self._decode_output(Path(stderr_path).read_bytes())
            return stdout, stderr, process.returncode
        finally:
            for fd in (fd_out, fd_err):
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
            for p in (stdout_path, stderr_path):
                if p is not None:
                    try:
                        os.unlink(p)
                    except OSError:
                        pass

    @staticmethod
    def _decode_output(data: bytes) -> str:
        """Decode bytes trying UTF-8 first, falling back to locale encoding."""
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode(locale.getpreferredencoding(False), errors="replace")

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
