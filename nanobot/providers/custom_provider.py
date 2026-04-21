"""Direct OpenAI-compatible provider — bypasses LiteLLM."""

from __future__ import annotations

from typing import Any

import time as _time

import json_repair
from openai import AsyncOpenAI

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class CustomProvider(LLMProvider):

    def __init__(self, api_key: str = "no-key", api_base: str = "http://localhost:8000/v1", default_model: str = "default"):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self._client = AsyncOpenAI(api_key=api_key, base_url=api_base)

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                   model: str | None = None, max_tokens: int = 4096, temperature: float = 0.7) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": self._sanitize_empty_content(messages),
            "max_tokens": max(1, max_tokens),
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs.update(tools=tools, tool_choice="auto")
        try:
            return await self._stream(kwargs)
        except Exception as e:
            return LLMResponse(content=f"Error: {e}", finish_reason="error")

    async def _stream(self, kwargs: dict[str, Any]) -> LLMResponse:
        """Stream a chat completion, recording TTFT at the first content chunk."""
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        finish_reason = "stop"
        usage: dict[str, int] = {}
        ttft_ms: float | None = None
        # tool call accumulator: index -> {id, name, args}
        tc_buf: dict[int, dict] = {}

        _start = _time.perf_counter()
        stream = await self._client.chat.completions.create(**kwargs)
        async for chunk in stream:
            # Usage appears in final chunk when stream_options include_usage=True
            if getattr(chunk, "usage", None):
                u = chunk.usage
                usage = {
                    "prompt_tokens": u.prompt_tokens or 0,
                    "completion_tokens": u.completion_tokens or 0,
                    "total_tokens": u.total_tokens or 0,
                }
            choices = chunk.choices
            if not choices:
                continue
            delta = choices[0].delta
            if choices[0].finish_reason:
                finish_reason = choices[0].finish_reason

            # TTFT: first chunk carrying any content or tool call delta
            has_content = bool(getattr(delta, "content", None))
            has_reasoning = bool(getattr(delta, "reasoning_content", None))
            has_tool = bool(getattr(delta, "tool_calls", None))
            if ttft_ms is None and (has_content or has_reasoning or has_tool):
                ttft_ms = (_time.perf_counter() - _start) * 1000

            if has_reasoning:
                reasoning_parts.append(delta.reasoning_content)
            if has_content:
                content_parts.append(delta.content)
            if has_tool:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tc_buf:
                        tc_buf[idx] = {"id": "", "name": "", "args": []}
                    if tc_delta.id:
                        tc_buf[idx]["id"] = tc_delta.id
                    if tc_delta.function.name:
                        tc_buf[idx]["name"] = tc_delta.function.name
                    if tc_delta.function.arguments:
                        tc_buf[idx]["args"].append(tc_delta.function.arguments)

        content = "".join(content_parts) or None
        reasoning = "".join(reasoning_parts) or None
        tool_calls = [
            ToolCallRequest(
                id=buf["id"],
                name=buf["name"],
                arguments=json_repair.loads("".join(buf["args"])),
            )
            for buf in tc_buf.values()
        ]
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            reasoning_content=reasoning,
            ttft_ms=ttft_ms,
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

