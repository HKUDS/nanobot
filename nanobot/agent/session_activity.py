"""Retain runner activity on Session messages without changing model input."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.bus.outbound_events import ProgressEvent
from nanobot.events import AgentEvent


class SessionActivity(AgentHook):
    """Associate shared progress events with the response that produced them."""

    def __init__(self) -> None:
        super().__init__()
        self._messages: list[dict[str, Any]] = []
        self._iteration_start = 0
        self._current: list[ProgressEvent] | None = None
        self._pending: list[ProgressEvent] = []
        self._responses: dict[int, list[ProgressEvent]] = {}

    async def before_iteration(self, context: AgentHookContext) -> None:
        self._messages = context.messages
        self._iteration_start = len(context.messages)
        self._current = None
        self._pending = []

    def _bind_response(self) -> None:
        if self._current is None:
            response = next((message for message in self._messages[self._iteration_start:]
                             if message.get("role") == "assistant"), None)
            if response is not None:
                self._current = self._responses.setdefault(id(response), [])
                self._current.extend(self._pending)
                self._pending = []

    def remember(self, event: AgentEvent) -> bool:
        """Keep structured tool/file activity, including its actual error phase."""
        if not isinstance(event, ProgressEvent) or not (event.tool_events or event.file_edit_events):
            return False
        self._bind_response()
        target = self._current if self._current is not None else self._pending
        target.append(deepcopy(event))
        return True

    def transcript(self, messages: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        """Add display fields only to detached copies, never provider messages."""
        self._bind_response()
        rows: list[dict[str, Any]] = []
        for message in self._messages if messages is None else messages:
            if message.get("role") == "system":
                continue
            row = deepcopy(message)
            row.update(self._fields(self._responses.get(id(message), [])))
            rows.append(row)
        # Provider-hosted tools may emit activity before the response exists.
        # An empty display row is omitted by Session.get_history() on replay.
        if self._pending:
            rows.append({"role": "assistant", "content": "", **self._fields(self._pending)})
        return rows

    @staticmethod
    def _fields(events: list[ProgressEvent]) -> dict[str, Any]:
        tools = list({tool["call_id"]: tool for event in events
                      for tool in event.tool_events or []}.values())
        edits = list({(edit["call_id"], edit["path"]): edit for event in events
                      for edit in event.file_edit_events or []}.values())
        return {key: deepcopy(value) for key, value in (
            ("tool_events", tools), ("file_edit_events", edits),
        ) if value}
