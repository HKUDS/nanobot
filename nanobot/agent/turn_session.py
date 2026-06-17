"""Turn-scoped session metadata coordination."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from nanobot.session.manager import Session, SessionManager


class TurnSessionCoordinator:
    """Owns in-flight turn metadata stored on a session."""

    RUNTIME_CHECKPOINT_KEY = "runtime_checkpoint"
    PENDING_USER_TURN_KEY = "pending_user_turn"

    def __init__(self, sessions: SessionManager | None) -> None:
        self._sessions = sessions

    def set_runtime_checkpoint(self, session: Session, payload: dict[str, Any]) -> None:
        """Persist the latest in-flight turn state into session metadata."""
        session.metadata[self.RUNTIME_CHECKPOINT_KEY] = payload
        if self._sessions is not None:
            self._sessions.save(session)

    def mark_pending_user_turn(self, session: Session) -> None:
        session.metadata[self.PENDING_USER_TURN_KEY] = True

    def clear_pending_user_turn(self, session: Session) -> None:
        session.metadata.pop(self.PENDING_USER_TURN_KEY, None)

    def clear_runtime_checkpoint(self, session: Session) -> None:
        session.metadata.pop(self.RUNTIME_CHECKPOINT_KEY, None)

    @staticmethod
    def checkpoint_message_key(message: dict[str, Any]) -> tuple[Any, ...]:
        return (
            message.get("role"),
            message.get("content"),
            message.get("tool_call_id"),
            message.get("name"),
            message.get("tool_calls"),
            message.get("reasoning_content"),
            message.get("thinking_blocks"),
        )

    def restore_runtime_checkpoint(self, session: Session) -> bool:
        """Materialize an unfinished turn into session history before a new request."""
        checkpoint = session.metadata.get(self.RUNTIME_CHECKPOINT_KEY)
        if not isinstance(checkpoint, dict):
            return False

        assistant_message = checkpoint.get("assistant_message")
        completed_tool_results = checkpoint.get("completed_tool_results") or []
        pending_tool_calls = checkpoint.get("pending_tool_calls") or []

        restored_messages: list[dict[str, Any]] = []
        if isinstance(assistant_message, dict):
            restored = dict(assistant_message)
            restored.setdefault("timestamp", datetime.now().isoformat())
            restored_messages.append(restored)
        for message in completed_tool_results:
            if isinstance(message, dict):
                restored = dict(message)
                restored.setdefault("timestamp", datetime.now().isoformat())
                restored_messages.append(restored)
        for tool_call in pending_tool_calls:
            if not isinstance(tool_call, dict):
                continue
            tool_id = tool_call.get("id")
            name = ((tool_call.get("function") or {}).get("name")) or "tool"
            restored_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "name": name,
                    "content": "Error: Task interrupted before this tool finished.",
                    "timestamp": datetime.now().isoformat(),
                }
            )

        overlap = 0
        max_overlap = min(len(session.messages), len(restored_messages))
        for size in range(max_overlap, 0, -1):
            existing = session.messages[-size:]
            restored = restored_messages[:size]
            if all(
                self.checkpoint_message_key(left) == self.checkpoint_message_key(right)
                for left, right in zip(existing, restored)
            ):
                overlap = size
                break
        session.messages.extend(restored_messages[overlap:])

        self.clear_pending_user_turn(session)
        self.clear_runtime_checkpoint(session)
        return True

    def restore_pending_user_turn(self, session: Session) -> bool:
        """Close a turn that only persisted the user message before crashing."""
        if not session.metadata.get(self.PENDING_USER_TURN_KEY):
            return False

        if session.messages and session.messages[-1].get("role") == "user":
            session.messages.append(
                {
                    "role": "assistant",
                    "content": "Error: Task interrupted before a response was generated.",
                    "timestamp": datetime.now().isoformat(),
                }
            )
            session.updated_at = datetime.now()

        self.clear_pending_user_turn(session)
        return True
