"""Canonical event builder for Nanobot's two-layer event model.

Layer A (this module): Plain-dict canonical events emitted by the agent.
Layer B (nanobot/web/events.py): Pydantic validation + SSE projection.

This module lives in ``bus/`` so both ``agent/loop.py`` and ``web/streaming.py``
can import it without violating module boundary rules.

Every canonical event shares the same envelope::

    {
        "v": 1,
        "event_id": "evt_<hex>",
        "type": "<family>.<name>",
        "ts": "<ISO-8601 UTC>",
        "run_id": "...",
        "session_id": "...",
        "turn_id": "turn_00042",
        "actor": {"kind": "agent", "id": "<role>"},
        "seq": 127,
        "payload": {...}
    }
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _event_id() -> str:
    return "evt_" + uuid.uuid4().hex


@dataclass(slots=True)
class CanonicalEventBuilder:
    """Stateful builder that stamps canonical events with shared envelope fields.

    Create one instance per agent request and call the builder methods for each
    event that needs to be emitted.  The ``seq`` counter increments automatically.
    """

    run_id: str
    session_id: str
    turn_id: str  # e.g. "turn_00042"
    actor_id: str  # agent role name (e.g. "main", "web")
    _seq: int = field(default=0, init=False)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _envelope(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "v": 1,
            "event_id": _event_id(),
            "type": event_type,
            "ts": _now_iso(),
            "run_id": self.run_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "actor": {"kind": "agent", "id": self.actor_id},
            "seq": self._next_seq(),
            "payload": payload,
        }

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    def run_start(self) -> dict[str, Any]:
        """Emit before the agent loop starts processing."""
        return self._envelope("run.start", {})

    def run_end(self, input_tokens: int = 0, output_tokens: int = 0) -> dict[str, Any]:
        """Emit after the agent loop completes."""
        return self._envelope(
            "run.end",
            {
                "finish_reason": "stop",
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                },
            },
        )

    # ------------------------------------------------------------------
    # Message lifecycle
    # ------------------------------------------------------------------

    def message_start(self, message_id: str, role: str = "assistant") -> dict[str, Any]:
        """Emit at the start of an assistant message within this run."""
        return self._envelope(
            "message.start",
            {"message_id": message_id, "role": role},
        )

    def message_end(
        self,
        message_id: str,
        finish_reason: str = "stop",
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> dict[str, Any]:
        """Emit when an assistant message is complete."""
        return self._envelope(
            "message.end",
            {
                "message_id": message_id,
                "finish_reason": finish_reason,
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                },
            },
        )

    # ------------------------------------------------------------------
    # Message parts
    # ------------------------------------------------------------------

    def text_delta(self, text: str) -> dict[str, Any]:
        """Emit a streaming text delta (incremental content)."""
        return self._envelope(
            "message.part",
            {"part_type": "text", "text": text},
        )

    def text_flush(self, text: str) -> dict[str, Any]:
        """Emit a non-streaming text update (full cumulative content)."""
        return self._envelope(
            "message.part",
            {"part_type": "text_flush", "text": text},
        )

    # ------------------------------------------------------------------
    # Tool lifecycle
    # ------------------------------------------------------------------

    def tool_call(
        self,
        tool_call_id: str,
        tool_name: str,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        """Emit when the LLM selects a tool to invoke."""
        return self._envelope(
            "tool.call.start",
            {
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "args": args,
            },
        )

    def tool_result(
        self,
        tool_call_id: str,
        tool_name: str,
        result: str,
        *,
        is_error: bool = False,
    ) -> dict[str, Any]:
        """Emit when a tool execution completes."""
        return self._envelope(
            "tool.result",
            {
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "status": "error" if is_error else "success",
                "output": {"kind": "text", "text": result},
            },
        )

    # ------------------------------------------------------------------
    # Delegation lifecycle
    # ------------------------------------------------------------------

    def delegate_start(
        self,
        delegation_id: str,
        child_role: str,
        task_title: str = "",
    ) -> dict[str, Any]:
        """Emit when delegating work to a sub-agent."""
        return self._envelope(
            "agent.delegate.start",
            {
                "delegation_id": delegation_id,
                "parent_agent_id": self.actor_id,
                "child_agent_id": child_role,
                "task": {"title": task_title},
            },
        )

    def delegate_end(
        self,
        delegation_id: str,
        *,
        success: bool = True,
    ) -> dict[str, Any]:
        """Emit when a delegated sub-agent finishes."""
        return self._envelope(
            "agent.delegate.end",
            {
                "delegation_id": delegation_id,
                "status": "success" if success else "error",
            },
        )

    # ------------------------------------------------------------------
    # Status / metadata
    # ------------------------------------------------------------------

    def status(self, code: str, *, label: str = "", scope: str = "run") -> dict[str, Any]:
        """Emit a transient status badge (thinking, calling_tool, retrying, etc.)."""
        return self._envelope(
            "status",
            {"scope": scope, "code": code, "label": label},
        )

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def keepalive(self) -> dict[str, Any]:
        """Emit a keepalive heartbeat (transport layer hint)."""
        return self._envelope("keepalive", {"scope": "transport"})
