"""SSE streaming adapter for the Vercel AI SDK Data Stream Protocol.

Consumes ``OutboundMessage`` events from the ``WebChannel`` per-request
queue and translates them into SSE events that ``@assistant-ui/react``
can consume natively.

The agent loop publishes messages to the bus — the WebChannel dispatcher
routes them to the SSE queue registered for this request.

Protocol reference (Vercel AI SDK Data Stream):
    0:"text"              — text delta
    9:{"toolCallId":...,"toolName":...,"args":{}}  — tool call
    a:{"toolCallId":...,"result":"..."}             — tool result
    d:{"finishReason":"stop","usage":{}}            — done
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nanobot.channels.web import WebChannel

# ---------------------------------------------------------------------------
# Tool hint parser  (agent publishes "🔧 Calling `tool_name` …" progress)
# ---------------------------------------------------------------------------

_TOOL_HINT_PATTERN = re.compile(
    r"🔧\s*(?:Calling|Running)\s+`?(\w+)`?\s*(?:with\s*(.*?))?$",
    re.IGNORECASE | re.DOTALL,
)


def _parse_tool_hint(text: str) -> dict | None:
    m = _TOOL_HINT_PATTERN.search(text)
    if m:
        return {"tool_name": m.group(1), "args_hint": m.group(2) or ""}
    return None


# ---------------------------------------------------------------------------
# Stream generator
# ---------------------------------------------------------------------------


async def stream_agent_response(
    web_channel: WebChannel,
    chat_id: str,
    content: str,
    *,
    media: list[str] | None = None,
    metadata: dict[str, object] | None = None,
) -> AsyncGenerator[str, None]:
    """Publish a user message and stream agent responses as Data Stream events.

    1. Register an SSE queue on the WebChannel for *chat_id*.
    2. Publish the user message to the bus via WebChannel.
    3. Consume ``OutboundMessage`` events from the queue, translating them to
       the Vercel AI SDK Data Stream Protocol.
    4. Terminate when a non-progress final response arrives.
    """
    queue = web_channel.register_stream(chat_id)
    tool_calls_active: dict[str, str] = {}

    try:
        # Publish user message → bus → agent
        await web_channel.publish_user_message(
            chat_id,
            content,
            media=media,
            metadata=metadata,
        )

        # Consume outbound messages until complete
        streamed_text_len = 0
        last_msg = None
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=300)
            except asyncio.TimeoutError:
                # Safety: don't hang forever if agent stalls
                yield f'0:"{_escape_text("[timeout — no response from agent]")}"\n'
                break

            if msg is None:
                break

            meta = msg.metadata or {}
            is_progress = meta.get("_progress", False)
            is_tool_hint = meta.get("_tool_hint", False)
            is_streaming = meta.get("_streaming", False)

            text = msg.content or ""

            if is_tool_hint and text:
                parsed = _parse_tool_hint(text)
                if parsed:
                    call_id = f"call_{uuid.uuid4().hex[:12]}"
                    tool_calls_active[call_id] = parsed["tool_name"]
                    event = {
                        "toolCallId": call_id,
                        "toolName": parsed["tool_name"],
                        "args": {},
                    }
                    yield f"9:{json.dumps(event)}\n"
                else:
                    yield f'0:"{_escape_text(text)}"\n'

            elif is_streaming and text:
                # Streaming delta — agent sends cumulative text; emit only new part
                if len(text) > streamed_text_len:
                    delta = text[streamed_text_len:]
                    streamed_text_len = len(text)
                    yield f'0:"{_escape_text(delta)}"\n'

            elif is_progress and text:
                # Generic progress text — emit as text delta
                yield f'0:"{_escape_text(text)}"\n'

            elif not is_progress:
                # Final response from agent
                last_msg = msg
                if text:
                    yield f'0:"{_escape_text(text)}"\n'
                break

        # Close any open tool calls
        for call_id in tool_calls_active:
            result_event = {"toolCallId": call_id, "result": "completed"}
            yield f"a:{json.dumps(result_event)}\n"

        # Finish event — surface token usage from the agent's response metadata
        usage_meta = (last_msg.metadata or {}).get("usage", {}) if last_msg else {}
        finish = {
            "finishReason": "stop",
            "usage": {
                "promptTokens": usage_meta.get("prompt_tokens", 0),
                "completionTokens": usage_meta.get("completion_tokens", 0),
            },
        }
        yield f"d:{json.dumps(finish)}\n"

    finally:
        web_channel.unregister_stream(chat_id)


def _escape_text(text: str) -> str:
    """Escape text for JSON string embedding in the data stream protocol."""
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
