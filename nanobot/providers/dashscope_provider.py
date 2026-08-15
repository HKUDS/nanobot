"""Alibaba Cloud DashScope (Bailian) native-protocol provider.

Talks to the DashScope native HTTP API rather than the OpenAI-compatible
endpoint, which unlocks models and parameters that compatible-mode does not
expose (full multimodal parameter surface, thinking controls such as
``reasoning_effort``, native-only models). See provider docs:
https://help.aliyun.com/zh/model-studio/qwen-api-via-dashscope

Wire shape (result_format="message"):

    POST {base}/api/v1/services/aigc/multimodal-generation/generation

    {"model": "...",
     "input": {"messages": [{"role": "user", "content": "..."}]},
     "parameters": {"result_format": "message", "tools": [...], ...}}

All traffic — text-only included — goes through the multimodal-generation
endpoint: the classic ``text-generation/generation`` path has been retired on
the public ``dashscope.aliyuncs.com`` host and answers ``url error``, while
multimodal-generation serves text, images, tools, and SSE streaming.

Streaming adds ``X-DashScope-SSE: enable`` and ``incremental_output: true``;
each SSE ``data:`` line carries one output.choices[0].message delta.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, cast

import httpx

from nanobot.providers.base import (
    LLMProvider,
    LLMResponse,
    ToolCallRequest,
    parse_tool_arguments,
    resolve_stream_idle_timeout_s,
)

_DEFAULT_API_BASE = "https://dashscope.aliyuncs.com"
_GENERATION_PATH = "/api/v1/services/aigc/multimodal-generation/generation"
_SSE_HEADERS = {
    "Accept": "text/event-stream",
    "X-DashScope-SSE": "enable",
}
# Non-streaming requests must still allow long thinking turns.
_REQUEST_TIMEOUT_S = httpx.Timeout(300.0, connect=15.0)

_FINISH_REASONS = {
    "stop": "stop",
    "length": "length",
    "tool_calls": "tool_calls",
    "function_call": "tool_calls",
    "content_filter": "content_filter",
}


class DashScopeProvider(LLMProvider):
    """LLM provider for the DashScope native protocol (Bailian)."""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "qwen3.8-max",
        *,
        extra_headers: dict[str, str] | None = None,
        extra_body: dict[str, Any] | None = None,
        proxy: str | None = None,
        client: Any | None = None,
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self._extra_headers = dict(extra_headers or {})
        self._extra_body = dict(extra_body or {})
        self._proxy = proxy
        self._client = client

    def _http_client(self) -> Any:
        if self._client is not None:
            return self._client
        headers = {"Authorization": f"Bearer {self.api_key or ''}"}
        headers.update(self._extra_headers)
        self._client = httpx.AsyncClient(
            base_url=self.api_base or _DEFAULT_API_BASE,
            headers=headers,
            timeout=_REQUEST_TIMEOUT_S,
            proxy=self._proxy,
        )
        return self._client

    # ------------------------------------------------------------------
    # Request building
    # ------------------------------------------------------------------

    @classmethod
    def _convert_user_content(
        cls, content: Any
    ) -> tuple[Any, bool]:
        """Convert OpenAI-style user content to the DashScope shape.

        Returns ``(converted, is_multimodal)``. Multimodal content becomes a
        list of ``{"text": ...}`` / ``{"image": url}`` objects.
        """
        if not isinstance(content, list):
            return content, False
        blocks: list[dict[str, Any]] = []
        has_image = False
        for raw_block in cast(list[object], content):
            if not isinstance(raw_block, dict):
                continue
            block = cast(dict[str, Any], raw_block)
            block_type = block.get("type")
            if block_type == "text":
                text = block.get("text")
                if isinstance(text, str):
                    blocks.append({"text": text})
            elif block_type == "image_url":
                image_url = cast(dict[str, Any], block.get("image_url") or {})
                url = image_url.get("url")
                if isinstance(url, str) and url:
                    blocks.append({"image": url})
                    has_image = True
        if has_image:
            return blocks, True
        return "".join(str(b.get("text") or "") for b in blocks), False

    @classmethod
    def _convert_messages(
        cls, messages: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], bool]:
        converted: list[dict[str, Any]] = []
        has_multimodal = False
        for msg in messages:
            role = msg.get("role")
            if role == "user":
                content, multimodal = cls._convert_user_content(msg.get("content"))
                has_multimodal = has_multimodal or multimodal
                converted.append({"role": "user", "content": content})
            elif role == "assistant":
                out: dict[str, Any] = {"role": "assistant", "content": msg.get("content")}
                tool_calls = msg.get("tool_calls")
                if isinstance(tool_calls, list) and tool_calls:
                    out["tool_calls"] = tool_calls
                converted.append(out)
            elif role == "tool":
                converted.append({
                    "role": "tool",
                    "content": msg.get("content") or "",
                    "tool_call_id": msg.get("tool_call_id") or "",
                })
            elif role == "system":
                converted.append({"role": "system", "content": msg.get("content") or ""})
        return converted, has_multimodal

    @staticmethod
    def _convert_tool_choice(tool_choice: str | dict[str, Any] | None) -> Any:
        if tool_choice is None or tool_choice == "auto":
            return None
        if isinstance(tool_choice, dict):
            return tool_choice
        if tool_choice == "none":
            return "none"
        if tool_choice == "required":
            return "required"
        return None

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        max_tokens: int,
        temperature: float,
        reasoning_effort: str | None,
        tool_choice: str | dict[str, Any] | None,
        *,
        stream: bool,
    ) -> tuple[dict[str, Any], str]:
        ds_messages, _has_multimodal = self._convert_messages(messages)
        parameters: dict[str, Any] = {
            "result_format": "message",
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if stream:
            parameters["incremental_output"] = True
        if reasoning_effort is not None:
            parameters["enable_thinking"] = True
            parameters["reasoning_effort"] = reasoning_effort
        if tools:
            # DashScope keeps tools and tool_choice inside `parameters`, and
            # requires result_format="message" (already set) for tool calls.
            parameters["tools"] = tools
            converted_choice = self._convert_tool_choice(tool_choice)
            if converted_choice is not None:
                parameters["tool_choice"] = converted_choice
        parameters.update(self._extra_body)
        payload = {
            "model": model or self.default_model,
            "input": {"messages": ds_messages},
            "parameters": parameters,
        }
        return payload, _GENERATION_PATH

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _usage(usage: object) -> dict[str, int]:
        if not isinstance(usage, dict):
            return {}
        data = cast(dict[str, Any], usage)
        result: dict[str, int] = {}
        for source, target in (
            ("input_tokens", "prompt_tokens"),
            ("output_tokens", "completion_tokens"),
            ("total_tokens", "total_tokens"),
        ):
            value = data.get(source)
            if isinstance(value, int):
                result[target] = value
        details = data.get("prompt_tokens_details")
        if isinstance(details, dict):
            cached = cast(dict[str, Any], details).get("cached_tokens")
            if isinstance(cached, int):
                result["cached_tokens"] = cached
        return result

    @staticmethod
    def _finish_reason(value: Any) -> str:
        token = str(value or "").strip().lower()
        return _FINISH_REASONS.get(token, "stop")

    @classmethod
    def _parse_tool_calls(cls, raw: object) -> list[ToolCallRequest]:
        calls: list[ToolCallRequest] = []
        if not isinstance(raw, list):
            return calls
        for raw_item in cast(list[object], raw):
            if not isinstance(raw_item, dict):
                continue
            item = cast(dict[str, Any], raw_item)
            function = cast(dict[str, Any], item.get("function") or {})
            arguments = parse_tool_arguments(function.get("arguments"))
            calls.append(ToolCallRequest(
                id=str(item.get("id") or ""),
                name=str(function.get("name") or ""),
                arguments=arguments,
            ))
        return calls

    @classmethod
    def _message_content(cls, content: object) -> str | None:
        if isinstance(content, str):
            return content or None
        if isinstance(content, list):
            text = "".join(
                str(cast(dict[str, Any], part).get("text") or "")
                for part in cast(list[object], content)
                if isinstance(part, dict)
            )
            return text or None
        return None

    @classmethod
    def _error_response(
        cls,
        *,
        message: str,
        status_code: int | None = None,
        code: str | None = None,
        kind: str | None = None,
    ) -> LLMResponse:
        should_retry: bool | None = None
        if kind in ("timeout", "connection"):
            should_retry = True
        elif status_code is not None:
            should_retry = status_code == 429 or status_code >= 500
        code_token = (code or "").lower()
        if any(token in code_token for token in ("throttl", "timeout", "unavailable")):
            should_retry = True
        elif should_retry is None:
            should_retry = False
        return LLMResponse(
            content=f"Error: {message[:500]}",
            finish_reason="error",
            error_status_code=status_code,
            error_kind=kind,
            error_type=code_token or None,
            error_code=code_token or None,
            error_should_retry=should_retry,
        )

    @classmethod
    def _handle_http_error(cls, status_code: int, body: str) -> LLMResponse:
        code: str | None = None
        message = body.strip()[:500]
        try:
            parsed = json.loads(body) if body.strip() else None
        except (json.JSONDecodeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            data = cast(dict[str, Any], parsed)
            code = str(data.get("code") or "") or None
            message = str(data.get("message") or "") or message
        return cls._error_response(
            message=message,
            status_code=status_code,
            code=code,
        )

    @classmethod
    def _parse_response(cls, data: dict[str, Any]) -> LLMResponse:
        output = cast(dict[str, Any], data.get("output") or {})
        usage = cls._usage(output.get("usage"))
        if data.get("code") or data.get("message"):
            # DashScope reports some logical errors with HTTP 200.
            return cls._error_response(
                message=str(data.get("message") or data.get("code")),
                code=str(data.get("code") or "") or None,
            )
        choices = output.get("choices")
        if not isinstance(choices, list) or not choices:
            return LLMResponse(content=None, finish_reason="stop", usage=usage)
        items = cast(list[object], choices)
        choice = cast(dict[str, Any], items[0]) if isinstance(items[0], dict) else {}
        message = cast(dict[str, Any], choice.get("message") or {})
        reasoning = message.get("reasoning_content")
        return LLMResponse(
            content=cls._message_content(message.get("content")),
            tool_calls=cls._parse_tool_calls(message.get("tool_calls")),
            finish_reason=cls._finish_reason(choice.get("finish_reason")),
            usage=usage,
            reasoning_content=str(reasoning) if reasoning else None,
        )

    @classmethod
    def _handle_exception(cls, e: Exception) -> LLMResponse:
        if isinstance(e, httpx.HTTPStatusError):
            return cls._handle_http_error(
                e.response.status_code,
                e.response.text,
            )
        name = e.__class__.__name__.lower()
        kind = None
        if "timeout" in name:
            kind = "timeout"
        elif "connect" in name or "request" in name:
            kind = "connection"
        return cls._error_response(
            message=str(e),
            kind=kind,
            code="timeout" if kind == "timeout" else None,
        )

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    @classmethod
    def _apply_stream_chunk(
        cls,
        chunk: dict[str, Any],
        *,
        content_parts: list[str],
        reasoning_parts: list[str],
        tool_buffers: dict[int, dict[str, Any]],
        state: dict[str, Any],
    ) -> tuple[str, str, dict[str, Any] | None]:
        """Fold one SSE chunk into accumulator state; return delta callbacks.

        Returns ``(content_delta, reasoning_delta, tool_call_delta)`` where
        empty strings / None mean "nothing to emit".
        """
        output = cast(dict[str, Any], chunk.get("output") or {})
        usage = cls._usage(output.get("usage"))
        if usage:
            state["usage"] = usage
        choices = output.get("choices")
        if not isinstance(choices, list) or not choices:
            return "", "", None
        items = cast(list[object], choices)
        choice = cast(dict[str, Any], items[0]) if isinstance(items[0], dict) else {}
        finish = choice.get("finish_reason")
        if finish not in (None, "", "null"):
            state["finish_reason"] = cls._finish_reason(finish)
        message = cast(dict[str, Any], choice.get("message") or {})
        content = message.get("content")
        content_delta = ""
        if isinstance(content, str) and content:
            content_parts.append(content)
            content_delta = content
        elif isinstance(content, list):
            # Multimodal models stream content as an array of {"text": ...}
            # parts; each part arrives complete, so track per-slot text and
            # emit only the growth (works for once-complete and incremental).
            slots: list[str] = state.setdefault("content_slots", [])
            part_texts: list[str] = []
            for raw_part in cast(list[object], content):
                if isinstance(raw_part, dict):
                    text = cast(dict[str, Any], raw_part).get("text")
                    part_texts.append(text if isinstance(text, str) else "")
            while len(slots) < len(part_texts):
                slots.append("")
            for i, text in enumerate(part_texts):
                seen = slots[i]
                if text.startswith(seen) and len(text) > len(seen):
                    delta = text[len(seen):]
                    slots[i] = text
                    content_parts.append(delta)
                    content_delta += delta
                elif text and text != seen:
                    slots[i] = text
                    content_parts.append(text)
                    content_delta += text
        reasoning = message.get("reasoning_content")
        reasoning_delta = ""
        if isinstance(reasoning, str) and reasoning:
            reasoning_parts.append(reasoning)
            reasoning_delta = reasoning
        tool_delta: dict[str, Any] | None = None
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            for raw_item in cast(list[object], tool_calls):
                if not isinstance(raw_item, dict):
                    continue
                item = cast(dict[str, Any], raw_item)
                index = item.get("index")
                idx = index if isinstance(index, int) else 0
                buffer = tool_buffers.setdefault(
                    idx, {"id": "", "name": "", "arguments": ""}
                )
                call_id = item.get("id")
                if isinstance(call_id, str) and call_id:
                    buffer["id"] = call_id
                function = cast(dict[str, Any], item.get("function") or {})
                name = function.get("name")
                if isinstance(name, str) and name and not buffer["name"]:
                    buffer["name"] = name
                args = function.get("arguments")
                args_delta = ""
                if isinstance(args, str) and args:
                    buffer["arguments"] += args
                    args_delta = args
                tool_delta = {
                    "index": idx,
                    "call_id": buffer["id"],
                    "name": buffer["name"],
                    "arguments_delta": args_delta,
                }
        return content_delta, reasoning_delta, tool_delta

    @classmethod
    def _stream_result(
        cls,
        *,
        content_parts: list[str],
        reasoning_parts: list[str],
        tool_buffers: dict[int, dict[str, Any]],
        state: dict[str, Any],
    ) -> LLMResponse:
        tool_calls: list[ToolCallRequest] = []
        for idx in sorted(tool_buffers):
            buffer = tool_buffers[idx]
            arguments: Any = {}
            if buffer["arguments"]:
                arguments = parse_tool_arguments(buffer["arguments"])
            tool_calls.append(ToolCallRequest(
                id=buffer["id"],
                name=buffer["name"],
                arguments=arguments,
            ))
        return LLMResponse(
            content="".join(content_parts) or None,
            tool_calls=tool_calls,
            finish_reason=str(state.get("finish_reason") or "stop"),
            usage=cast(dict[str, int], state.get("usage") or {}),
            reasoning_content="".join(reasoning_parts) or None,
        )

    # ------------------------------------------------------------------
    # LLMProvider API
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        if not self.api_key:
            return self._error_response(
                message="DashScope provider requires an API key "
                "(providers.dashscope_native.api_key or DASHSCOPE_API_KEY).",
                code="missing_api_key",
            )
        try:
            payload, path = self._build_payload(
                messages,
                tools,
                model,
                max_tokens,
                temperature,
                reasoning_effort,
                tool_choice,
                stream=False,
            )
            client = self._http_client()
            response = await client.post(path, json=payload)
            if response.status_code != 200:
                return self._handle_http_error(response.status_code, response.text)
            return self._parse_response(response.json())
        except Exception as e:
            return self._handle_exception(e)

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
        on_thinking_delta: Callable[[str], Awaitable[None]] | None = None,
        on_tool_call_delta: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        if not self.api_key:
            return self._error_response(
                message="DashScope provider requires an API key "
                "(providers.dashscope_native.api_key or DASHSCOPE_API_KEY).",
                code="missing_api_key",
            )
        idle_timeout_s = resolve_stream_idle_timeout_s()
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_buffers: dict[int, dict[str, Any]] = {}
        state: dict[str, Any] = {}
        try:
            payload, path = self._build_payload(
                messages,
                tools,
                model,
                max_tokens,
                temperature,
                reasoning_effort,
                tool_choice,
                stream=True,
            )
            client = self._http_client()
            async with client.stream(
                "POST", path, json=payload, headers=_SSE_HEADERS
            ) as response:
                if response.status_code != 200:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    return self._handle_http_error(response.status_code, body)
                lines = response.aiter_lines().__aiter__()
                while True:
                    try:
                        line = await asyncio.wait_for(
                            lines.__anext__(), timeout=idle_timeout_s
                        )
                    except StopAsyncIteration:
                        break
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    data_str = line[len("data:"):].strip()
                    if not data_str or data_str == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(data_str)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if not isinstance(chunk, dict):
                        continue
                    content_delta, reasoning_delta, tool_delta = (
                        self._apply_stream_chunk(
                            cast(dict[str, Any], chunk),
                            content_parts=content_parts,
                            reasoning_parts=reasoning_parts,
                            tool_buffers=tool_buffers,
                            state=state,
                        )
                    )
                    if content_delta and on_content_delta:
                        await on_content_delta(content_delta)
                    if reasoning_delta and on_thinking_delta:
                        await on_thinking_delta(reasoning_delta)
                    if tool_delta is not None and on_tool_call_delta:
                        await on_tool_call_delta(tool_delta)
            return self._stream_result(
                content_parts=content_parts,
                reasoning_parts=reasoning_parts,
                tool_buffers=tool_buffers,
                state=state,
            )
        except asyncio.TimeoutError:
            return LLMResponse(
                content=(
                    f"Error calling LLM: stream stalled for more than "
                    f"{idle_timeout_s:g} seconds"
                ),
                finish_reason="error",
                error_kind="timeout",
            )
        except Exception as e:
            return self._handle_exception(e)

    def get_default_model(self) -> str:
        return self.default_model
