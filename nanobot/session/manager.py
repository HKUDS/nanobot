"""Session management for conversation history."""

import json
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
    """

    key: str  # channel:chat_id
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    saved_count: int = 0  # Number of messages already persisted to disk

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """Add a message to the session."""
        msg = {"role": role, "content": content, "timestamp": datetime.now().isoformat(), **kwargs}
        self.messages.append(msg)
        self.updated_at = datetime.now()

    def get_history(self, max_messages: int = 50) -> list[dict[str, Any]]:
        """
        Get message history for LLM context.

        Args:
            max_messages: Maximum messages to return.

        Returns:
            List of messages in LLM format.
        """
        # Get recent messages
        recent = (
            self.messages[-max_messages:] if len(self.messages) > max_messages else self.messages
        )

        # Convert to LLM format (just role and content)
        return [{"role": m["role"], "content": m["content"]} for m in recent]

    def clear(self) -> None:
        """Clear all messages in the session."""
        self.messages = []
        self.updated_at = datetime.now()
        # Keep saved_count so save() can detect history shrink and rewrite the file.


class SessionManager:
    """
    Manages conversation sessions.

    Sessions are stored as JSONL files in the sessions directory.
    """

    def __init__(
        self,
        workspace: Path,
        compact_threshold_messages: int = 400,
        compact_threshold_bytes: int = 2_000_000,
        compact_keep_messages: int = 300,
    ):
        self.workspace = workspace
        self.sessions_dir = ensure_dir(Path.home() / ".nanobot" / "sessions")
        self.compact_threshold_messages = max(1, compact_threshold_messages)
        self.compact_threshold_bytes = max(1, compact_threshold_bytes)
        self.compact_keep_messages = max(1, compact_keep_messages)
        self._cache: dict[str, Session] = {}

    def _get_session_path(self, key: str) -> Path:
        """Get the file path for a session."""
        safe_key = safe_filename(key.replace(":", "_"))
        return self.sessions_dir / f"{safe_key}.jsonl"

    def get_or_create(self, key: str) -> Session:
        """
        Get an existing session or create a new one.

        Args:
            key: Session key (usually channel:chat_id).

        Returns:
            The session.
        """
        # Check cache
        if key in self._cache:
            return self._cache[key]

        # Try to load from disk
        session = self._load(key)
        if session is None:
            session = Session(key=key)

        self._cache[key] = session
        return session

    def _load(self, key: str) -> Session | None:
        """Load a session from disk."""
        path = self._get_session_path(key)

        if not path.exists():
            return None

        try:
            messages = []
            metadata = {}
            created_at = None
            updated_at = None

            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    data = json.loads(line)

                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        created_at = (
                            datetime.fromisoformat(data["created_at"])
                            if data.get("created_at")
                            else None
                        )
                        updated_at = (
                            datetime.fromisoformat(data["updated_at"])
                            if data.get("updated_at")
                            else updated_at
                        )
                    else:
                        messages.append(data)
                        msg_ts = data.get("timestamp")
                        if msg_ts:
                            try:
                                updated_at = datetime.fromisoformat(msg_ts)
                            except Exception:
                                # Keep loading even if a single message timestamp is malformed.
                                pass

            return Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                updated_at=updated_at or created_at or datetime.now(),
                metadata=metadata,
                saved_count=len(messages),
            )
        except Exception as e:
            logger.warning(f"Failed to load session {key}: {e}")
            return None

    def save(self, session: Session) -> None:
        """Persist session changes using append-only writes."""
        path = self._get_session_path(session.key)
        path.parent.mkdir(parents=True, exist_ok=True)
        should_rewrite = not path.exists() or len(session.messages) < session.saved_count

        if should_rewrite:
            with open(path, "w", encoding="utf-8") as f:
                metadata_line = {
                    "_type": "metadata",
                    "created_at": session.created_at.isoformat(),
                    "updated_at": session.updated_at.isoformat(),
                    "metadata": session.metadata,
                }
                f.write(json.dumps(metadata_line, ensure_ascii=False) + "\n")
                for msg in session.messages:
                    f.write(json.dumps(msg, ensure_ascii=False) + "\n")
            session.saved_count = len(session.messages)
        else:
            new_messages = session.messages[session.saved_count :]
            if new_messages:
                with open(path, "a", encoding="utf-8") as f:
                    for msg in new_messages:
                        f.write(json.dumps(msg, ensure_ascii=False) + "\n")
                session.saved_count = len(session.messages)

        self._cache[session.key] = session
        self.compact_if_needed(session.key)

    def delete(self, key: str) -> bool:
        """
        Delete a session.

        Args:
            key: Session key.

        Returns:
            True if deleted, False if not found.
        """
        # Remove from cache
        self._cache.pop(key, None)

        # Remove file
        path = self._get_session_path(key)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_sessions(self) -> list[dict[str, Any]]:
        """
        List all sessions.

        Returns:
            List of session info dicts.
        """
        sessions = []

        for path in self.sessions_dir.glob("*.jsonl"):
            try:
                created_at = None
                with open(path, encoding="utf-8") as f:
                    first_line = f.readline().strip()
                    if first_line:
                        data = json.loads(first_line)
                        if data.get("_type") == "metadata":
                            created_at = data.get("created_at")
                updated_at = datetime.fromtimestamp(path.stat().st_mtime).isoformat()
                sessions.append(
                    {
                        "key": path.stem.replace("_", ":"),
                        "created_at": created_at,
                        "updated_at": updated_at,
                        "path": str(path),
                    }
                )
            except Exception:
                continue

        return sorted(sessions, key=lambda x: x.get("updated_at", ""), reverse=True)

    def compact_if_needed(self, key: str) -> bool:
        """
        Compact a session file if it exceeds thresholds.

        Returns:
            True if compacted, False otherwise.
        """
        session = self.get_or_create(key)
        path = self._get_session_path(key)
        if not path.exists():
            return False

        by_message_count = len(session.messages) >= self.compact_threshold_messages
        by_file_size = path.stat().st_size >= self.compact_threshold_bytes
        if not by_message_count and not by_file_size:
            return False

        return self.compact(key)

    def compact(self, key: str) -> bool:
        """
        Compact a session by rewriting with recent messages only.

        Returns:
            True if compacted, False if session file does not exist.
        """
        path = self._get_session_path(key)
        if not path.exists():
            return False

        session = self.get_or_create(key)
        if len(session.messages) > self.compact_keep_messages:
            session.messages = session.messages[-self.compact_keep_messages :]

        session.saved_count = len(session.messages)
        session.updated_at = datetime.now()

        with open(path, "w", encoding="utf-8") as f:
            metadata_line = {
                "_type": "metadata",
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "metadata": session.metadata,
            }
            f.write(json.dumps(metadata_line, ensure_ascii=False) + "\n")
            for msg in session.messages:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")

        self._cache[key] = session
        return True

    def compact_all(self) -> int:
        """Compact all existing session files and return compacted count."""
        compacted = 0
        for info in self.list_sessions():
            if self.compact(info["key"]):
                compacted += 1
        return compacted
