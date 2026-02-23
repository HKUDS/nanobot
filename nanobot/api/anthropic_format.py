"""Anthropic <-> LiteLLM (OpenAI) format conversion.

Converts between the Anthropic Messages API format and the OpenAI/LiteLLM
chat completion format so the proxy can serve Anthropic-format requests
using any LiteLLM-supported backend.
"""

import json
from typing import Any, AsyncIterator

# Anthropic stop_reason -> OpenAI finish_reason
_STOP_REASON_MAP = {
    "stop": "end_turn",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "content_filter": "end_turn",
}

# OpenAI finish_reason -> Anthropic stop_reason (reverse)
_FINISH_REASON_MAP = {v: k for k, v in _STOP_REASON_MAP.items()}


def anthropic_request_to_litellm(body: dict[str, Any]) -> dict[str, Any]:
    """Convert an Anthropic Messages API request to LiteLLM (OpenAI) format.

    Handles: system, messages (text/image/tool_use/tool_result), tools, stop_sequences.
    """
    litellm_messages: list[dict[str, Any]] = []

    # System prompt
    system = body.get("system")
    if isinstance(system, str) and system:
        litellm_messages.append({"role": "system", "content": system})
    elif isinstance(system, list):
        text_parts = [b["text"] for b in system if b.get("type") == "text"]
        if text_parts:
            litellm_messages.append({"role": "system", "content": "\n\n".join(text_parts)})

    # Messages
    for msg in body.get("messages", []):
        role = msg.get("role")
        content = msg.get("content")

        if role == "assistant":
            if isinstance(content, str):
                litellm_messages.append({"role": "assistant", "content": content})
            elif isinstance(content, list):
                text_parts = []
                tool_calls = []
                for block in content:
                    btype = block.get("type")
                    if btype == "text":
                        text_parts.append(block["text"])
                    elif btype == "tool_use":
                        tool_calls.append({
                            "id": block.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": block.get("name", ""),
                                "arguments": json.dumps(block.get("input", {})),
                            },
                        })
                assistant_msg: dict[str, Any] = {"role": "assistant"}
                assistant_msg["content"] = "\n".join(text_parts) if text_parts else None
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                litellm_messages.append(assistant_msg)
            continue

        if role == "user":
            if isinstance(content, str):
                litellm_messages.append({"role": "user", "content": content})
            elif isinstance(content, list):
                user_parts: list[dict[str, Any]] = []
                tool_results: list[dict[str, Any]] = []
                for block in content:
                    btype = block.get("type")
                    if btype == "text":
                        user_parts.append({"type": "text", "text": block["text"]})
                    elif btype == "image":
                        source = block.get("source", {})
                        if source.get("type") == "base64":
                            url = f"data:{source['media_type']};base64,{source['data']}"
                            user_parts.append({
                                "type": "image_url",
                                "image_url": {"url": url},
                            })
                    elif btype == "tool_result":
                        # Tool results become separate messages
                        result_content = block.get("content", "")
                        if isinstance(result_content, list):
                            result_content = "\n".join(
                                b.get("text", "") for b in result_content if b.get("type") == "text"
                            )
                        tool_results.append({
                            "role": "tool",
                            "tool_call_id": block.get("tool_use_id", ""),
                            "content": result_content,
                        })
                # Add tool results first (they relate to previous assistant turn)
                litellm_messages.extend(tool_results)
                # Then add user content if any
                if user_parts:
                    if len(user_parts) == 1 and user_parts[0].get("type") == "text":
                        litellm_messages.append({"role": "user", "content": user_parts[0]["text"]})
                    else:
                        litellm_messages.append({"role": "user", "content": user_parts})
            continue

        # Pass through other roles
        litellm_messages.append(msg)

    result: dict[str, Any] = {
        "model": body.get("model", ""),
        "messages": litellm_messages,
        "max_tokens": body.get("max_tokens", 4096),
    }

    if "temperature" in body:
        result["temperature"] = body["temperature"]

    # stop_sequences -> stop
    if "stop_sequences" in body:
        result["stop"] = body["stop_sequences"]

    # Tools
    if "tools" in body:
        openai_tools = []
        for tool in body["tools"]:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
                },
            })
        result["tools"] = openai_tools
        result["tool_choice"] = "auto"

    if body.get("stream"):
        result["stream"] = True

    return result


