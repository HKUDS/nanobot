"""Tmux session management tool."""

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool

SOCKET_DIR = Path(tempfile.gettempdir()) / "nanobot-tmux-sockets"
SOCKET_PATH = SOCKET_DIR / "nanobot.sock"


class TmuxTool(Tool):
    """Tool to manage persistent tmux shell sessions."""

    @property
    def name(self) -> str:
        return "tmux"

    @property
    def description(self) -> str:
        return (
            "Manage persistent tmux shell sessions. "
            "Create long-running sessions, send commands, and read output."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "send", "read", "list", "kill"],
                    "description": "The tmux action to perform",
                },
                "session_name": {
                    "type": "string",
                    "description": ("Session name (required for create/send/read/kill)"),
                },
                "command": {
                    "type": "string",
                    "description": ("Command to send (required for send action)"),
                },
                "lines": {
                    "type": "integer",
                    "description": ("Number of lines to capture (default 50, for read action)"),
                },
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs: Any) -> str:
        action: str = kwargs.get("action", "")
        session_name: str | None = kwargs.get("session_name")
        command: str | None = kwargs.get("command")
        lines: int = kwargs.get("lines", 50)

        if not shutil.which("tmux"):
            return "Error: tmux is not installed or not found on PATH"

        try:
            SOCKET_DIR.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return f"Error: Failed to create socket directory: {e}"

        if action == "create":
            return await self._create(session_name)
        elif action == "send":
            return await self._send(session_name, command)
        elif action == "read":
            return await self._read(session_name, lines)
        elif action == "list":
            return await self._list()
        elif action == "kill":
            return await self._kill(session_name)
        else:
            return f"Error: Unknown action '{action}'"

    async def _create(self, session_name: str | None) -> str:
        if not session_name:
            return "Error: session_name is required for create action"

        result = await self._run_tmux("new-session", "-d", "-s", session_name)
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            return f"Error: Failed to create session '{session_name}': {stderr}"

        logger.debug("tmux session '{}' created via socket {}", session_name, SOCKET_PATH)
        return f"Session '{session_name}' created"

    async def _send(self, session_name: str | None, command: str | None) -> str:
        if not session_name:
            return "Error: session_name is required for send action"
        if not command:
            return "Error: command is required for send action"

        result = await self._run_tmux("send-keys", "-t", session_name, command, "Enter")
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            return f"Error: Failed to send command to '{session_name}': {stderr}"

        return f"Command sent to session '{session_name}'"

    async def _read(self, session_name: str | None, lines: int) -> str:
        if not session_name:
            return "Error: session_name is required for read action"

        result = await self._run_tmux("capture-pane", "-t", session_name, "-p", "-S", f"-{lines}")
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            return f"Error: Failed to read session '{session_name}': {stderr}"

        output = result.stdout.decode("utf-8", errors="replace")
        return output.strip() if output.strip() else "(no output)"

    async def _list(self) -> str:
        result = await self._run_tmux("list-sessions")
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            if "no server running" in stderr or "no sessions" in stderr:
                return "No active sessions"
            return f"Error: Failed to list sessions: {stderr}"

        output = result.stdout.decode("utf-8", errors="replace")
        return output.strip() if output.strip() else "No active sessions"

    async def _kill(self, session_name: str | None) -> str:
        if not session_name:
            return "Error: session_name is required for kill action"

        result = await self._run_tmux("kill-session", "-t", session_name)
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            return f"Error: Failed to kill session '{session_name}': {stderr}"

        logger.debug("tmux session '{}' killed", session_name)
        return f"Session '{session_name}' killed"

    async def _run_tmux(self, *args: str) -> "_TmuxResult":
        """Run a tmux command with the dedicated nanobot socket."""
        process = await asyncio.create_subprocess_exec(
            "tmux",
            "-S",
            str(SOCKET_PATH),
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        return _TmuxResult(
            returncode=process.returncode or 0,
            stdout=stdout or b"",
            stderr=stderr or b"",
        )


class _TmuxResult:
    """Simple container for tmux subprocess results."""

    __slots__ = ("returncode", "stdout", "stderr")

    def __init__(self, returncode: int, stdout: bytes, stderr: bytes) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
