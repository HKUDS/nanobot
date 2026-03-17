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
# Tool hint parser  (format_hint output: ``tool("arg"), tool2("arg2")``)
# ---------------------------------------------------------------------------

_TOOL_NAME_PATTERN = re.compile(r"(\w+)\(")


def _parse_tool_hints(text: str) -> list[str]:
    """Extract tool names from a format_hint string."""
    return _TOOL_NAME_PATTERN.findall(text)


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
        streamed_text = ""  # actual content — used to detect verifier rewrites
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
                tool_names = _parse_tool_hints(text)
                if tool_names:
                    for name in tool_names:
                        call_id = f"call_{uuid.uuid4().hex[:12]}"
                        tool_calls_active[call_id] = name
                        event = {
                            "toolCallId": call_id,
                            "toolName": name,
                            "args": {},
                        }
                        yield f"9:{json.dumps(event)}\n"
                else:
                    yield f'0:"{_escape_text(text)}"\n'
                # Tool-call boundary — next LLM response starts fresh.
                streamed_text_len = 0
                streamed_text = ""

            elif is_streaming and text:
                # Streaming delta — agent sends cumulative text; emit only new part.
                # Detect a new LLM call (cumulative text restarted shorter).
                if streamed_text_len and len(text) < streamed_text_len:
                    streamed_text_len = 0
                    streamed_text = ""
                if len(text) > streamed_text_len:
                    delta = text[streamed_text_len:]
                    streamed_text_len = len(text)
                    streamed_text = text
                    yield f'0:"{_escape_text(delta)}"\n'

            elif is_progress and text:
                # The agent loop may re-send already-streamed text as a
                # non-streaming progress flush (e.g. before a tool call).
                # Deduplicate against what was already streamed.
                if streamed_text and text.startswith(streamed_text):
                    if len(text) > streamed_text_len:
                        delta = text[streamed_text_len:]
                        streamed_text_len = len(text)
                        streamed_text = text
                        yield f'0:"{_escape_text(delta)}"\n'
                elif streamed_text and streamed_text.startswith(text):
                    pass  # subset of already-streamed content
                else:
                    yield f'0:"{_escape_text(text)}"\n'

            elif not is_progress:
                # Final response from agent
                last_msg = msg
                if text:
                    if not streamed_text:
                        # Nothing streamed yet — emit full text
                        yield f'0:"{_escape_text(text)}"\n'
                    elif text.startswith(streamed_text):
                        # Text continues from what was streamed — emit tail
                        if len(text) > streamed_text_len:
                            delta = text[streamed_text_len:]
                            yield f'0:"{_escape_text(delta)}"\n'
                    # else: verifier revised the answer — text diverges from
                    # already-streamed content.  The final streaming flush
                    # ensures the user received the complete original text,
                    # so we keep what they already saw.
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
