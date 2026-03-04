"""Session management for conversation history."""

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.utils.helpers import ensure_dir, safe_filename


@dataclass
class Session:
    """
    A conversation session.

    Stores messages in JSONL format for easy reading and persistence.

    Important: Messages are append-only for LLM cache efficiency.
    The consolidation process writes summaries to MEMORY.md/HISTORY.md
    but does NOT modify the messages list or get_history() output.
    """

    key: str  # channel:chat_id
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_consolidated: int = 0  # Number of messages already consolidated to files

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """Add a message to the session."""
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            **kwargs
        }
        self.messages.append(msg)
        self.updated_at = datetime.now()

    def get_history(self, max_messages: int = 500) -> list[dict[str, Any]]:
        """Return unconsolidated messages for LLM input, aligned to a user turn."""
        unconsolidated = self.messages[self.last_consolidated:]
        sliced = unconsolidated[-max_messages:]

        # Drop leading non-user messages to avoid orphaned tool_result blocks
        for i, m in enumerate(sliced):
            if m.get("role") == "user":
                sliced = sliced[i:]
                break

        out: list[dict[str, Any]] = []
        for m in sliced:
            entry: dict[str, Any] = {"role": m["role"], "content": m.get("content", "")}
            for k in ("tool_calls", "tool_call_id", "name"):
                if k in m:
                    entry[k] = m[k]
            out.append(entry)
        return out

    def clear(self) -> None:
        """Clear all messages and reset session to initial state."""
        self.messages = []
        self.last_consolidated = 0
        self.updated_at = datetime.now()


