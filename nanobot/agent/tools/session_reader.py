"""Session reader tool for reading and chunking conversation history."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.utils.helpers import safe_filename


class SessionReaderTool(Tool):
    """Tool to read and filter conversation history from session files."""

    def __init__(self, sessions_dir: Path | None = None):
        self._sessions_dir = sessions_dir or Path.home() / ".nanobot" / "sessions"

    @property
    def name(self) -> str:
        return "session_reader"

    @property
    def description(self) -> str:
        return (
            "Read conversation messages from session files with filtering and chunking. "
            "Use 'list' action to see available sessions. "
            "Use 'stats' action to get message count and date range without content. "
            "Use 'read' action to read messages in chunks with optional filters."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "stats", "read"],
                    "description": "Action: 'list' available sessions, 'stats' for counts/dates, 'read' for messages"
                },
                "session_key": {
                    "type": "string",
                    "description": "Session key (e.g. 'telegram:12345'). Required for 'stats' and 'read'."
                },
                "offset": {
                    "type": "integer",
                    "description": "Start reading from this message number (0-indexed). Default: 0"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of messages to return. Default: 50, max: 200"
                },
                "roles": {
                    "type": "string",
                    "description": "Comma-separated roles to include: 'user,assistant' (default). Use 'all' for everything including tool calls."
                },
                "date_from": {
                    "type": "string",
                    "description": "Only messages from this date onwards (YYYY-MM-DD)"
                },
                "date_to": {
                    "type": "string",
                    "description": "Only messages up to this date (YYYY-MM-DD)"
                },
            },
            "required": ["action"]
        }

    async def execute(self, action: str, **kwargs: Any) -> str:
        try:
            if action == "list":
                return self._list_sessions()
            elif action == "stats":
                return self._get_stats(kwargs.get("session_key", ""))
            elif action == "read":
                return self._read_messages(**kwargs)
            else:
                return f"Error: Unknown action '{action}'. Use 'list', 'stats', or 'read'."
        except Exception as e:
            return f"Error: {str(e)}"

    def _get_session_path(self, key: str) -> Path:
        """Get the file path for a session key."""
        safe_key = safe_filename(key.replace(":", "_"))
        return self._sessions_dir / f"{safe_key}.jsonl"

    def _list_sessions(self) -> str:
        """List all available sessions with basic info."""
        if not self._sessions_dir.exists():
            return "No sessions directory found."

        sessions = []
        for path in sorted(self._sessions_dir.glob("*.jsonl")):
            try:
                msg_count = 0
                metadata = {}
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        data = json.loads(line)
                        if data.get("_type") == "metadata":
                            metadata = data
                        else:
                            msg_count += 1

                key = path.stem.replace("_", ":", 1)
                updated = metadata.get("updated_at", "unknown")
                sessions.append(f"- {key}: {msg_count} messages (updated: {updated})")
            except Exception:
                sessions.append(f"- {path.stem}: (error reading)")

        if not sessions:
            return "No sessions found."
        return "Available sessions:\n" + "\n".join(sessions)

    def _get_stats(self, session_key: str) -> str:
        """Get statistics about a session without loading message content."""
        if not session_key:
            return "Error: session_key is required for 'stats' action."

        path = self._get_session_path(session_key)
        if not path.exists():
            return f"Error: Session '{session_key}' not found."

        msg_count = 0
        first_ts = None
        last_ts = None
        role_counts: dict[str, int] = {}

        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                if data.get("_type") == "metadata":
                    continue

                msg_count += 1
                role = data.get("role", "unknown")
                role_counts[role] = role_counts.get(role, 0) + 1

                ts = data.get("timestamp")
                if ts:
                    if first_ts is None:
                        first_ts = ts
                    last_ts = ts

        roles_str = ", ".join(f"{r}: {c}" for r, c in sorted(role_counts.items()))
        return (
            f"Session: {session_key}\n"
            f"Total messages: {msg_count}\n"
            f"By role: {roles_str}\n"
            f"First message: {first_ts or 'unknown'}\n"
            f"Last message: {last_ts or 'unknown'}"
        )

    def _read_messages(self, **kwargs: Any) -> str:
        """Read messages from a session with filtering and chunking."""
        session_key = kwargs.get("session_key", "")
        if not session_key:
            return "Error: session_key is required for 'read' action."

        path = self._get_session_path(session_key)
        if not path.exists():
            return f"Error: Session '{session_key}' not found."

        offset = max(0, kwargs.get("offset", 0))
        limit = min(200, max(1, kwargs.get("limit", 50)))

        roles_str = kwargs.get("roles", "user,assistant")
        if roles_str == "all":
            filter_roles = None
        else:
            filter_roles = set(r.strip() for r in roles_str.split(","))

        date_from = self._parse_date(kwargs.get("date_from"))
        date_to = self._parse_date(kwargs.get("date_to"))

        # Read and filter messages
        messages = []
        total_count = 0
        skipped_by_filter = 0

        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                if data.get("_type") == "metadata":
                    continue

                total_count += 1
                role = data.get("role", "unknown")

                # Role filter
                if filter_roles and role not in filter_roles:
                    skipped_by_filter += 1
                    continue

                # Date filters
                ts = data.get("timestamp")
                if ts and (date_from or date_to):
                    try:
                        msg_date = datetime.fromisoformat(ts).date()
                        if date_from and msg_date < date_from:
                            skipped_by_filter += 1
                            continue
                        if date_to and msg_date > date_to:
                            skipped_by_filter += 1
                            continue
                    except (ValueError, TypeError):
                        pass

                messages.append(data)

        # Apply offset and limit
        chunk = messages[offset:offset + limit]
        remaining = len(messages) - offset - len(chunk)

        if not chunk:
            if offset > 0:
                return f"No messages at offset {offset}. Total filtered messages: {len(messages)} (of {total_count} total)."
            return f"No messages match the filters. Total messages in session: {total_count}."

        # Format output
        lines = [
            f"Messages {offset + 1}-{offset + len(chunk)} of {len(messages)} filtered ({total_count} total in session)",
            f"Remaining after this chunk: {max(0, remaining)}",
            "---"
        ]

        for i, msg in enumerate(chunk):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            ts = msg.get("timestamp", "")

            # Truncate very long messages
            if len(content) > 2000:
                content = content[:2000] + "... [truncated]"

            ts_short = ts[:16] if ts else ""  # YYYY-MM-DDTHH:MM
            lines.append(f"[{offset + i}] {ts_short} [{role}]: {content}")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _parse_date(date_str: str | None) -> "datetime.date | None":
        """Parse a YYYY-MM-DD date string."""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None
