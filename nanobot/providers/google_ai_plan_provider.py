"""Stateless Google AI Ultra inference (earendil-works/pi#12614, Google Interactions)."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, cast

import httpx

from nanobot import __version__
from nanobot.providers.base import (
    LLMProvider,
    LLMResponse,
    LLMUsage,
    ToolCallRequest,
    parse_tool_arguments,
    resolve_stream_idle_timeout_s,
    tool_arguments_object_for_replay,
)
from nanobot.providers.images import prepare_message_images
from nanobot.utils.helpers import sanitize_surrogates_deep

from .google_ai_plan_oauth import get_google_ai_plan_token

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions:createPerUserQuota"
_SKIP_SIGNATURE = "skip_thought_signature_validator"
_LAYOUT = "google_ai_plan_steps"
_Json = dict[str, Any]
_TextSink = Callable[[str], Awaitable[None]]
_ToolSink = Callable[[_Json], Awaitable[None]]


def _object(value: object) -> _Json:
    if not isinstance(value, dict):
        raise ValueError("Expected a Google Interactions object")
    return cast(_Json, value)


def _objects(value: object) -> Iterable[_Json]:
    if not isinstance(value, list):
        raise ValueError("Expected a Google Interactions array")
    return (_object(item) for item in cast(list[object], value))


def _content(value: object) -> list[_Json]:
    if value is None:
        return []
    if isinstance(value, str):
        return [{"type": "text", "text": value}]
    parts: list[_Json] = []
    for block in _objects(value):
        if block.get("type") == "text":
            parts.append({"type": "text", "text": block["text"]})
        elif block.get("type") == "image_url":
            url = _object(block["image_url"])["url"]
            head, _, data = url.partition(",")
            if not (head.startswith("data:image/") and head.endswith(";base64") and data):
                raise ValueError("Google AI Ultra requires inline base64 images")
            parts.append({"type": "image", "mime_type": head[5:-7], "data": data})
        else:
            raise ValueError("Unsupported Google AI Ultra content block")
    return parts


def _text(parts: list[_Json]) -> str:
    return "\n".join(p["text"] for p in parts if p["type"] == "text")


def _assistant_steps(message: _Json, model: str, text: str, calls: dict[str, _Json]) -> list[_Json]:
    # Chat history separates text, calls and thinking. The layout references the public text
    # and calls (rather than storing another copy) so a tool turn can retain its signed order.
    ordered: list[_Json] = []
    for layout in _objects(message.get("thinking_blocks") or []):
        if layout.get("type") != _LAYOUT or layout.get("model") != model:
            continue
        offset = 0
        call_ids: list[str] = []
        for step in _objects(layout["steps"]):
            if step["type"] == "thought":
                ordered.append(step)
            elif step["type"] == "model_output":
                end = offset + step["length"]
                ordered.append({"type": "model_output", "content": _content(text[offset:end])})
                offset = end
            elif step["type"] == "function_call" and step["id"] in calls:
                call_ids.append(step["id"])
                ordered.append(calls[step["id"]])
        if offset == len(text) and call_ids == list(calls):
            break
        ordered.clear()
    else:
        if text:
            ordered.append({"type": "model_output", "content": _content(text)})
        ordered.extend(calls.values())

    steps: list[_Json] = []
    signed = False
    for step in ordered:
        if step["type"] == "function_call" and not signed:
            steps.append({"type": "thought", "signature": _SKIP_SIGNATURE})
            signed = True
        if step["type"] == "thought" and step.get("signature"):
            signed = True
        steps.append(step)
    return steps


def _request(messages: list[_Json], tools: list[_Json] | None, model: str, max_tokens: int,
             effort: str | None, choice: str | _Json | None) -> _Json:
    config: _Json = {"max_output_tokens": max_tokens}
    # The plan models reject sampling settings and cannot turn thinking off.
    level = (effort or "minimal").lower()
    if level in {"off", "none", "minimal"}:
        level = "minimal" if model == "gemini-3.5-flash-lite" else "low"
    elif level in {"xhigh", "max"}:
        level = "xhigh" if model in {"gemini-4-hydrogen", "gemini-4-neon"} else "high"
    elif level not in {"low", "medium", "high"}:
        raise ValueError("Unsupported Google AI Ultra reasoning effort")
    config.update(thinking_level=level, thinking_summaries="auto")
    steps: list[_Json] = []
    body: _Json = {"model": model, "store": False, "stream": True, "input": steps, "generation_config": config}
    if tools:
        definitions: list[_Json] = []
        for tool in tools:
            function = tool["function"]
            definitions.append({"type": "function", **{k: function[k] for k in
                                ("name", "description", "parameters") if k in function}})
        if isinstance(choice, dict):
            name = choice["function"]["name"]
            definitions = [d for d in definitions if d["name"] == name]
            if not definitions:
                raise ValueError("Requested Google AI Ultra function is not available")
            choice = "any"
        if choice is not None:
            if choice not in {"none", "auto", "any", "required"}:
                raise ValueError("Unsupported Google AI Ultra tool choice")
            config["tool_choice"] = "any" if choice == "required" else choice
        body["tools"] = definitions
    instructions: list[str] = []
    names: dict[str, str] = {}
    for message in messages:
        role = message["role"]
        parts = _content(message.get("content"))
        if role in {"system", "developer"}:
            instructions.append(_text(parts))
        elif role == "user":
            steps.append({"type": "user_input", "content": parts})
        elif role == "assistant":
            calls: dict[str, _Json] = {}
            for call in _objects(message.get("tool_calls") or []):
                call_id, function = call["id"], call["function"]
                names[call_id] = function["name"]
                calls[call_id] = {"type": "function_call", "id": call_id, "name": names[call_id],
                                  "arguments": tool_arguments_object_for_replay(function.get("arguments"))}
            steps.extend(_assistant_steps(message, model, _text(parts), calls))
        elif role == "tool":
            call_id = message["tool_call_id"]
            text = _text(parts)
            images = [p for p in parts if p["type"] == "image"]
            steps.append({"type": "function_result", "call_id": call_id, "name": message.get("name") or names[call_id],
                          "result": ((_content(text) if text else []) + images) if images else text,
                          **({"is_error": True} if message.get("is_error") else {})})
        else:
            raise ValueError("Unsupported Google AI Ultra message role")
    if instructions:
        body["system_instruction"] = "\n\n".join(instructions)
    return body


async def _events(response: httpx.Response) -> AsyncIterator[_Json]:
    data: list[str] = []
    async for line in response.aiter_lines():
        if line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
        elif not line and data:
            frame = "\n".join(data)
            data.clear()
            if frame == "[DONE]":
                return
            yield _object(json.loads(frame))


@dataclass
class _Step:
    kind: str
    id: str = ""
    name: str = ""
    signature: str = ""
    fragments: list[str] = field(default_factory=list)


def _finish(steps: Iterable[_Step], interaction: _Json, model: str) -> LLMResponse:
    status = interaction["status"]
    reason = {"completed": "stop", "requires_action": "tool_calls", "incomplete": "length"}.get(status)
    if not reason:
        raise ValueError(f"Google interaction ended with status {status}")
    layout: list[_Json] = []
    text: list[str] = []
    thoughts: list[str] = []
    calls: list[ToolCallRequest] = []
    for step in steps:
        value = "".join(step.fragments)
        if step.kind == "thought":
            layout.append({"type": "thought", **({"signature": step.signature} if step.signature else {}),
                           **({"summary": _content(value)} if value.strip() else {})})
            if value:
                thoughts.append(value)
        elif step.kind == "model_output" and value:
            text.append(value)
            layout.append({"type": "model_output", "length": len(value)})
        elif step.kind == "function_call":
            calls.append(ToolCallRequest(step.id, step.name, parse_tool_arguments(value)))
            layout.append({"type": "function_call", "id": step.id})
    usage = interaction.get("usage")
    return LLMResponse(
        content="".join(text) or None, finish_reason=reason, tool_calls=calls,
        reasoning_content="\n\n".join(thoughts) or None,
        thinking_blocks=[{"type": _LAYOUT, "model": model, "steps": layout}]
        if any(s["type"] != "model_output" for s in layout) else None,
        usage=LLMUsage.reported(input_tokens=usage.get("total_input_tokens", 0),
                                output_tokens=usage.get("total_output_tokens", 0) + usage.get("total_thought_tokens", 0),
                                cache_read_tokens=usage.get("total_cached_tokens"), total_tokens=usage.get("total_tokens"))
        if usage else None,
    )


def _api_error(error: _Json, status: int | None, token: str) -> LLMResponse:
    message = str(error.get("message") or "Request failed").replace(token, "[redacted]")[:1000]
    # Google returns 429 both for short-term limits and for daily/zero plan quota.
    retry = None
    if status == 429:
        daily = re.search(r"per day\b|reached today's .*? limit", message, re.I)
        retry = not daily and not any(
            "PerDay" in str(v.get("quotaId", ""))
            for d in _objects(error.get("details") or []) for v in _objects(d.get("violations") or [])
        )
    code = error.get("status") or error.get("code")
    label = f" ({status})" if status else ""
    return LLMResponse(content=f"Google AI Ultra{label}: {message}", finish_reason="error",
                       error_status_code=status, error_code=str(code) if code else None, error_should_retry=retry)


def _http_error(response: httpx.Response, token: str) -> LLMResponse:
    text = response.text.strip()
    if text.startswith(("event:", "data:")):
        text = next((line[5:] for line in text.splitlines() if line.startswith("data:")), "")
    try:
        payload: object = json.loads(text)
        if isinstance(payload, list):
            payload = next(iter(cast(list[object], payload)), None)
        first = _object(payload)
        error = _object(first.get("error", first))
    except ValueError:
        error = {"message": response.reason_phrase}
    return _api_error(error, response.status_code, token)


async def _consume(response: httpx.Response, model: str, token: str, on_text: _TextSink | None,
                   on_thought: _TextSink | None, on_tool: _ToolSink | None) -> LLMResponse:
    steps: dict[int, _Step] = {}
    open_steps: set[int] = set()
    async for event in _events(response):
        kind = event["event_type"]
        if kind == "interaction.completed":
            if open_steps:
                raise ValueError("Google interaction completed with unfinished steps")
            return _finish(steps.values(), event["interaction"], model)
        if kind == "error":
            error = _object(event["error"])
            code = error.get("code")
            return _api_error(error, code if isinstance(code, int) else None, token)
        if kind not in {"step.start", "step.delta", "step.stop"}:
            continue
        index = event["index"]
        if kind == "step.start":
            raw = event["step"]
            step = _Step(raw["type"], signature=raw.get("signature", ""))
            if step.kind == "function_call":
                step.id, step.name = raw["id"], raw["name"]
                if not step.id or not step.name:
                    raise ValueError("Google returned a function call without an id or name")
                if on_tool:
                    await on_tool({"index": index, "call_id": step.id, "name": step.name, "arguments_delta": ""})
            steps[index] = step
            open_steps.add(index)
        elif kind == "step.stop":
            open_steps.remove(index)
        else:
            if index not in open_steps:
                raise ValueError("Google returned a delta outside an open step")
            step, delta = steps[index], event["delta"]
            if step.kind == "thought" and delta["type"] == "thought_signature":
                step.signature += delta["signature"]
            elif step.kind == "thought" and delta["type"] == "thought_summary" and delta["content"]["type"] == "text":
                piece = delta["content"]["text"]
                step.fragments.append(piece)
                if on_thought:
                    await on_thought(piece)
            elif step.kind == "model_output" and delta["type"] == "text":
                step.fragments.append(delta["text"])
                if on_text:
                    await on_text(delta["text"])
            elif step.kind == "function_call" and delta["type"] == "arguments_delta":
                piece = delta["arguments"]
                step.fragments.append(piece)
                if on_tool:
                    await on_tool({"index": index, "call_id": step.id, "name": step.name, "arguments_delta": piece})
    raise httpx.RemoteProtocolError("Google stream ended before interaction.completed")


class GoogleAIPlanProvider(LLMProvider):
    """Send the whole transcript to the per-user quota endpoint, never to an API-key backend."""

    def __init__(self, default_model: str, proxy: str | None = None):
        super().__init__(provider_name="google_ai_plan")
        self.default_model = default_model
        self.proxy = proxy

    def get_default_model(self) -> str:
        return self.default_model

    async def chat(self, messages: list[_Json], tools: list[_Json] | None = None, model: str | None = None,
                   max_tokens: int = 4096, temperature: float = 0.7, reasoning_effort: str | None = None,
                   tool_choice: str | _Json | None = None) -> LLMResponse:
        return await self.chat_stream(messages, tools, model, max_tokens, temperature, reasoning_effort, tool_choice)

    async def chat_stream(self, messages: list[_Json], tools: list[_Json] | None = None, model: str | None = None,
                          max_tokens: int = 4096, temperature: float = 0.7, reasoning_effort: str | None = None,
                          tool_choice: str | _Json | None = None, on_content_delta: _TextSink | None = None,
                          on_thinking_delta: _TextSink | None = None, on_tool_call_delta: _ToolSink | None = None,
                          ) -> LLMResponse:
        model = (model or self.default_model).removeprefix("google-ai-plan/").removeprefix("google_ai_plan/")
        try:
            body = _request(await prepare_message_images(messages), tools, model, max_tokens, reasoning_effort, tool_choice)
            token = await asyncio.to_thread(get_google_ai_plan_token, proxy=self.proxy)
            headers = {"Authorization": f"Bearer {token}", "User-Agent": f"nanobot/{__version__}",
                       "Accept": "text/event-stream", "Content-Type": "application/json"}
            async with httpx.AsyncClient(proxy=self.proxy, trust_env=False, timeout=resolve_stream_idle_timeout_s()) as client:
                async with client.stream("POST", _ENDPOINT, headers=headers, json=sanitize_surrogates_deep(body)) as response:
                    if not response.is_success:
                        await response.aread()
                        error = _http_error(response, token)
                        error.error_retry_after_s = self._extract_retry_after_from_headers(response.headers)
                        return error
                    return await _consume(response, model, token, on_content_delta, on_thinking_delta, on_tool_call_delta)
        except Exception as exc:
            return self._error_response_from_exception(exc)
