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

    def get_history_by_channel(self, channel_id: str, max_messages: int = 500) -> list[dict[str, Any]]:
        """Return history prioritising messages from *channel_id*.

        Messages that originated in *channel_id* (tagged via ``_channel_id``)
        are included in full.  Consecutive runs of messages from other channels
        are compacted into a brief summary so the LLM stays on-topic while
        retaining cross-channel awareness.

        Tool-call chains are kept intact by grouping messages into "turns"
        (each starting with a user message).
        """
        unconsolidated = self.messages[self.last_consolidated:]
        sliced = unconsolidated[-max_messages:]

        # Drop leading non-user messages to avoid orphaned tool_result blocks
        for i, m in enumerate(sliced):
            if m.get("role") == "user":
                sliced = sliced[i:]
                break

        # ── Group messages into turns (user msg → assistant/tool responses) ──
        turns: list[tuple[str | None, list[dict[str, Any]]]] = []
        current_turn: list[dict[str, Any]] = []
        current_ch: str | None = None

        for m in sliced:
            if m.get("role") == "user":
                if current_turn:
                    turns.append((current_ch, current_turn))
                current_turn = [m]
                current_ch = m.get("_channel_id")
            else:
                current_turn.append(m)
        if current_turn:
            turns.append((current_ch, current_turn))

        # ── Build output with full turns for current channel, summaries for others ──
        out: list[dict[str, Any]] = []
        cross_buffer: list[tuple[str | None, list[dict[str, Any]]]] = []

        def _flush_cross() -> None:
            if not cross_buffer:
                return
            summary = _summarize_cross_channel_turns(cross_buffer)
            out.append({"role": "user", "content": summary})
            cross_buffer.clear()

        for turn_ch, turn_msgs in turns:
            if turn_ch is None or turn_ch == channel_id:
                _flush_cross()
                for m in turn_msgs:
                    entry: dict[str, Any] = {"role": m["role"], "content": m.get("content", "")}
                    for k in ("tool_calls", "tool_call_id", "name"):
                        if k in m:
                            entry[k] = m[k]
                    out.append(entry)
            else:
                cross_buffer.append((turn_ch, turn_msgs))

        _flush_cross()
        return out

    def clear(self) -> None:
        """Clear all messages and reset session to initial state."""
        self.messages = []
        self.last_consolidated = 0
        self.updated_at = datetime.now()


def _summarize_cross_channel_turns(
    turns: list[tuple[str | None, list[dict[str, Any]]]],
) -> str:
    """Compact consecutive cross-channel turns into a brief summary string.

    Groups messages by source channel and keeps only the last few user/assistant
    snippets per channel so the LLM retains awareness without context bloat.
    """
    by_channel: dict[str, list[str]] = {}
    for ch, msgs in turns:
        label = ch or "unknown"
        for m in msgs:
            content = m.get("content", "")
            if not content or m.get("role") not in ("user", "assistant"):
                continue
            snippet = content[:120] + "…" if len(content) > 120 else content
            by_channel.setdefault(label, []).append(f"[{m['role']}]: {snippet}")

    parts = ["[Cross-channel context — other channel activity]"]
    for ch, snippets in by_channel.items():
        parts.append(f"  #{ch} ({len(snippets)} message(s)):")
        # Keep only the last 3 snippets per channel to limit size
        for s in snippets[-3:]:
            parts.append(f"    {s}")
    return "\n".join(parts)


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
