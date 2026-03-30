"""Canonical event schema and SSE projection for the web layer.

This module defines:

* ``NanobotEvent`` — Pydantic model for validating canonical events produced by
  ``nanobot.bus.canonical.CanonicalEventBuilder``.

* ``project_to_sse`` — translates a canonical event dict into zero or more
  ui-message-stream SSE strings.  All semantics live here; the SSE writer in
  ``streaming.py`` is a "dumb projection" that just delegates to this function.

Projection table
----------------
=====================================  ==========================================
Canonical type                         SSE output
=====================================  ==========================================
``message.part`` (part_type=text)      text-start (if not open) + text-delta
``message.part`` (part_type=text_flush) same dedup logic as legacy streaming path
``tool.call.start``                    text-end (if open) + tool-call-start
                                       + tool-call-delta + tool-call-end
``tool.result``                        tool-result
``run.end``                            stored in *text_state* for later ``finish``
``run.start`` / ``keepalive``          silently skipped (handled at transport layer)
=====================================  ==========================================
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Pydantic model
# ---------------------------------------------------------------------------


class ActorInfo(BaseModel):
    kind: str  # "agent" | "tool"
    id: str  # role name


class NanobotEvent(BaseModel):
    """Canonical event envelope emitted by CanonicalEventBuilder."""

    v: int
    event_id: str
    type: str
    ts: str
    run_id: str
    session_id: str
    turn_id: str
    actor: ActorInfo
    seq: int
    payload: dict[str, Any]


# ---------------------------------------------------------------------------
# SSE helpers (mirrors nanobot/web/streaming.py — kept here for cohesion)
# ---------------------------------------------------------------------------


def _sse(payload: dict[str, object]) -> str:
    return f"event: message\ndata: {json.dumps(payload)}\n\n"


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------


def project_to_sse(event_dict: dict[str, Any], *, text_state: dict[str, Any]) -> list[str]:
    """Translate a canonical event dict into zero or more SSE strings.

    *text_state* is a mutable dict shared across calls for one stream.  It must
    contain at minimum::

        {"text_started": bool, "streamed_text": str, "run_end_usage": dict | None}

    The caller is responsible for initialising and threading this state.
    """
    event_type: str = event_dict.get("type", "")
    payload: dict[str, Any] = event_dict.get("payload", {})
    chunks: list[str] = []

    if event_type == "message.part":
        part_type = payload.get("part_type", "text")
        text: str = payload.get("text", "")

        if part_type == "text" and text:
            # Streaming delta — text is already the incremental delta.
            if not text_state["text_started"]:
                chunks.append(_sse({"type": "text-start"}))
                text_state["text_started"] = True
            chunks.append(_sse({"type": "text-delta", "textDelta": text}))
            text_state["streamed_text"] += text

        elif part_type == "text_flush" and text:
            # Non-streaming flush — text is cumulative; deduplicate.
            already = text_state["streamed_text"]
            if already and text.startswith(already):
                delta = text[len(already) :]
                if delta:
                    if not text_state["text_started"]:
                        chunks.append(_sse({"type": "text-start"}))
                        text_state["text_started"] = True
                    chunks.append(_sse({"type": "text-delta", "textDelta": delta}))
                    text_state["streamed_text"] = text
            elif already and already.startswith(text):
                pass  # subset already sent
            elif text:
                if not text_state["text_started"]:
                    chunks.append(_sse({"type": "text-start"}))
                    text_state["text_started"] = True
                chunks.append(_sse({"type": "text-delta", "textDelta": text}))
                text_state["streamed_text"] = text

    elif event_type == "tool.call.start":
        # Close any open text segment before tool boundary.
        if text_state["text_started"]:
            chunks.append(_sse({"type": "text-end"}))
            text_state["text_started"] = False
        text_state["streamed_text"] = ""

        call_id: str = payload.get("tool_call_id", "")
        tool_name: str = payload.get("tool_name", "")
        args: dict[str, Any] = payload.get("args", {})

        chunks.append(
            _sse({"type": "tool-call-start", "toolCallId": call_id, "toolName": tool_name})
        )
        chunks.append(
            _sse({"type": "tool-call-delta", "toolCallId": call_id, "argsText": json.dumps(args)})
        )
        chunks.append(_sse({"type": "tool-call-end", "toolCallId": call_id}))

    elif event_type == "tool.result":
        call_id = payload.get("tool_call_id", "")
        output = payload.get("output", {})
        result_text = output.get("text", "") if isinstance(output, dict) else str(output)
        is_error = payload.get("status") == "error"
        chunks.append(
            _sse(
                {
                    "type": "tool-result",
                    "toolCallId": call_id,
                    "result": result_text,
                    "isError": is_error,
                }
            )
        )

    elif event_type in ("run.end", "message.end"):
        # Store usage so streaming.py can emit the finish event.
        # Both run.end and message.end carry the authoritative token counts.
        usage = payload.get("usage", {})
        text_state["run_end_usage"] = usage
        # Signal to streaming.py that the run is complete.
        text_state["run_ended"] = True

    # message.start → no SSE (the stream `start` event serves this purpose)

    elif event_type == "status":
        code = payload.get("code", "")
        label = payload.get("label", "")
        chunks.append(_sse({"type": "status", "code": code, "label": label}))

    # run.start, keepalive, unknown → no SSE output

    return chunks
