"""Session management for conversation history."""

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.config.paths import get_legacy_sessions_dir
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
        self.legacy_sessions_dir = get_legacy_sessions_dir()
        self._cache: dict[str, Session] = {}

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

    def export_session(self, key: str, output_path: Path | None = None) -> Path:
        """
        Export a session to a JSON file.

        Args:
            key: Session key (channel:chat_id).
            output_path: Optional output path. Defaults to workspace/exports/<key>.json

        Returns:
            Path to the exported file.
        """
        session = self.get_or_create(key)

        # Determine output path
        target_path: Path
        if output_path is None:
            exports_dir = ensure_dir(self.workspace / "exports")
            safe_key = safe_filename(key.replace(":", "_"))
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            target_path = exports_dir / f"{safe_key}_{timestamp}.json"
        else:
            target_path = output_path

        export_data = {
            "version": 1,
            "exported_at": datetime.now().isoformat(),
            "session": {
                "key": session.key,
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "metadata": session.metadata,
                "last_consolidated": session.last_consolidated,
                "messages": session.messages
            }
        }

        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)

        return target_path

    def import_session(self, input_path: Path, target_key: str | None = None) -> Session:
        """
        Import a session from a JSON file.

        Args:
            input_path: Path to the exported JSON file.
            target_key: Optional new key for the session. Uses original if not provided.

        Returns:
            The imported session.
        """
        with open(input_path, encoding="utf-8") as f:
            export_data = json.load(f)

        session_data = export_data.get("session", {})
        key = target_key or session_data.get("key", f"imported:{datetime.now().timestamp()}")

        session = Session(
            key=key,
            messages=session_data.get("messages", []),
            metadata=session_data.get("metadata", {}),
            last_consolidated=session_data.get("last_consolidated", 0)
        )

        if "created_at" in session_data:
            session.created_at = datetime.fromisoformat(session_data["created_at"])

        self.save(session)
        self._cache[key] = session

        return session

    def search_sessions(self, query: str, case_sensitive: bool = False) -> list[dict[str, Any]]:
        """
        Search across all sessions for messages containing the query.

        Args:
            query: Search string.
            case_sensitive: Whether to match case.

        Returns:
            List of results with session key, message, and timestamp.
        """
        results = []
        query_cmp = query if case_sensitive else query.lower()

        for session_info in self.list_sessions():
            key = session_info["key"]
            session = self.get_or_create(key)

            for msg in session.messages:
                content = msg.get("content", "")
                if not isinstance(content, str):
                    continue

                content_cmp = content if case_sensitive else content.lower()

                if query_cmp in content_cmp:
                    results.append({
                        "session_key": key,
                        "role": msg.get("role", "unknown"),
                        "content": content[:200] + "..." if len(content) > 200 else content,
                        "timestamp": msg.get("timestamp", ""),
                        "full_message": msg
                    })

        return sorted(results, key=lambda x: x.get("timestamp", ""), reverse=True)

    def get_session_stats(self, key: str) -> dict[str, Any]:
        """
        Get statistics for a session.

        Args:
            key: Session key.

        Returns:
            Dictionary with message counts, tool usage, etc.
        """
        session = self.get_or_create(key)

        stats = {
            "key": key,
            "total_messages": len(session.messages),
            "user_messages": 0,
            "assistant_messages": 0,
            "tool_calls": 0,
            "tool_results": 0,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "unconsolidated_messages": len(session.messages) - session.last_consolidated
        }

        for msg in session.messages:
            role = msg.get("role", "")
            if role == "user":
                stats["user_messages"] += 1
            elif role == "assistant":
                stats["assistant_messages"] += 1

            if "tool_calls" in msg:
                stats["tool_calls"] += len(msg["tool_calls"])
            if "tool_call_id" in msg:
                stats["tool_results"] += 1

        return stats
