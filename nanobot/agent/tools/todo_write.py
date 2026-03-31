"""Structured todo state tool with progress updates."""

from __future__ import annotations

import asyncio
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.bus.events import OutboundMessage


class TodoWriteTool(Tool):
    """Maintain per-session todo list and emit compact progress updates."""

    name = "todo_write"
    description = (
        "Update a structured todo list with statuses pending/in_progress/completed/cancelled. "
        "Use for complex tasks to keep plan state explicit."
    )
    parameters = {
        "type": "object",
        "properties": {
            "merge": {
                "type": "boolean",
                "description": "If true, merge by todo id; if false, replace list.",
            },
            "todos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "content": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed", "cancelled"],
                        },
                    },
                    "required": ["id", "content", "status"],
                },
                "minItems": 1,
            },
        },
        "required": ["merge", "todos"],
    }

    def __init__(self, send_callback=None):
        self._send_callback = send_callback
        self._channel = "cli"
        self._chat_id = "direct"
        self._state: dict[str, list[dict[str, str]]] = {}

    def set_context(self, channel: str, chat_id: str, message_id: int | None = None) -> None:
        self._channel = channel
        self._chat_id = chat_id

    @property
    def _key(self) -> str:
        return f"{self._channel}:{self._chat_id}"

    @staticmethod
    def _validate_single_in_progress(todos: list[dict[str, str]]) -> str | None:
        n = sum(1 for t in todos if t.get("status") == "in_progress")
        if n > 1:
            return "Error: only one todo can be in_progress at a time."
        return None

    @staticmethod
    def _render(todos: list[dict[str, str]]) -> str:
        icon = {
            "pending": "⬜",
            "in_progress": "🔄",
            "completed": "✅",
            "cancelled": "❌",
        }
        lines = ["Plan status:"]
        for t in todos:
            lines.append(f"{icon.get(t['status'], '•')} [{t['id']}] {t['content']}")
        return "\n".join(lines)

    async def execute(self, merge: bool, todos: list[dict[str, Any]], **kwargs: Any) -> str:
        normalized = [
            {
                "id": str(t.get("id", "")).strip(),
                "content": str(t.get("content", "")).strip(),
                "status": str(t.get("status", "")).strip(),
            }
            for t in todos
        ]
        for t in normalized:
            if not t["id"] or not t["content"]:
                return "Error: each todo requires non-empty id and content."
            if t["status"] not in {"pending", "in_progress", "completed", "cancelled"}:
                return f"Error: invalid status '{t['status']}' for todo '{t['id']}'."

        current = self._state.get(self._key, [])
        if merge:
            by_id = {t["id"]: dict(t) for t in current}
            for t in normalized:
                by_id[t["id"]] = t
            updated = list(by_id.values())
        else:
            updated = normalized

        err = self._validate_single_in_progress(updated)
        if err:
            return err

        self._state[self._key] = updated
        rendered = self._render(updated)

        if self._send_callback:
            msg = OutboundMessage(
                channel=self._channel,
                chat_id=self._chat_id,
                content=rendered,
                metadata={
                    "_progress": True,
                    "_progress_kind": "todo",
                    "_progress_update": True,
                },
            )
            try:
                maybe = self._send_callback(msg)
                if asyncio.iscoroutine(maybe):
                    await maybe
            except Exception:
                pass
        return rendered

