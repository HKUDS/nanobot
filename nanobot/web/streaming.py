"""SSE streaming adapter for the Vercel AI SDK Data Stream Protocol.

Converts AgentLoop.process_direct() on_progress callbacks into SSE events
that assistant-ui can consume natively.

Protocol reference (Vercel AI SDK Data Stream):
    0:"text"              — text token
    2:[{"toolCallId":...}] — tool call streaming start
    9:{"toolCallId":...,"toolName":...,"args":{}}  — tool call
    a:{"toolCallId":...,"result":"..."}             — tool result
    e:{"finishReason":"stop","usage":{}}            — finish
    d:{"finishReason":"stop","usage":{}}            — done (alternative)
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import AsyncGenerator

# ---------------------------------------------------------------------------
# Tool hint parser
# ---------------------------------------------------------------------------

_TOOL_HINT_PATTERN = re.compile(
    r"🔧\s*(?:Calling|Running)\s+`?(\w+)`?\s*(?:with\s*(.*?))?$",
    re.IGNORECASE | re.DOTALL,
)

_TOOL_RESULT_PATTERN = re.compile(
    r"✅\s*(?:Result|Done|Completed)\s*(?:from\s+`?(\w+)`?)?\s*:?\s*(.*)",
    re.IGNORECASE | re.DOTALL,
)


def _parse_tool_hint(text: str) -> dict | None:
    """Try to parse a tool hint from on_progress output."""
    m = _TOOL_HINT_PATTERN.search(text)
    if m:
        return {"tool_name": m.group(1), "args_hint": m.group(2) or ""}
    return None


# ---------------------------------------------------------------------------
# Stream generator
# ---------------------------------------------------------------------------


async def stream_agent_response(
    agent_loop,  # AgentLoop instance
    content: str,
    session_key: str,
) -> AsyncGenerator[str, None]:
    """Run agent and yield SSE-formatted events in Vercel AI SDK Data Stream Protocol.

    Each yielded string is a complete SSE ``data:`` line (without the ``data: `` prefix,
    that is added by sse-starlette).
    """
    text_queue: asyncio.Queue[str | None] = asyncio.Queue()
    tool_calls_active: dict[str, str] = {}  # toolCallId -> toolName
    streamed_text_len = 0  # track how much text we've already emitted

    async def on_progress(
        content: str, *, tool_hint: bool = False, streaming: bool = False
    ) -> None:
        """Callback invoked by AgentLoop during processing."""
        nonlocal streamed_text_len
        if tool_hint:
            # Try to parse as tool invocation hint
            parsed = _parse_tool_hint(content)
            if parsed:
                call_id = f"call_{uuid.uuid4().hex[:12]}"
                tool_calls_active[call_id] = parsed["tool_name"]
                # Emit tool call start event (type 9)
                event = {
                    "toolCallId": call_id,
                    "toolName": parsed["tool_name"],
                    "args": {},
                }
                await text_queue.put(f"9:{json.dumps(event)}\n")
            else:
                # Unknown tool hint format — emit as text
                await text_queue.put(f'0:"{_escape_text(content)}"\n')
        else:
            # Regular text content — emit only the new delta
            if content and len(content) > streamed_text_len:
                delta = content[streamed_text_len:]
                streamed_text_len = len(content)
                await text_queue.put(f'0:"{_escape_text(delta)}"\n')

    async def _run_agent():
        """Run the agent and signal completion."""
        nonlocal streamed_text_len
        try:
            result = await agent_loop.process_direct(
                content,
                session_key=session_key,
                channel="web",
                chat_id=session_key.split(":", 1)[-1] if ":" in session_key else "default",
                on_progress=on_progress,
            )
            # Emit final result only if nothing was streamed via on_progress
            if result and streamed_text_len == 0:
                await text_queue.put(f'0:"{_escape_text(result)}"\n')
        finally:
            await text_queue.put(None)  # Signal completion

    # Start agent processing in background
    task = asyncio.create_task(_run_agent())

    try:
        while True:
            event = await text_queue.get()
            if event is None:
                break
            yield event

        # Emit tool results for any active calls (mark as completed)
        for call_id, tool_name in tool_calls_active.items():
            result_event = {
                "toolCallId": call_id,
                "result": "completed",
            }
            yield f"a:{json.dumps(result_event)}\n"

        # Emit finish event
        finish = {"finishReason": "stop", "usage": {"promptTokens": 0, "completionTokens": 0}}
        yield f"d:{json.dumps(finish)}\n"

    except asyncio.CancelledError:
        task.cancel()
        raise
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass


def _escape_text(text: str) -> str:
    """Escape text for JSON string embedding in the data stream protocol."""
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