def litellm_response_to_anthropic(response: Any, model: str = "") -> dict[str, Any]:
    """Convert a LiteLLM response object to Anthropic Messages API format."""
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
                    args = {}
            content_blocks.append({
                "type": "tool_use",
                "id": tc.id,
                "name": tc.function.name,
                "input": args,
            })

    # Map finish reason
    finish = choice.finish_reason or "stop"
    stop_reason = _STOP_REASON_MAP.get(finish, "end_turn")

    usage = response.usage if hasattr(response, "usage") and response.usage else None

    return {
        "id": getattr(response, "id", "msg_proxy"),
        "type": "message",
        "role": "assistant",
        "model": model or getattr(response, "model", ""),
        "content": content_blocks,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.prompt_tokens if usage else 0,
            "output_tokens": usage.completion_tokens if usage else 0,
        },
    }


async def generate_sse_events(
    stream: AsyncIterator,
    model: str = "",
) -> AsyncIterator[str]:
    """Convert LiteLLM streaming chunks to Anthropic SSE event sequence.

    Yields SSE-formatted strings: "event: <type>\\ndata: <json>\\n\\n"
    """
    # message_start
    yield _sse("message_start", {
        "type": "message_start",
        "message": {
            "id": "msg_proxy",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    })

    block_index = 0
    in_text_block = False
    in_tool_block = False
    current_tool_id = ""
    current_tool_name = ""

    async for chunk in stream:
        if not hasattr(chunk, "choices") or not chunk.choices:
            continue

        delta = chunk.choices[0].delta
        finish_reason = chunk.choices[0].finish_reason

        # Text content
        text = getattr(delta, "content", None)
        if text:
            if not in_text_block:
                yield _sse("content_block_start", {
                    "type": "content_block_start",
                    "index": block_index,
                    "content_block": {"type": "text", "text": ""},
                })
                in_text_block = True

            yield _sse("content_block_delta", {
                "type": "content_block_delta",
                "index": block_index,
                "delta": {"type": "text_delta", "text": text},
            })

        # Tool calls
        tool_calls = getattr(delta, "tool_calls", None)
        if tool_calls:
            for tc in tool_calls:
                fn = getattr(tc, "function", None)
                if not fn:
                    continue

                # New tool call starts
                if fn.name:
                    # Close previous blocks
                    if in_text_block:
                        yield _sse("content_block_stop", {
                            "type": "content_block_stop",
                            "index": block_index,
                        })
                        block_index += 1
                        in_text_block = False

                    if in_tool_block:
                        yield _sse("content_block_stop", {
                            "type": "content_block_stop",
                            "index": block_index,
                        })
                        block_index += 1

                    current_tool_id = tc.id or ""
                    current_tool_name = fn.name
                    yield _sse("content_block_start", {
                        "type": "content_block_start",
                        "index": block_index,
                        "content_block": {
                            "type": "tool_use",
                            "id": current_tool_id,
                            "name": current_tool_name,
                            "input": {},
                        },
                    })
                    in_tool_block = True

                # Tool arguments delta
                if fn.arguments:
                    yield _sse("content_block_delta", {
                        "type": "content_block_delta",
                        "index": block_index,
                        "delta": {
                            "type": "input_json_delta",
                            "partial_json": fn.arguments,
                        },
                    })

        # Stream finished
        if finish_reason:
            if in_text_block:
                yield _sse("content_block_stop", {
                    "type": "content_block_stop",
                    "index": block_index,
                })
            if in_tool_block:
                yield _sse("content_block_stop", {
                    "type": "content_block_stop",
                    "index": block_index,
                })

            stop_reason = _STOP_REASON_MAP.get(finish_reason, "end_turn")
            yield _sse("message_delta", {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": 0},
            })
            yield _sse("message_stop", {"type": "message_stop"})


def _sse(event: str, data: dict[str, Any]) -> str:
    """Format an SSE event string."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
