"""Convert between Anthropic Messages API format and OpenAI/LiteLLM format."""

import json
import uuid
from typing import Any, AsyncIterator


def anthropic_request_to_litellm(body: dict[str, Any]) -> dict[str, Any]:
    """Convert Anthropic Messages API request to litellm acompletion kwargs.

    Handles: system prompt, message content blocks, tool definitions,
    tool_use/tool_result blocks, images, and all request parameters.
    """
    messages: list[dict[str, Any]] = []

    # System prompt (top-level string or array of content blocks)
    system = body.get("system")
    if system:
        if isinstance(system, str):
            messages.append({"role": "system", "content": system})
        elif isinstance(system, list):
            text_parts = [b["text"] for b in system if b.get("type") == "text"]
            messages.append({"role": "system", "content": "\n".join(text_parts)})

    # Convert messages
    for msg in body.get("messages", []):
        converted = _convert_message(msg)
        if isinstance(converted, list):
            messages.extend(converted)
        else:
            messages.append(converted)

    kwargs: dict[str, Any] = {
        "model": body["model"],
        "messages": messages,
        "max_tokens": body.get("max_tokens", 4096),
        "temperature": body.get("temperature", 1.0),
        "stream": body.get("stream", False),
    }

    if body.get("tools"):
        kwargs["tools"] = [_convert_tool(t) for t in body["tools"]]
        kwargs["tool_choice"] = "auto"

    if "top_p" in body:
        kwargs["top_p"] = body["top_p"]
    if "stop_sequences" in body:
        kwargs["stop"] = body["stop_sequences"]

    return kwargs


def litellm_response_to_anthropic(response: Any, model: str) -> dict[str, Any]:
    """Convert a litellm/OpenAI response object to Anthropic Messages API format."""
    choice = response.choices[0]
    message = choice.message

    content_blocks: list[dict[str, Any]] = []

    if message.content:
        content_blocks.append({"type": "text", "text": message.content})

    if hasattr(message, "tool_calls") and message.tool_calls:
        for tc in message.tool_calls:
            args = tc.function.arguments
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"raw": args}
            content_blocks.append({
                "type": "tool_use",
                "id": tc.id,
                "name": tc.function.name,
                "input": args,
            })

    stop_reason = _map_stop_reason(choice.finish_reason)

    usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
    if hasattr(response, "usage") and response.usage:
        usage = {
            "input_tokens": response.usage.prompt_tokens or 0,
            "output_tokens": response.usage.completion_tokens or 0,
        }

    return {
        "id": _make_msg_id(),
        "type": "message",
        "role": "assistant",
        "content": content_blocks,
        "model": model,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": usage,
    }


