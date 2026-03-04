"""Claude Code tool for managing Claude Code sessions via tmux."""

import json
import os
import random
import shutil
import string
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool

TMUX_SOCKET = "/tmp/nanobot-tmux-sockets/nanobot.sock"
SESSIONS_DIR = "claude-code"
SESSIONS_FILE = "sessions.json"


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _generate_id() -> str:
    now = datetime.now(timezone.utc)
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"cc-{now.strftime('%Y%m%d-%H%M%S')}-{rand}"


class ClaudeCodeTool(Tool):
    """Tool to create, list, and resume Claude Code sessions running in tmux."""

    def __init__(self, workspace: Path):
        self._workspace = workspace
        self._storage_dir = workspace / SESSIONS_DIR
        self._storage_file = self._storage_dir / SESSIONS_FILE
        self._channel = ""
        self._chat_id = ""

    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the current session context (stored in session metadata)."""
        self._channel = channel
        self._chat_id = chat_id

    @property
    def name(self) -> str:
        return "claude_code"

    @property
    def description(self) -> str:
        return (
            "Manage Claude Code sessions. Actions: "
            "create (start a new Claude Code session in tmux), "
            "list (show sessions filtered by status), "
            "resume (reconnect to an existing session), "
            "status (check health of a session and capture pane output), "
            "archive (mark session as archived and optionally kill tmux)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "list", "resume", "status", "archive"],
                    "description": "Action to perform",
                },
                "purpose": {
                    "type": "string",
                    "description": "Purpose/task description for the session (for create)",
                },
                "workspace_path": {
                    "type": "string",
                    "description": "Working directory for the Claude Code session (for create)",
                },
                "session_id": {
                    "type": "string",
                    "description": "Session ID or partial match (for resume)",
                },
                "status": {
                    "type": "string",
                    "enum": ["active", "detached", "archived", "all"],
                    "description": "Filter sessions by status (for list, default: all)",
                },
                "message": {
                    "type": "string",
                    "description": "Initial message/prompt to send to Claude Code (for create)",
                },
                "metadata": {
                    "type": "object",
                    "description": "Optional metadata to attach to the session",
                },
                "kill": {
                    "type": "boolean",
                    "description": "Kill the tmux session when archiving (for archive, default: false)",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str,
        purpose: str = "",
        workspace_path: str = "",
        session_id: str = "",
        status: str = "all",
        message: str = "",
        metadata: dict | None = None,
        kill: bool = False,
        **kwargs: Any,
    ) -> str:
        if action == "create":
            return self._create_session(purpose, workspace_path, message, metadata)
        elif action == "list":
            return self._list_sessions(status)
        elif action == "resume":
            return self._resume_session(session_id)
        elif action == "status":
            return self._status_session(session_id)
        elif action == "archive":
            return self._archive_session(session_id, kill)
        return f"Error: Unknown action '{action}'. Use create, list, resume, status, or archive."

    # ── Storage ──────────────────────────────────────────────────────

    def _load_sessions(self) -> list[dict[str, Any]]:
        if not self._storage_file.exists():
            return []
        try:
            data = json.loads(self._storage_file.read_text())
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def _save_sessions(self, sessions: list[dict[str, Any]]) -> None:
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._storage_file.write_text(json.dumps(sessions, indent=2))

    # ── Validation ────────────────────────────────────────────────────

    @staticmethod
    def _check_binary(name: str) -> str | None:
        """Return an error string if binary is not found, else None."""
        if shutil.which(name) is None:
            return f"Error: '{name}' is not installed or not in PATH"
        return None

    def _find_session(
        self, session_id: str, sessions: list[dict[str, Any]]
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Find a session by exact or fuzzy match. Returns (match, error_message)."""
        if not session_id:
            return None, "Error: session_id is required"
        if not sessions:
            return None, "Error: no sessions found"

        for s in sessions:
            if s["id"] == session_id:
                return s, None

        candidates = [
            s for s in sessions
            if session_id in s["id"] or session_id.lower() in s.get("purpose", "").lower()
        ]
        if len(candidates) == 1:
            return candidates[0], None
        if len(candidates) > 1:
            lines = ["Multiple sessions match. Please be more specific:"]
            for c in candidates:
                lines.append(f"  {c['id']} — {c['purpose']}")
            return None, "\n".join(lines)

        return None, f"Error: no session found matching '{session_id}'"

    # ── Tmux helpers ─────────────────────────────────────────────────

    @staticmethod
    def _ensure_tmux_socket_dir() -> None:
        socket_dir = os.path.dirname(TMUX_SOCKET)
        os.makedirs(socket_dir, exist_ok=True)

    @staticmethod
    def _tmux_session_exists(session_name: str) -> bool:
        try:
            result = subprocess.run(
                ["tmux", "-S", TMUX_SOCKET, "has-session", "-t", session_name],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    @staticmethod
    def _list_tmux_sessions() -> set[str]:
        try:
            result = subprocess.run(
                ["tmux", "-S", TMUX_SOCKET, "list-sessions", "-F", "#{session_name}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return set()
            return {line.strip() for line in result.stdout.splitlines() if line.strip()}
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return set()

    @staticmethod
    def _capture_pane(session_name: str, lines: int = 50) -> str | None:
        """Capture the last N lines of tmux pane output."""
        try:
            result = subprocess.run(
                [
                    "tmux", "-S", TMUX_SOCKET,
                    "capture-pane", "-p", "-J",
                    "-t", f"{session_name}:0.0",
                    "-S", str(-lines),
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.rstrip()
            return None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

    @staticmethod
    def _kill_tmux_session(session_name: str) -> bool:
        """Kill a tmux session. Returns True on success."""
        try:
            result = subprocess.run(
                ["tmux", "-S", TMUX_SOCKET, "kill-session", "-t", session_name],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    # ── Actions ──────────────────────────────────────────────────────

    def _create_session(
        self,
        purpose: str,
        workspace_path: str,
        message: str,
        metadata: dict | None,
    ) -> str:
        # Validate required binaries
        for binary in ("tmux", "claude"):
            if err := self._check_binary(binary):
                return err

        session_id = _generate_id()
        tmux_session_name = f"claude-{session_id}"

        work_dir = workspace_path or str(self._workspace)
        if not os.path.isdir(work_dir):
            return f"Error: workspace path does not exist: {work_dir}"

        self._ensure_tmux_socket_dir()

        # Create tmux session with a shell (not running claude directly)
        # This ensures the session persists even after claude exits
        try:
            # Step 1: Create tmux session with a shell
            subprocess.run(
                [
                    "tmux", "-S", TMUX_SOCKET,
                    "new-session", "-d",
                    "-s", tmux_session_name,
                    "-c", work_dir,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            return "Error: tmux session creation timed out"
        except FileNotFoundError:
            return "Error: tmux is not installed or not in PATH"

        # Step 2: Send the claude command to the shell
        claude_cmd = "claude"
        if message:
            # Use --message for non-interactive prompt
            escaped = message.replace("'", "'\\''")
            claude_cmd = f"claude --message '{escaped}'"

        try:
            # Send command as literal string
            subprocess.run(
                [
                    "tmux", "-S", TMUX_SOCKET,
                    "send-keys", "-t", f"{tmux_session_name}:0.0",
                    "-l", "--", claude_cmd,
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            # Send Enter to execute
            subprocess.run(
                [
                    "tmux", "-S", TMUX_SOCKET,
                    "send-keys", "-t", f"{tmux_session_name}:0.0",
                    "Enter",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            return "Error: sending command to tmux timed out"
        except FileNotFoundError:
            return "Error: tmux is not installed or not in PATH"

        if not self._tmux_session_exists(tmux_session_name):
            return "Error: failed to create tmux session"

        now = _now_ms()
        session_metadata = metadata or {}
        if self._channel:
            session_metadata["created_by_channel"] = self._channel
        if self._chat_id:
            session_metadata["created_by_chat_id"] = self._chat_id

        session_data = {
            "id": session_id,
            "purpose": purpose or "General session",
            "workspace_path": work_dir,
            "tmux_socket": TMUX_SOCKET,
            "tmux_session_name": tmux_session_name,
            "status": "active",
            "created_at_ms": now,
            "last_used_at_ms": now,
            "metadata": session_metadata,
        }

        sessions = self._load_sessions()
        sessions.append(session_data)
        self._save_sessions(sessions)

        lines = [
            f"Created Claude Code session: {session_id}",
            f"  Purpose: {session_data['purpose']}",
            f"  Workspace: {work_dir}",
            f"  tmux session: {tmux_session_name}",
            "",
            "To attach to this session:",
            f"  tmux -S {TMUX_SOCKET} attach -t {tmux_session_name}",
        ]
        return "\n".join(lines)

    def _list_sessions(self, status_filter: str) -> str:
        sessions = self._load_sessions()
        if not sessions:
            return "No Claude Code sessions found."

        # Sync status with tmux reality
        live_tmux = self._list_tmux_sessions()
        for s in sessions:
            if s["status"] == "active" and s["tmux_session_name"] not in live_tmux:
                s["status"] = "detached"
        self._save_sessions(sessions)

        if status_filter and status_filter != "all":
            sessions = [s for s in sessions if s["status"] == status_filter]

        if not sessions:
            return f"No sessions with status '{status_filter}'."

        # Sort by last_used_at_ms descending (most recent first)
        sessions.sort(key=lambda s: s.get("last_used_at_ms", 0), reverse=True)

        lines = ["Claude Code sessions:"]
        for s in sessions:
            created = datetime.fromtimestamp(
                s["created_at_ms"] / 1000, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M")
            lines.append(
                f"  [{s['status']}] {s['id']} — {s['purpose']} (created {created})"
            )
        return "\n".join(lines)

    def _resume_session(self, session_id: str) -> str:
        sessions = self._load_sessions()
        match, err = self._find_session(session_id, sessions)
        if err:
            return err

        if match["status"] == "archived":
            return (
                f"Error: session '{match['id']}' is archived. "
                f"Use create to start a new session."
            )

        tmux_name = match["tmux_session_name"]

        if not self._tmux_session_exists(tmux_name):
            match["status"] = "detached"
            self._save_sessions(sessions)
            return (
                f"Error: tmux session '{tmux_name}' is no longer running. "
                f"Session status updated to 'detached'. "
                f"Use create to start a new session."
            )

        # Update timestamp and status
        match["last_used_at_ms"] = _now_ms()
        match["status"] = "active"
        self._save_sessions(sessions)

        lines = [
            f"Session {match['id']} is active.",
            f"  Purpose: {match['purpose']}",
            f"  Workspace: {match['workspace_path']}",
            "",
            "To attach to this session:",
            f"  tmux -S {TMUX_SOCKET} attach -t {tmux_name}",
        ]
        return "\n".join(lines)

    def _status_session(self, session_id: str) -> str:
        sessions = self._load_sessions()
        match, err = self._find_session(session_id, sessions)
        if err:
            return err

        tmux_name = match["tmux_session_name"]
        alive = self._tmux_session_exists(tmux_name)

        # Update status based on tmux reality (but never un-archive)
        if match["status"] != "archived":
            if alive:
                match["status"] = "active"
                match["last_used_at_ms"] = _now_ms()
            elif match["status"] == "active":
                match["status"] = "detached"
        self._save_sessions(sessions)

        created = datetime.fromtimestamp(
            match["created_at_ms"] / 1000, tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M UTC")
        last_used = datetime.fromtimestamp(
            match["last_used_at_ms"] / 1000, tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M UTC")

        lines = [
            f"Session: {match['id']}",
            f"  Status: {match['status']}",
            f"  Purpose: {match['purpose']}",
            f"  Workspace: {match['workspace_path']}",
            f"  Created: {created}",
            f"  Last used: {last_used}",
            f"  tmux alive: {'yes' if alive else 'no'}",
        ]

        # Show creator metadata if present
        meta = match.get("metadata", {})
        if meta.get("created_by_channel"):
            lines.append(f"  Creator: {meta['created_by_channel']}")
            if meta.get("created_by_chat_id"):
                lines[-1] += f" (chat {meta['created_by_chat_id']})"

        if alive:
            pane_output = self._capture_pane(tmux_name)
            if pane_output:
                # Show last 20 non-empty lines
                recent = [ln for ln in pane_output.splitlines() if ln.strip()][-20:]
                lines.append("")
                lines.append("Recent output:")
                lines.extend(f"  {ln}" for ln in recent)

        return "\n".join(lines)

    def _archive_session(self, session_id: str, kill: bool) -> str:
        sessions = self._load_sessions()
        match, err = self._find_session(session_id, sessions)
        if err:
            return err

        if match["status"] == "archived":
            return f"Session {match['id']} is already archived."

        tmux_name = match["tmux_session_name"]

        if kill and self._tmux_session_exists(tmux_name):
            self._kill_tmux_session(tmux_name)

        match["status"] = "archived"
        match["last_used_at_ms"] = _now_ms()
        self._save_sessions(sessions)

        killed_msg = " (tmux session killed)" if kill else ""
        return f"Session {match['id']} archived{killed_msg}."
