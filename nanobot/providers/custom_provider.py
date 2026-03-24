"""Direct OpenAI-compatible provider — bypasses LiteLLM."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import json_repair
from openai import AsyncOpenAI

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class CustomProvider(LLMProvider):

    def __init__(
        self,
        api_key: str = "no-key",
        api_base: str = "http://localhost:8000/v1",
        default_model: str = "default",
        extra_headers: dict[str, str] | None = None,
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=api_base,
            default_headers={
                "x-session-affinity": uuid.uuid4().hex,
                **(extra_headers or {}),
            },
        )

    def _build_kwargs(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None,
        model: str | None, max_tokens: int, temperature: float,
        reasoning_effort: str | None, tool_choice: str | dict[str, Any] | None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": self._sanitize_empty_content(messages),
            "max_tokens": max(1, max_tokens),
            "temperature": temperature,
        }
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
        if tools:
            kwargs.update(tools=tools, tool_choice=tool_choice or "auto")
        return kwargs

    def _handle_error(self, e: Exception) -> LLMResponse:
        body = getattr(e, "doc", None) or getattr(getattr(e, "response", None), "text", None)
        msg = f"Error: {body.strip()[:500]}" if body and body.strip() else f"Error: {e}"
        return LLMResponse(content=msg, finish_reason="error")

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                   model: str | None = None, max_tokens: int = 4096, temperature: float = 0.7,
                   reasoning_effort: str | None = None,
                   tool_choice: str | dict[str, Any] | None = None) -> LLMResponse:
        kwargs = self._build_kwargs(messages, tools, model, max_tokens, temperature, reasoning_effort, tool_choice)
        try:
            return self._parse(await self._client.chat.completions.create(**kwargs))
        except Exception as e:
            return self._handle_error(e)

    async def chat_stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
        model: str | None = None, max_tokens: int = 4096, temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        kwargs = self._build_kwargs(messages, tools, model, max_tokens, temperature, reasoning_effort, tool_choice)
        kwargs["stream"] = True
        try:
            stream = await self._client.chat.completions.create(**kwargs)
            chunks: list[Any] = []
            async for chunk in stream:
                chunks.append(chunk)
                if on_content_delta and chunk.choices:
                    text = getattr(chunk.choices[0].delta, "content", None)
                    if text:
                        await on_content_delta(text)
            return self._parse_chunks(chunks)
        except Exception as e:
            return self._handle_error(e)

    def _parse(self, response: Any) -> LLMResponse:
        if not response.choices:
            return LLMResponse(
                content="Error: API returned empty choices.",
                finish_reason="error",
            )
        choice = response.choices[0]
        msg = choice.message
        tool_calls = [
            ToolCallRequest(
                id=tc.id, name=tc.function.name,
                arguments=json_repair.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments,
            )
            for tc in (msg.tool_calls or [])
        ]
        u = response.usage
        return LLMResponse(
            content=msg.content, tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage={"prompt_tokens": u.prompt_tokens, "completion_tokens": u.completion_tokens, "total_tokens": u.total_tokens} if u else {},
            reasoning_content=getattr(msg, "reasoning_content", None) or None,
        )

    def _parse_chunks(self, chunks: list[Any]) -> LLMResponse:
        """Reassemble streamed chunks into a single LLMResponse."""
        content_parts: list[str] = []
        tc_bufs: dict[int, dict[str, str]] = {}
        finish_reason = "stop"
        usage: dict[str, int] = {}

        for chunk in chunks:
            if not chunk.choices:
                if hasattr(chunk, "usage") and chunk.usage:
                    u = chunk.usage
                    usage = {"prompt_tokens": u.prompt_tokens or 0, "completion_tokens": u.completion_tokens or 0,
                             "total_tokens": u.total_tokens or 0}
                continue
            choice = chunk.choices[0]
            if choice.finish_reason:
                finish_reason = choice.finish_reason
            delta = choice.delta
            if delta and delta.content:
                content_parts.append(delta.content)
            for tc in (delta.tool_calls or []) if delta else []:
                buf = tc_bufs.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                if tc.id:
                    buf["id"] = tc.id
                if tc.function and tc.function.name:
                    buf["name"] = tc.function.name
                if tc.function and tc.function.arguments:
                    buf["arguments"] += tc.function.arguments

        return LLMResponse(
            content="".join(content_parts) or None,
            tool_calls=[
                ToolCallRequest(id=b["id"], name=b["name"], arguments=json_repair.loads(b["arguments"]) if b["arguments"] else {})
                for b in tc_bufs.values()
            ],
            finish_reason=finish_reason,
            usage=usage,
        )

    def get_default_model(self) -> str:
        return self.default_model
