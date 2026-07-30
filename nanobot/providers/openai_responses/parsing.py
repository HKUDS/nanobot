"""Parse Responses API SSE streams and SDK response objects."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, cast

import httpx
from loguru import logger

from nanobot.providers.base import LLMResponse, ToolCallRequest, parse_tool_arguments
from nanobot.providers.openai_responses.state import build_responses_state

FINISH_REASON_MAP = {
    "completed": "stop",
    "incomplete": "length",
    "failed": "error",
    "cancelled": "error",
}
REPLAYABLE_FINISH_REASONS = frozenset({"stop", "tool_calls", "function_call"})


@dataclass(slots=True)
class ResponsesStreamCapture:
    """Losslessly capture terminal output items without changing stream results."""

    completed: bool = False
    response: dict[str, Any] | None = field(default=None, repr=False)
    _items_by_index: dict[int, dict[str, Any]] = field(default_factory=dict, repr=False)

    def record_output_item(self, index: object, item: object) -> None:
        item_object = _response_object(item)
        if item_object is None:
            return
        output_index = (
            index
            if isinstance(index, int) and not isinstance(index, bool)
            else len(self._items_by_index)
        )
        self._items_by_index[output_index] = item_object

    def record_completed(self, response: object) -> None:
        response_object = _response_object(response)
        if response_object is None:
            return
        self.completed = True
        self.response = response_object

    @property
    def output_items(self) -> list[dict[str, Any]]:
        if self.response is not None:
            output = _response_object_list(self.response.get("output"))
            if output:
                return output
        return [self._items_by_index[index] for index in sorted(self._items_by_index)]


def _as_json_object(value: object) -> dict[str, Any] | None:
    """Narrow untyped Responses API JSON payloads at the wire boundary."""
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def _response_object(value: object) -> dict[str, Any] | None:
    """Convert a Responses SDK model or JSON object to a dictionary."""
    object_value = _as_json_object(value)
    if object_value is not None:
        return object_value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return _as_json_object(dump())
    try:
        return _as_json_object(vars(value))
    except TypeError:
        return None


def _response_object_list(value: object) -> list[dict[str, Any]]:
    """Normalize a Responses API array that may contain SDK model objects."""
    if not isinstance(value, list):
        return []
    return [
        item
        for raw in cast(list[object], value)
        if (item := _response_object(raw)) is not None
    ]


def map_finish_reason(status: str | None) -> str:
    """Map a Responses API status string to a Chat-Completions-style finish_reason."""
    return FINISH_REASON_MAP.get(status or "completed", "stop")


def is_replayable_finish_reason(finish_reason: str) -> bool:
    """Return whether a response can safely advance opaque conversation state."""
    return finish_reason in REPLAYABLE_FINISH_REASONS


def _response_finish_reason(
    response: object,
    *,
    fallback_status: str | None = None,
) -> str:
    """Map terminal response details without treating content filtering as truncation."""
    response_object = _response_object(response) or {}
    status = response_object.get("status")
    terminal_status = status if isinstance(status, str) else fallback_status
    if terminal_status == "incomplete":
        details = _response_object(response_object.get("incomplete_details"))
        if details is not None and details.get("reason") == "content_filter":
            return "content_filter"
    return map_finish_reason(terminal_status)


def _usage_from_response_obj(response: object) -> dict[str, int]:
    response_object = _response_object(response)
    usage_raw: object = (
        response_object.get("usage")
        if response_object is not None
        else getattr(response, "usage", None)
    )
    if not usage_raw:
        return {}
    usage = _response_object(usage_raw)
    if usage is None:
        return {}
    prompt_tokens = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    completion_tokens = int(
        usage.get("output_tokens") or usage.get("completion_tokens") or 0
    )
    total_tokens = int(usage.get("total_tokens") or prompt_tokens + completion_tokens)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _parse_tool_call_arguments(args_raw: Any, name: str | None) -> Any:
    parsed = parse_tool_arguments(args_raw)
    if parsed == args_raw and isinstance(args_raw, str) and args_raw.strip():
        logger.warning(
            "Failed to parse tool call arguments for '{}': {}",
            name,
            args_raw[:200],
        )
    return parsed


def _tool_arguments_source(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return "{}"


def _refusal_event_key(
    item_id: object,
    content_index: object,
) -> tuple[str | None, int | None]:
    """Identify one streamed refusal content part across delta/done events."""
    return (
        item_id if isinstance(item_id, str) else None,
        (
            content_index
            if isinstance(content_index, int) and not isinstance(content_index, bool)
            else None
        ),
    )


def _remaining_refusal_text(streamed_text: str, refusal_text: str) -> str:
    """Return only text not already surfaced by refusal deltas."""
    if not streamed_text:
        return refusal_text
    if refusal_text.startswith(streamed_text):
        return refusal_text[len(streamed_text):]
    return ""


def _extract_refusal_text_from_output(output: object) -> tuple[bool, str]:
    """Extract refusal content from terminal Responses output items."""
    refusal_seen = False
    parts: list[str] = []
    for item in _response_object_list(output):
        if item.get("type") != "message":
            continue
        for block in _response_object_list(item.get("content")):
            if block.get("type") != "refusal":
                continue
            refusal_seen = True
            refusal_text = block.get("refusal")
            if isinstance(refusal_text, str):
                parts.append(refusal_text)
    return refusal_seen, "".join(parts)


async def iter_sse(response: httpx.Response) -> AsyncGenerator[dict[str, Any], None]:
    """Yield parsed JSON events from a Responses API SSE stream."""
    buffer: list[str] = []

    def _flush() -> dict[str, Any] | None:
        data_lines = [line[5:].strip() for line in buffer if line.startswith("data:")]
        buffer.clear()
        if not data_lines:
            return None
        data = "\n".join(data_lines).strip()
        if not data or data == "[DONE]":
            return None
        try:
            return _as_json_object(json.loads(data))
        except Exception:
            logger.warning("Failed to parse SSE event JSON: {}", data[:200])
            return None

    async for line in response.aiter_lines():
        if line == "":
            if buffer:
                event = _flush()
                if event is not None:
                    yield event
            continue
        buffer.append(line)

    # Flush any remaining buffer at EOF (#10)
    if buffer:
        event = _flush()
        if event is not None:
            yield event


async def consume_sse(
    response: httpx.Response,
    on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    on_tool_call_delta: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> tuple[str, list[ToolCallRequest], str]:
    """Consume a Responses API SSE stream into ``(content, tool_calls, finish_reason)``."""
    content, tool_calls, finish_reason, _, _ = await consume_sse_with_reasoning(
        response,
        on_content_delta=on_content_delta,
        on_tool_call_delta=on_tool_call_delta,
    )
    return content, tool_calls, finish_reason


async def consume_sse_with_reasoning(
    response: httpx.Response,
    on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    on_tool_call_delta: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    on_reasoning_delta: Callable[[str], Awaitable[None]] | None = None,
    on_response_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    capture: ResponsesStreamCapture | None = None,
) -> tuple[str, list[ToolCallRequest], str, dict[str, int], str | None]:
    """Consume a Responses API SSE stream, including visible reasoning summaries."""
    content = ""
    tool_calls: list[ToolCallRequest] = []
    tool_call_buffers: dict[str, dict[str, Any]] = {}
    tool_call_args_emitted: set[str] = set()
    finish_reason = "stop"
    usage: dict[str, int] = {}
    reasoning_content: str | None = None
    streamed_reasoning = False
    refusal_seen = False
    refusal_deltas: dict[tuple[str | None, int | None], str] = {}
    emitted_refusal_text = ""

    async for event in iter_sse(response):
        if on_response_event:
            await on_response_event(event)
        event_type = event.get("type")
        if event_type == "response.output_item.added":
            item = _as_json_object(event.get("item")) or {}
            if item.get("type") == "function_call":
                call_id = item.get("call_id")
                if not call_id:
                    continue
                arguments = item.get("arguments")
                tool_call_buffers[call_id] = {
                    "id": item.get("id") or "fc_0",
                    "name": item.get("name"),
                    "arguments": "" if arguments is None else arguments,
                }
                if on_tool_call_delta:
                    await on_tool_call_delta({
                        "call_id": str(call_id),
                        "name": str(item.get("name") or ""),
                        "arguments_delta": "",
                    })
        elif event_type == "response.output_text.delta":
            delta_text = event.get("delta") or ""
            content += delta_text
            if on_content_delta and delta_text:
                await on_content_delta(delta_text)
        elif event_type == "response.refusal.delta":
            refusal_seen = True
            delta_text = event.get("delta")
            if isinstance(delta_text, str) and delta_text:
                key = _refusal_event_key(
                    event.get("item_id"),
                    event.get("content_index"),
                )
                refusal_deltas[key] = refusal_deltas.get(key, "") + delta_text
                content += delta_text
                emitted_refusal_text += delta_text
                if on_content_delta:
                    await on_content_delta(delta_text)
        elif event_type == "response.refusal.done":
            refusal_seen = True
            refusal_text = event.get("refusal")
            key = _refusal_event_key(
                event.get("item_id"),
                event.get("content_index"),
            )
            streamed_text = refusal_deltas.pop(key, "")
            if isinstance(refusal_text, str) and refusal_text:
                remaining_text = _remaining_refusal_text(streamed_text, refusal_text)
                content += remaining_text
                emitted_refusal_text += remaining_text
                if on_content_delta and remaining_text:
                    await on_content_delta(remaining_text)
        elif event_type == "response.reasoning_summary_text.delta":
            delta_text = event.get("delta") or ""
            if delta_text:
                reasoning_content = (reasoning_content or "") + delta_text
                streamed_reasoning = True
                if on_reasoning_delta:
                    await on_reasoning_delta(delta_text)
        elif event_type == "response.reasoning_summary_text.done":
            text = event.get("text") or ""
            if text and not streamed_reasoning and not reasoning_content:
                reasoning_content = text
                if on_reasoning_delta:
                    await on_reasoning_delta(text)
        elif event_type == "response.reasoning_summary_part.done":
            part = _as_json_object(event.get("part")) or {}
            text = part.get("text") if part.get("type") == "summary_text" else None
            if text and not streamed_reasoning and not reasoning_content:
                reasoning_content = text
                if on_reasoning_delta:
                    await on_reasoning_delta(text)
        elif event_type == "response.function_call_arguments.delta":
            call_id = event.get("call_id")
            if call_id and call_id in tool_call_buffers:
                delta = event.get("delta") or ""
                current = tool_call_buffers[call_id].get("arguments")
                if not isinstance(current, str):
                    current = ""
                tool_call_buffers[call_id]["arguments"] = current + delta
                if on_tool_call_delta and delta:
                    await on_tool_call_delta({
                        "call_id": str(call_id),
                        "name": str(tool_call_buffers[call_id].get("name") or ""),
                        "arguments_delta": str(delta),
                    })
        elif event_type == "response.function_call_arguments.done":
            call_id = event.get("call_id")
            if call_id and call_id in tool_call_buffers:
                arguments = event.get("arguments")
                tool_call_buffers[call_id]["arguments"] = arguments
                if on_tool_call_delta:
                    tool_call_args_emitted.add(str(call_id))
                    await on_tool_call_delta({
                        "call_id": str(call_id),
                        "name": str(tool_call_buffers[call_id].get("name") or ""),
                        "arguments": "" if arguments is None else str(arguments),
                    })
        elif event_type == "response.output_item.done":
            item = _as_json_object(event.get("item")) or {}
            if capture is not None:
                capture.record_output_item(event.get("output_index"), item)
            if item.get("type") == "function_call":
                call_id = item.get("call_id")
                if not call_id:
                    continue
                buf = tool_call_buffers.get(call_id) or {}
                args_raw = _tool_arguments_source(buf.get("arguments"), item.get("arguments"))
                if on_tool_call_delta and str(call_id) not in tool_call_args_emitted:
                    tool_call_args_emitted.add(str(call_id))
                    await on_tool_call_delta({
                        "call_id": str(call_id),
                        "name": str(buf.get("name") or item.get("name") or ""),
                        "arguments": str(args_raw),
                    })
                args = _parse_tool_call_arguments(
                    args_raw,
                    buf.get("name") or item.get("name"),
                )
                tool_calls.append(
                    ToolCallRequest(
                        id=f"{call_id}|{buf.get('id') or item.get('id') or 'fc_0'}",
                        name=buf.get("name") or item.get("name") or "",
                        arguments=args,
                    )
                )
            elif item.get("type") == "reasoning" and not reasoning_content:
                summary = _extract_reasoning_summary_from_output([item])
                if summary:
                    reasoning_content = summary
                    if on_reasoning_delta:
                        await on_reasoning_delta(summary)
        elif event_type in {"response.completed", "response.incomplete"}:
            response_obj = _response_object(event.get("response")) or {}
            if capture is not None:
                capture.record_completed(response_obj)
            finish_reason = _response_finish_reason(
                response_obj,
                fallback_status=event_type.removeprefix("response."),
            )
            usage = _usage_from_response_obj(response_obj) or usage
            terminal_refusal, terminal_refusal_text = _extract_refusal_text_from_output(
                response_obj.get("output")
            )
            if terminal_refusal:
                refusal_seen = True
                remaining_text = _remaining_refusal_text(
                    emitted_refusal_text,
                    terminal_refusal_text,
                )
                content += remaining_text
                emitted_refusal_text += remaining_text
                if on_content_delta and remaining_text:
                    await on_content_delta(remaining_text)
            if not reasoning_content:
                summary = _extract_reasoning_summary_from_output(response_obj.get("output"))
                if summary:
                    reasoning_content = summary
                    if on_reasoning_delta:
                        await on_reasoning_delta(summary)
        elif event_type in {"error", "response.failed"}:
            detail = event.get("error") or event.get("message") or event
            raise RuntimeError(f"Response failed: {str(detail)[:500]}")

    if refusal_seen:
        finish_reason = "refusal"
    return content, tool_calls, finish_reason, usage, reasoning_content


def _extract_reasoning_summary_from_output(output: object) -> str | None:
    parts: list[str] = []
    for item in _response_object_list(output):
        if item.get("type") != "reasoning":
            continue
        for summary in _response_object_list(item.get("summary")):
            if summary.get("type") == "summary_text" and summary.get("text"):
                text = summary.get("text")
                if isinstance(text, str):
                    parts.append(text)
    return "".join(parts) or None


def parse_response_output(
    response: object,
    *,
    state_provider: str | None = None,
    state_model: str | None = None,
    state_input_items: list[dict[str, Any]] | None = None,
) -> LLMResponse:
    """Parse an SDK ``Response`` object into an ``LLMResponse``."""
    response_object = _response_object(response) or {}

    output = _response_object_list(response_object.get("output"))
    content_parts: list[str] = []
    tool_calls: list[ToolCallRequest] = []
    reasoning_content: str | None = None
    refusal_seen = False

    for item in output:
        item_type = item.get("type")
        if item_type == "message":
            for block in _response_object_list(item.get("content")):
                block_type = block.get("type")
                if block_type == "output_text":
                    text = block.get("text")
                    if isinstance(text, str):
                        content_parts.append(text)
                elif block_type == "refusal":
                    refusal_seen = True
                    refusal = block.get("refusal")
                    if isinstance(refusal, str):
                        content_parts.append(refusal)
        elif item_type == "reasoning":
            for s in _response_object_list(item.get("summary")):
                if s.get("type") == "summary_text" and s.get("text"):
                    text = s.get("text")
                    if isinstance(text, str):
                        reasoning_content = (reasoning_content or "") + text
        elif item_type == "function_call":
            call_id = item.get("call_id") or ""
            item_id = item.get("id") or "fc_0"
            args_raw = _tool_arguments_source(item.get("arguments"))
            args = _parse_tool_call_arguments(args_raw, item.get("name"))
            tool_calls.append(ToolCallRequest(
                id=f"{call_id}|{item_id}",
                name=item.get("name") or "",
                arguments=args,
            ))

    usage = _usage_from_response_obj(response_object)

    status = response_object.get("status")
    finish_reason = "refusal" if refusal_seen else _response_finish_reason(response_object)

    result = LLMResponse(
        content="".join(content_parts) or None,
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        usage=usage,
        reasoning_content=reasoning_content if isinstance(reasoning_content, str) else None,
    )
    if (
        state_provider is not None
        and state_model is not None
        and state_input_items is not None
        and (status is None or status == "completed")
        and is_replayable_finish_reason(finish_reason)
    ):
        result.provider_state = build_responses_state(
            provider=state_provider,
            model=state_model,
            input_items=state_input_items,
            output_items=output,
            usage=usage,
        )
    return result


async def consume_sdk_stream(
    stream: Any,
    on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    on_tool_call_delta: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    capture: ResponsesStreamCapture | None = None,
) -> tuple[str, list[ToolCallRequest], str, dict[str, int], str | None]:
    """Consume an SDK async stream from ``client.responses.create(stream=True)``."""
    content = ""
    tool_calls: list[ToolCallRequest] = []
    tool_call_buffers: dict[str, dict[str, Any]] = {}
    tool_call_args_emitted: set[str] = set()
    finish_reason = "stop"
    usage: dict[str, int] = {}
    reasoning_content: str | None = None
    refusal_seen = False
    refusal_deltas: dict[tuple[str | None, int | None], str] = {}
    emitted_refusal_text = ""

    async for raw_event in stream:
        event: Any = raw_event
        event_type = getattr(event, "type", None)
        if event_type == "response.output_item.added":
            item = getattr(event, "item", None)
            if item and getattr(item, "type", None) == "function_call":
                call_id = getattr(item, "call_id", None)
                if not call_id:
                    continue
                arguments = getattr(item, "arguments", None)
                tool_call_buffers[call_id] = {
                    "id": getattr(item, "id", None) or "fc_0",
                    "name": getattr(item, "name", None),
                    "arguments": "" if arguments is None else arguments,
                }
                if on_tool_call_delta:
                    await on_tool_call_delta({
                        "call_id": str(call_id),
                        "name": str(getattr(item, "name", None) or ""),
                        "arguments_delta": "",
                    })
        elif event_type == "response.output_text.delta":
            delta_text = getattr(event, "delta", "") or ""
            content += delta_text
            if on_content_delta and delta_text:
                await on_content_delta(delta_text)
        elif event_type == "response.refusal.delta":
            refusal_seen = True
            delta_text = getattr(event, "delta", None)
            if isinstance(delta_text, str) and delta_text:
                key = _refusal_event_key(
                    getattr(event, "item_id", None),
                    getattr(event, "content_index", None),
                )
                refusal_deltas[key] = refusal_deltas.get(key, "") + delta_text
                content += delta_text
                emitted_refusal_text += delta_text
                if on_content_delta:
                    await on_content_delta(delta_text)
        elif event_type == "response.refusal.done":
            refusal_seen = True
            refusal_text = getattr(event, "refusal", None)
            key = _refusal_event_key(
                getattr(event, "item_id", None),
                getattr(event, "content_index", None),
            )
            streamed_text = refusal_deltas.pop(key, "")
            if isinstance(refusal_text, str) and refusal_text:
                remaining_text = _remaining_refusal_text(streamed_text, refusal_text)
                content += remaining_text
                emitted_refusal_text += remaining_text
                if on_content_delta and remaining_text:
                    await on_content_delta(remaining_text)
        elif event_type == "response.function_call_arguments.delta":
            call_id = getattr(event, "call_id", None)
            if call_id and call_id in tool_call_buffers:
                delta = getattr(event, "delta", "") or ""
                current = tool_call_buffers[call_id].get("arguments")
                if not isinstance(current, str):
                    current = ""
                tool_call_buffers[call_id]["arguments"] = current + delta
                if on_tool_call_delta and delta:
                    await on_tool_call_delta({
                        "call_id": str(call_id),
                        "name": str(tool_call_buffers[call_id].get("name") or ""),
                        "arguments_delta": str(delta),
                    })
        elif event_type == "response.function_call_arguments.done":
            call_id = getattr(event, "call_id", None)
            if call_id and call_id in tool_call_buffers:
                arguments = getattr(event, "arguments", None)
                tool_call_buffers[call_id]["arguments"] = arguments
                if on_tool_call_delta:
                    tool_call_args_emitted.add(str(call_id))
                    await on_tool_call_delta({
                        "call_id": str(call_id),
                        "name": str(tool_call_buffers[call_id].get("name") or ""),
                        "arguments": "" if arguments is None else str(arguments),
                    })
        elif event_type == "response.output_item.done":
            item = getattr(event, "item", None)
            if capture is not None:
                capture.record_output_item(getattr(event, "output_index", None), item)
            if item and getattr(item, "type", None) == "function_call":
                call_id = getattr(item, "call_id", None)
                if not call_id:
                    continue
                buf = tool_call_buffers.get(call_id) or {}
                args_raw = _tool_arguments_source(
                    buf.get("arguments"),
                    getattr(item, "arguments", None),
                )
                if on_tool_call_delta and str(call_id) not in tool_call_args_emitted:
                    tool_call_args_emitted.add(str(call_id))
                    await on_tool_call_delta({
                        "call_id": str(call_id),
                        "name": str(buf.get("name") or getattr(item, "name", None) or ""),
                        "arguments": str(args_raw),
                    })
                args = _parse_tool_call_arguments(
                    args_raw,
                    buf.get("name") or getattr(item, "name", None),
                )
                tool_calls.append(
                    ToolCallRequest(
                        id=f"{call_id}|{buf.get('id') or getattr(item, 'id', None) or 'fc_0'}",
                        name=buf.get("name") or getattr(item, "name", None) or "",
                        arguments=args,
                    )
                )
        elif event_type in {"response.completed", "response.incomplete"}:
            resp = getattr(event, "response", None)
            response_obj = _response_object(resp) or {}
            if capture is not None:
                capture.record_completed(resp)
            finish_reason = _response_finish_reason(
                resp,
                fallback_status=event_type.removeprefix("response."),
            )
            terminal_output = response_obj.get("output")
            if terminal_output is None:
                terminal_output = getattr(resp, "output", None)
            terminal_refusal, terminal_refusal_text = _extract_refusal_text_from_output(
                terminal_output
            )
            if terminal_refusal:
                refusal_seen = True
                remaining_text = _remaining_refusal_text(
                    emitted_refusal_text,
                    terminal_refusal_text,
                )
                content += remaining_text
                emitted_refusal_text += remaining_text
                if on_content_delta and remaining_text:
                    await on_content_delta(remaining_text)
            if resp:
                usage_obj = getattr(resp, "usage", None)
                if usage_obj:
                    usage = {
                        "prompt_tokens": int(getattr(usage_obj, "input_tokens", 0) or 0),
                        "completion_tokens": int(getattr(usage_obj, "output_tokens", 0) or 0),
                        "total_tokens": int(getattr(usage_obj, "total_tokens", 0) or 0),
                    }
                for out_item in cast(list[Any], getattr(resp, "output", None) or []):
                    if getattr(out_item, "type", None) == "reasoning":
                        for s in cast(list[Any], getattr(out_item, "summary", None) or []):
                            if getattr(s, "type", None) == "summary_text":
                                text = getattr(s, "text", None)
                                if text:
                                    reasoning_content = (reasoning_content or "") + text
        elif event_type in {"error", "response.failed"}:
            detail = getattr(event, "error", None) or getattr(event, "message", None) or event
            raise RuntimeError(f"Response failed: {str(detail)[:500]}")

    if refusal_seen:
        finish_reason = "refusal"
    return content, tool_calls, finish_reason, usage, reasoning_content