async def generate_sse_events(
    stream: AsyncIterator, model: str, input_tokens: int = 0
) -> AsyncIterator[str]:
    """Async generator yielding Anthropic SSE event strings from a litellm stream.

    Produces the event sequence:
      message_start -> content_block_start -> content_block_delta* ->
      content_block_stop -> message_delta -> message_stop
    """
    msg_id = _make_msg_id()

    # message_start
    yield _sse_line("message_start", {
        "type": "message_start",
        "message": {
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "content": [],
            "model": model,
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": input_tokens, "output_tokens": 0},
        },
    })

    block_index = -1
    block_type: str | None = None
    tool_call_ids: dict[int, str] = {}
    output_tokens = 0
    stop_reason = "end_turn"

    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        finish = chunk.choices[0].finish_reason

        # Text content delta
        if hasattr(delta, "content") and delta.content:
            if block_type != "text":
                if block_type is not None:
                    yield _sse_line("content_block_stop", {
                        "type": "content_block_stop", "index": block_index,
                    })
                block_index += 1
                block_type = "text"
                yield _sse_line("content_block_start", {
                    "type": "content_block_start",
                    "index": block_index,
                    "content_block": {"type": "text", "text": ""},
                })

            yield _sse_line("content_block_delta", {
                "type": "content_block_delta",
                "index": block_index,
                "delta": {"type": "text_delta", "text": delta.content},
            })

        # Tool call deltas
        if hasattr(delta, "tool_calls") and delta.tool_calls:
            for tc_delta in delta.tool_calls:
                tc_index = tc_delta.index if hasattr(tc_delta, "index") else 0
                if tc_index not in tool_call_ids:
                    # New tool call block
                    if block_type is not None:
                        yield _sse_line("content_block_stop", {
                            "type": "content_block_stop", "index": block_index,
                        })
                    block_index += 1
                    block_type = "tool_use"
                    tool_id = tc_delta.id or f"toolu_{uuid.uuid4().hex[:24]}"
                    tool_call_ids[tc_index] = tool_id
                    yield _sse_line("content_block_start", {
                        "type": "content_block_start",
                        "index": block_index,
                        "content_block": {
                            "type": "tool_use",
                            "id": tool_id,
                            "name": tc_delta.function.name if tc_delta.function else "",
                            "input": {},
                        },
                    })

                if tc_delta.function and tc_delta.function.arguments:
                    yield _sse_line("content_block_delta", {
                        "type": "content_block_delta",
                        "index": block_index,
                        "delta": {
                            "type": "input_json_delta",
                            "partial_json": tc_delta.function.arguments,
                        },
                    })

        if finish:
            stop_reason = _map_stop_reason(finish)
            if hasattr(chunk, "usage") and chunk.usage:
                output_tokens = chunk.usage.completion_tokens or 0

    # Close final content block
    if block_type is not None:
        yield _sse_line("content_block_stop", {
            "type": "content_block_stop", "index": block_index,
        })

    # message_delta
    yield _sse_line("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": stop_reason, "stop_sequence": None},
        "usage": {"output_tokens": output_tokens},
    })

    # message_stop
    yield _sse_line("message_stop", {"type": "message_stop"})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _convert_message(msg: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
    """Convert a single Anthropic message to OpenAI format."""
    role = msg["role"]
    content = msg["content"]

    if isinstance(content, str):
        return {"role": role, "content": content}

    if role == "assistant":
        return _convert_assistant_blocks(content)
    elif role == "user":
        return _convert_user_blocks(content)

    return {"role": role, "content": str(content)}


def _convert_assistant_blocks(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    """Convert assistant content blocks, extracting tool_use as tool_calls."""
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []

    for block in blocks:
        if block["type"] == "text":
            text_parts.append(block["text"])
        elif block["type"] == "tool_use":
            tool_calls.append({
                "id": block["id"],
                "type": "function",
                "function": {
                    "name": block["name"],
                    "arguments": json.dumps(block["input"]),
                },
            })

    result: dict[str, Any] = {
        "role": "assistant",
        "content": "\n".join(text_parts) or None,
    }
    if tool_calls:
        result["tool_calls"] = tool_calls
    return result


def _convert_user_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert user content blocks, splitting tool_result into separate messages."""
    result: list[dict[str, Any]] = []
    content_parts: list[dict[str, Any]] = []

    for block in blocks:
        btype = block.get("type", "text")
        if btype == "text":
            content_parts.append({"type": "text", "text": block["text"]})
        elif btype == "image":
            source = block["source"]
            if source.get("type") == "base64":
                content_parts.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{source['media_type']};base64,{source['data']}"
                    },
                })
        elif btype == "tool_result":
            tool_content = block.get("content", "")
            if isinstance(tool_content, list):
                tool_content = "\n".join(
                    b.get("text", "") for b in tool_content if b.get("type") == "text"
                )
            result.append({
                "role": "tool",
                "tool_call_id": block["tool_use_id"],
                "content": str(tool_content),
            })

    if content_parts:
        # Flatten single text block to plain string
        if len(content_parts) == 1 and content_parts[0].get("type") == "text":
            user_msg: dict[str, Any] = {"role": "user", "content": content_parts[0]["text"]}
        else:
            user_msg = {"role": "user", "content": content_parts}
        result.insert(0, user_msg)

    return result if result else [{"role": "user", "content": ""}]


def _convert_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """Convert Anthropic tool definition to OpenAI function format."""
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema", {}),
        },
    }


_STOP_REASON_MAP = {
    "stop": "end_turn",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "content_filter": "end_turn",
}


def _map_stop_reason(finish_reason: str | None) -> str:
    return _STOP_REASON_MAP.get(finish_reason or "stop", "end_turn")


def _make_msg_id() -> str:
    return f"msg_{uuid.uuid4().hex[:24]}"


def _sse_line(event: str, data: dict[str, Any]) -> str:
    """Format a single SSE event line."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
