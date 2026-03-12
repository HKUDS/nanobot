"""Direct OpenAI-compatible provider — bypasses LiteLLM."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import json_repair
from openai import AsyncOpenAI

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class CustomProvider(LLMProvider):

    def __init__(self, api_key: str = "no-key", api_base: str = "http://localhost:8000/v1", default_model: str = "default"):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=api_base,
            default_headers={"x-session-affinity": uuid.uuid4().hex},
        )

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                   model: str | None = None, max_tokens: int = 4096, temperature: float = 0.7,
                   reasoning_effort: str | None = None, on_text_delta=None,
                   tool_choice: str | dict[str, Any] | None = None) -> LLMResponse:
        upstream_model = model or self.default_model
        if isinstance(upstream_model, str) and upstream_model.startswith("custom/"):
            upstream_model = upstream_model.split("/", 1)[1]
        kwargs: dict[str, Any] = {
            "model": upstream_model,
            "messages": self._sanitize_empty_content(messages),
            "max_tokens": max(1, max_tokens),
            "temperature": temperature,
        }
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
        if tools:
            kwargs.update(tools=tools, tool_choice=tool_choice or "auto")
        try:
            if on_text_delta:
                return await self._stream_via_sdk(kwargs, on_text_delta)
            return self._parse(await self._client.chat.completions.create(**kwargs))
        except Exception as e:
            fallback = await self._chat_via_http(kwargs, on_text_delta=on_text_delta)
            if fallback is not None:
                return fallback
            return LLMResponse(content=f"Error: {e}", finish_reason="error")

    async def _stream_via_sdk(self, kwargs: dict[str, Any], on_text_delta) -> LLMResponse:
        stream = await self._client.chat.completions.create(stream=True, **kwargs)
        return await self._consume_openai_stream(stream, on_text_delta=on_text_delta)

    async def _chat_via_http(self, kwargs: dict[str, Any], on_text_delta=None) -> LLMResponse | None:
        """Fallback for OpenAI-compatible endpoints that reject the official SDK."""
        try:
            base = (self.api_base or "").rstrip("/")
            if not base:
                return None
            url = f"{base}/chat/completions"
            request_kwargs = dict(kwargs)
            if on_text_delta:
                request_kwargs["stream"] = True
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            }
            async with httpx.AsyncClient(timeout=60.0) as client:
                if on_text_delta:
                    async with client.stream("POST", url, headers=headers, json=request_kwargs) as resp:
                        resp.raise_for_status()
                        return await self._consume_http_stream(resp, on_text_delta=on_text_delta)
                resp = await client.post(url, headers=headers, json=request_kwargs)
                resp.raise_for_status()
                data = resp.json()

            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            tool_calls = []
            for tc in message.get("tool_calls") or []:
                function = tc.get("function") or {}
                arguments = function.get("arguments") or {}
                if isinstance(arguments, str):
                    arguments = json_repair.loads(arguments)
                tool_calls.append(
                    ToolCallRequest(
                        id=tc.get("id", ""),
                        name=function.get("name", ""),
                        arguments=arguments,
                    )
                )

            usage = data.get("usage") or {}
            return LLMResponse(
                content=message.get("content"),
                tool_calls=tool_calls,
                finish_reason=choice.get("finish_reason") or "stop",
                usage={
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                },
                reasoning_content=message.get("reasoning_content"),
            )
        except Exception:
            return None

    async def _consume_openai_stream(self, stream: Any, on_text_delta) -> LLMResponse:
        content = ""
        finish_reason = "stop"
        streamed_output = False
        tool_call_buffers: dict[int, dict[str, Any]] = {}

        async for chunk in stream:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            choice = choices[0]
            delta = getattr(choice, "delta", None)
            if delta is None:
                continue

            text_delta = getattr(delta, "content", None)
            if text_delta:
                content += text_delta
                await on_text_delta(text_delta)
                streamed_output = True
            else:
                reasoning_delta = getattr(delta, "reasoning_content", None)
                if reasoning_delta:
                    await on_text_delta(reasoning_delta)
                    streamed_output = True

            for tc in getattr(delta, "tool_calls", None) or []:
                index = getattr(tc, "index", 0) or 0
                buf = tool_call_buffers.setdefault(index, {"id": "", "name": "", "arguments": ""})
                if getattr(tc, "id", None):
                    buf["id"] = tc.id
                fn = getattr(tc, "function", None)
                if fn is not None:
                    if getattr(fn, "name", None):
                        buf["name"] = fn.name
                    if getattr(fn, "arguments", None):
                        buf["arguments"] += fn.arguments

            if getattr(choice, "finish_reason", None):
                finish_reason = choice.finish_reason or "stop"

        tool_calls: list[ToolCallRequest] = []
        for buf in tool_call_buffers.values():
            raw_arguments = buf["arguments"] or "{}"
            try:
                arguments = json_repair.loads(raw_arguments)
            except Exception:
                arguments = {"raw": raw_arguments}
            tool_calls.append(
                ToolCallRequest(
                    id=buf["id"] or "",
                    name=buf["name"] or "",
                    arguments=arguments,
                )
            )

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            streamed_output=streamed_output,
        )

    async def _consume_http_stream(self, response: httpx.Response, on_text_delta) -> LLMResponse:
        content = ""
        finish_reason = "stop"
        streamed_output = False
        tool_call_buffers: dict[int, dict[str, Any]] = {}
        buffer: list[str] = []

        async for line in response.aiter_lines():
            if line == "":
                if not buffer:
                    continue
                data_lines = [part[5:].strip() for part in buffer if part.startswith("data:")]
                buffer = []
                payload = "\n".join(data_lines).strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    event = json.loads(payload)
                except Exception:
                    continue

                choice = (event.get("choices") or [{}])[0]
                delta = choice.get("delta") or {}
                text_delta = delta.get("content")
                if text_delta:
                    content += text_delta
                    await on_text_delta(text_delta)
                    streamed_output = True
                else:
                    reasoning_delta = delta.get("reasoning_content")
                    if reasoning_delta:
                        await on_text_delta(reasoning_delta)
                        streamed_output = True

                for tc in delta.get("tool_calls") or []:
                    index = tc.get("index", 0) or 0
                    buf = tool_call_buffers.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    if tc.get("id"):
                        buf["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        buf["name"] = fn["name"]
                    if fn.get("arguments"):
                        buf["arguments"] += fn["arguments"]

                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]
                continue
            buffer.append(line)

        tool_calls: list[ToolCallRequest] = []
        for buf in tool_call_buffers.values():
            raw_arguments = buf["arguments"] or "{}"
            try:
                arguments = json_repair.loads(raw_arguments)
            except Exception:
                arguments = {"raw": raw_arguments}
            tool_calls.append(
                ToolCallRequest(
                    id=buf["id"] or "",
                    name=buf["name"] or "",
                    arguments=arguments,
                )
            )

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            streamed_output=streamed_output,
        )

    def _parse(self, response: Any) -> LLMResponse:
        choice = response.choices[0]
        msg = choice.message
        tool_calls = [
            ToolCallRequest(id=tc.id, name=tc.function.name,
                            arguments=json_repair.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments)
            for tc in (msg.tool_calls or [])
        ]
        u = response.usage
        return LLMResponse(
            content=msg.content, tool_calls=tool_calls, finish_reason=choice.finish_reason or "stop",
            usage={"prompt_tokens": u.prompt_tokens, "completion_tokens": u.completion_tokens, "total_tokens": u.total_tokens} if u else {},
            reasoning_content=getattr(msg, "reasoning_content", None) or None,
        )

    def get_default_model(self) -> str:
        return self.default_model
