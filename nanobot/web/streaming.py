"""SSE streaming adapter for the ui-message-stream protocol.

Consumes ``OutboundMessage`` events from the ``WebChannel`` per-request
queue and translates them into SSE events that ``@assistant-ui/react``
can consume natively.

The agent loop publishes messages to the bus — the WebChannel dispatcher
routes them to the SSE queue registered for this request.

Two-layer dispatch
------------------
1. **Canonical path** (preferred): if ``msg.metadata["_canonical"]`` is present,
   ``project_to_sse()`` from ``nanobot.web.events`` translates it directly.
2. **Legacy path** (fallback): the original metadata-flag decoding runs unchanged
   for any message that does not carry a canonical event (e.g. CLI, test mocks).

Protocol reference (ui-message-stream / SSE):
    {"type":"start","messageId":"..."}                  — stream start
    {"type":"text-start"}                               — text segment open
    {"type":"text-delta","textDelta":"..."}              — text chunk
    {"type":"text-end"}                                  — text segment close
    {"type":"tool-call-start","toolCallId":...}          — tool invocation
    {"type":"tool-call-delta","argsText":"..."}           — tool args (JSON string)
    {"type":"tool-call-end","toolCallId":"..."}           — tool invocation end
    {"type":"tool-result","toolCallId":...,"result":...}  — tool output
    {"type":"finish","finishReason":"stop","usage":{}}    — done
    [DONE]                                                — stream terminator
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from nanobot.web.events import project_to_sse

if TYPE_CHECKING:
    from nanobot.channels.web import WebChannel


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


def _sse(payload: dict[str, object]) -> str:
    """Format a single ui-message-stream SSE event."""
    return f"event: message\ndata: {json.dumps(payload)}\n\n"


def _sse_done() -> str:
    """Format the mandatory [DONE] stream terminator."""
    return "data: [DONE]\n\n"


def _sse_keepalive() -> str:
    """Format an SSE comment used as a connection keepalive."""
    return ": keepalive\n\n"


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
    """Publish a user message and stream agent responses as SSE events.

    1. Register an SSE queue on the WebChannel for *chat_id*.
    2. Publish the user message to the bus via WebChannel.
    3. Consume ``OutboundMessage`` events from the queue, translating them to
       the ui-message-stream protocol (SSE).
    4. Terminate when a non-progress final response arrives.
    """
    queue = web_channel.register_stream(chat_id)
    tool_calls_active: dict[str, str] = {}
    message_id = uuid.uuid4().hex

    try:
        # Stream start event
        yield _sse({"type": "start", "messageId": message_id})

        # Publish user message → bus → agent
        await web_channel.publish_user_message(
            chat_id,
            content,
            media=media,
            metadata=metadata,
        )

        # Shared state for canonical and legacy dispatch paths.
        # project_to_sse() mutates this dict to track open text segments.
        text_state: dict[str, object] = {
            "text_started": False,
            "streamed_text": "",
            "run_end_usage": None,
            "run_ended": False,
        }
        # Legacy-path tracking (mirrors text_state for the fallback code below).
        streamed_text_len = 0
        last_msg = None
        idle_intervals = 0
        max_idle_intervals = 20  # 20 * 15s = 300s total idle time before giving up
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                idle_intervals += 1
                if idle_intervals >= max_idle_intervals:
                    if not text_state["text_started"]:
                        yield _sse({"type": "text-start"})
                        text_state["text_started"] = True
                    yield _sse(
                        {
                            "type": "text-delta",
                            "textDelta": "[timeout — no response from agent]",
                        }
                    )
                    break
                # SSE comment — ignored by the decoder, keeps connection alive
                yield _sse_keepalive()
                continue

            idle_intervals = 0  # reset on any message

            if msg is None:
                break

            meta = msg.metadata or {}
            canonical = meta.get("_canonical")

            # ------------------------------------------------------------------
            # Canonical path (preferred): translate structured event to SSE.
            # ------------------------------------------------------------------
            if canonical:
                for chunk in project_to_sse(canonical, text_state=text_state):
                    yield chunk
                    # Track active tool calls for the safety-close below.
                    c_type = canonical.get("type", "")
                    if c_type == "tool.call.start":
                        c_payload = canonical.get("payload", {})
                        tool_calls_active[c_payload.get("tool_call_id", "")] = c_payload.get(
                            "tool_name", ""
                        )
                    elif c_type == "tool.result":
                        tool_calls_active.pop(
                            canonical.get("payload", {}).get("tool_call_id", ""), None
                        )

                # run.end on the final (non-progress) message signals completion.
                is_progress = meta.get("_progress", False)
                if not is_progress:
                    last_msg = msg
                    # Guard: emit any final text not yet streamed via canonical events.
                    # This handles non-streaming mode and verifier rewrites where the
                    # complete response arrives on the final message rather than as deltas.
                    final_text = msg.content or ""
                    streamed = str(text_state["streamed_text"])
                    if final_text and not streamed:
                        if not text_state["text_started"]:
                            yield _sse({"type": "text-start"})
                            text_state["text_started"] = True
                        yield _sse({"type": "text-delta", "textDelta": final_text})
                    elif final_text and final_text.startswith(streamed):
                        tail = final_text[len(streamed) :]
                        if tail:
                            if not text_state["text_started"]:
                                yield _sse({"type": "text-start"})
                                text_state["text_started"] = True
                            yield _sse({"type": "text-delta", "textDelta": tail})
                    # else: verifier rewrite — keep what was already shown
                    break
                continue

            # ------------------------------------------------------------------
            # Legacy path (fallback): decode metadata flags as before.
            # Used for messages without _canonical (CLI, test mocks, etc.).
            # ------------------------------------------------------------------
            is_progress = meta.get("_progress", False)
            is_streaming = meta.get("_streaming", False)
            text_started: bool = bool(text_state["text_started"])
            streamed_text: str = str(text_state["streamed_text"])

            text = msg.content or ""

            if meta.get("_tool_call"):
                # Close any open text segment before tool boundary
                if text_started:
                    yield _sse({"type": "text-end"})
                    text_state["text_started"] = False
                    text_started = False

                tc = meta["_tool_call"]
                call_id = tc["toolCallId"]
                tool_name = tc["toolName"]
                args = tc.get("args", {})
                tool_calls_active[call_id] = tool_name

                yield _sse(
                    {
                        "type": "tool-call-start",
                        "toolCallId": call_id,
                        "toolName": tool_name,
                    }
                )
                yield _sse(
                    {
                        "type": "tool-call-delta",
                        "toolCallId": call_id,
                        "argsText": json.dumps(args),
                    }
                )
                yield _sse(
                    {
                        "type": "tool-call-end",
                        "toolCallId": call_id,
                    }
                )

                # Tool-call boundary — next LLM response starts fresh.
                streamed_text_len = 0
                streamed_text = ""
                text_state["streamed_text"] = ""

            elif meta.get("_tool_result"):
                tr = meta["_tool_result"]
                call_id = tr["toolCallId"]
                yield _sse(
                    {
                        "type": "tool-result",
                        "toolCallId": call_id,
                        "result": tr.get("result", ""),
                        "isError": False,
                    }
                )
                tool_calls_active.pop(call_id, None)

            elif is_streaming and text:
                # Streaming delta — agent sends cumulative text; emit only new part.
                # Detect a new LLM call (cumulative text restarted shorter).
                if streamed_text_len and len(text) < streamed_text_len:
                    if text_started:
                        yield _sse({"type": "text-end"})
                        text_state["text_started"] = False
                        text_started = False
                    streamed_text_len = 0
                    streamed_text = ""
                    text_state["streamed_text"] = ""
                if len(text) > streamed_text_len:
                    delta = text[streamed_text_len:]
                    streamed_text_len = len(text)
                    streamed_text = text
                    text_state["streamed_text"] = text
                    if not text_started:
                        yield _sse({"type": "text-start"})
                        text_state["text_started"] = True
                        text_started = True
                    yield _sse({"type": "text-delta", "textDelta": delta})

            elif is_progress and text:
                # The agent loop may re-send already-streamed text as a
                # non-streaming progress flush (e.g. before a tool call).
                # Deduplicate against what was already streamed.
                if streamed_text and text.startswith(streamed_text):
                    if len(text) > streamed_text_len:
                        delta = text[streamed_text_len:]
                        streamed_text_len = len(text)
                        streamed_text = text
                        text_state["streamed_text"] = text
                        if not text_started:
                            yield _sse({"type": "text-start"})
                            text_state["text_started"] = True
                            text_started = True
                        yield _sse({"type": "text-delta", "textDelta": delta})
                elif streamed_text and streamed_text.startswith(text):
                    pass  # subset of already-streamed content
                else:
                    if not text_started:
                        yield _sse({"type": "text-start"})
                        text_state["text_started"] = True
                        text_started = True
                    yield _sse({"type": "text-delta", "textDelta": text})

            elif not is_progress:
                # Final response from agent
                last_msg = msg
                if text:
                    if not streamed_text:
                        # Nothing streamed yet — emit full text
                        if not text_started:
                            yield _sse({"type": "text-start"})
                            text_state["text_started"] = True
                            text_started = True
                        yield _sse({"type": "text-delta", "textDelta": text})
                    elif text.startswith(streamed_text):
                        # Text continues from what was streamed — emit tail
                        if len(text) > streamed_text_len:
                            delta = text[streamed_text_len:]
                            if not text_started:
                                yield _sse({"type": "text-start"})
                                text_state["text_started"] = True
                                text_started = True
                            yield _sse({"type": "text-delta", "textDelta": delta})
                    # else: verifier revised the answer — text diverges from
                    # already-streamed content.  The final streaming flush
                    # ensures the user received the complete original text,
                    # so we keep what they already saw.
                break

        # Close any open text segment
        if text_state["text_started"]:
            yield _sse({"type": "text-end"})

        # Safety: close any tool calls that didn't get an explicit result
        for call_id in tool_calls_active:
            yield _sse(
                {
                    "type": "tool-result",
                    "toolCallId": call_id,
                    "result": "completed",
                    "isError": False,
                }
            )

        # Finish event — prefer usage from canonical run.end, fall back to legacy key.
        _raw_usage = text_state.get("run_end_usage")
        run_end_usage: dict[str, int] = _raw_usage if isinstance(_raw_usage, dict) else {}
        if run_end_usage:
            input_tokens = run_end_usage.get("input_tokens", 0)
            output_tokens = run_end_usage.get("output_tokens", 0)
        else:
            usage_meta = (last_msg.metadata or {}).get("usage", {}) if last_msg else {}
            input_tokens = usage_meta.get("prompt_tokens", 0)
            output_tokens = usage_meta.get("completion_tokens", 0)
        yield _sse(
            {
                "type": "finish",
                "finishReason": "stop",
                "usage": {
                    "inputTokens": input_tokens,
                    "outputTokens": output_tokens,
                },
            }
        )

    finally:
        # [DONE] is mandatory — without it the decoder throws
        # "Stream ended abruptly without receiving [DONE] marker"
        yield _sse_done()
        web_channel.unregister_stream(chat_id)