class SessionManager:
    """
    Manages conversation sessions.

    Sessions are stored as JSONL files in the sessions directory.
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.sessions_dir = ensure_dir(self.workspace / "sessions")
        self.legacy_sessions_dir = Path.home() / ".nanobot" / "sessions"
        self._cache: dict[str, Session] = {}
        self._active_sessions_file = self.workspace / "active_sessions.json"
        self._active_sessions: dict[str, str] = {}  # "channel:chat_id" -> "suffix" (empty = default)
        self._load_active_sessions()

    def _load_active_sessions(self) -> None:
        """Load active session tracking from disk."""
        if self._active_sessions_file.exists():
            try:
                with open(self._active_sessions_file, encoding="utf-8") as f:
                    self._active_sessions = json.load(f)
            except Exception:
                self._active_sessions = {}

    def _save_active_sessions(self) -> None:
        """Save active session tracking to disk."""
        try:
            with open(self._active_sessions_file, "w", encoding="utf-8") as f:
                json.dump(self._active_sessions, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get_active_session_key(self, channel: str, chat_id: str) -> str:
        """
        Get the active session key for a user.

        Returns the full session key including suffix if set.
        """
        base_key = f"{channel}:{chat_id}"
        suffix = self._active_sessions.get(base_key, "")
        if suffix:
            return f"{base_key}:{suffix}"
        return base_key

    def set_active_session(self, channel: str, chat_id: str, suffix: str | None) -> str:
        """
        Set the active session for a user.

        Args:
            suffix: Session suffix (e.g., "work"), or None/empty for default session.

        Returns:
            The full session key that was activated.
        """
        base_key = f"{channel}:{chat_id}"
        if suffix:
            self._active_sessions[base_key] = suffix
            full_key = f"{base_key}:{suffix}"
        else:
            self._active_sessions.pop(base_key, None)
            full_key = base_key
        self._save_active_sessions()
        return full_key

    def _get_session_path(self, key: str) -> Path:
        """Get the file path for a session."""
        safe_key = safe_filename(key.replace(":", "_"))
        return self.sessions_dir / f"{safe_key}.jsonl"

    def _get_legacy_session_path(self, key: str) -> Path:
        """Legacy global session path (~/.nanobot/sessions/)."""
        safe_key = safe_filename(key.replace(":", "_"))
        return self.legacy_sessions_dir / f"{safe_key}.jsonl"

    def get_or_create(self, key: str) -> Session:
        """
        Get an existing session or create a new one.

        Args:
            key: Session key (usually channel:chat_id).

        Returns:
            The session.
        """
        if key in self._cache:
            return self._cache[key]

        session = self._load(key)
        if session is None:
            session = Session(key=key)

        self._cache[key] = session
        return session

    def _load(self, key: str) -> Session | None:
        """Load a session from disk."""
        path = self._get_session_path(key)
        if not path.exists():
            legacy_path = self._get_legacy_session_path(key)
            if legacy_path.exists():
                try:
                    shutil.move(str(legacy_path), str(path))
                    logger.info("Migrated session {} from legacy path", key)
                except Exception:
                    logger.exception("Failed to migrate session {}", key)

        if not path.exists():
            return None

        try:
            messages = []
            metadata = {}
            created_at = None
            last_consolidated = 0

            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    data = json.loads(line)

                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        created_at = datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None
                        last_consolidated = data.get("last_consolidated", 0)
                    else:
                        messages.append(data)

            return Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                metadata=metadata,
                last_consolidated=last_consolidated
            )
        except Exception as e:
            logger.warning("Failed to load session {}: {}", key, e)
            return None

    def save(self, session: Session) -> None:
        """Save a session to disk."""
        path = self._get_session_path(session.key)

        with open(path, "w", encoding="utf-8") as f:
            metadata_line = {
                "_type": "metadata",
                "key": session.key,
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "metadata": session.metadata,
                "last_consolidated": session.last_consolidated
            }
            f.write(json.dumps(metadata_line, ensure_ascii=False) + "\n")
            for msg in session.messages:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")

        self._cache[session.key] = session

    def invalidate(self, key: str) -> None:
        """Remove a session from the in-memory cache."""
        self._cache.pop(key, None)

    def list_sessions(self) -> list[dict[str, Any]]:
        """
        List all sessions.

        Returns:
            List of session info dicts.
        """
        sessions = []

        for path in self.sessions_dir.glob("*.jsonl"):
            try:
                # Read just the metadata line
                with open(path, encoding="utf-8") as f:
                    first_line = f.readline().strip()
                    if first_line:
                        data = json.loads(first_line)
                        if data.get("_type") == "metadata":
                            key = data.get("key") or path.stem.replace("_", ":", 1)
                            sessions.append({
                                "key": key,
                                "created_at": data.get("created_at"),
                                "updated_at": data.get("updated_at"),
                                "path": str(path)
                            })
            except Exception:
                continue

        return sorted(sessions, key=lambda x: x.get("updated_at", ""), reverse=True)

    def get_session_metadata(self, key: str) -> dict[str, Any] | None:
        """
        Get session metadata including message count and last message preview.

        Returns dict with: key, created_at, updated_at, message_count, last_message_preview
        Returns None if session not found.
        """
        path = self._get_session_path(key)
        if not path.exists():
            return None

        try:
            message_count = 0
            last_content = None
            created_at = None
            updated_at = None

            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("_type") == "metadata":
                        created_at = data.get("created_at")
                        updated_at = data.get("updated_at")
                    else:
                        message_count += 1
                        if data.get("content"):
                            last_content = data["content"]

            # Truncate preview
            preview = None
            if last_content and isinstance(last_content, str):
                preview = last_content.replace("\n", " ").strip()[:80]
                if len(last_content) > 80:
                    preview += "..."

            return {
                "key": key,
                "created_at": created_at,
                "updated_at": updated_at,
                "message_count": message_count,
                "last_message_preview": preview,
            }
        except Exception:
            return None

    def list_user_sessions(self, channel: str, chat_id: str) -> list[dict[str, Any]]:
        """
        List all sessions for a specific user (channel:chat_id prefix).

        This finds sessions matching:
        - channel:chat_id (default session)
        - channel:chat_id:<suffix> (named sessions)

        Returns:
            List of session info dicts, sorted by updated_at desc.
        """
        prefix = f"{channel}:{chat_id}"
        all_sessions = self.list_sessions()

        user_sessions = []
        for s in all_sessions:
            key = s["key"]
            # Match exact prefix or prefix with ":suffix"
            if key == prefix or key.startswith(f"{prefix}:"):
                metadata = self.get_session_metadata(key)
                if metadata:
                    # Extract suffix for display
                    if key == prefix:
                        suffix = "default"
                    else:
                        suffix = key[len(prefix) + 1:]  # Remove "channel:chat_id:"
                    user_sessions.append({
                        **metadata,
                        "suffix": suffix,
                    })

        return sorted(user_sessions, key=lambda x: x.get("updated_at", ""), reverse=True)
