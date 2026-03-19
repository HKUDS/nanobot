"""Direct OpenAI-compatible provider — bypasses LiteLLM."""

from __future__ import annotations

import uuid
from typing import Any, Awaitable, Callable

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
        # Keep affinity stable for this provider instance to improve backend cache locality,
        # while still letting users attach provider-specific headers for custom gateways.
        default_headers = {
            "x-session-affinity": uuid.uuid4().hex,
            **(extra_headers or {}),
        }
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=api_base,
            default_headers=default_headers,
        )

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                   model: str | None = None, max_tokens: int = 4096, temperature: float = 0.7,
                   reasoning_effort: str | None = None,
                   tool_choice: str | dict[str, Any] | None = None) -> LLMResponse:
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
        try:
            return self._parse(await self._client.chat.completions.create(**kwargs))
        except Exception as e:
            return LLMResponse(content=f"Error: {e}", finish_reason="error")

    def _parse(self, response: Any) -> LLMResponse:
        if not response.choices:
            return LLMResponse(
                content="Error: API returned empty choices. This may indicate a temporary service issue or an invalid model response.",
                finish_reason="error"
            )
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

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        on_token: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        """Stream response tokens using the OpenAI streaming API."""
        kwargs: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": self._sanitize_empty_content(messages),
            "max_tokens": max(1, self.generation.max_tokens),
            "temperature": self.generation.temperature,
            "stream": True,
        }
        if tools:
            kwargs.update(tools=tools, tool_choice="auto")

        try:
            accumulated_content = ""
            accumulated_tool_calls: dict[int, dict] = {}
            finish_reason = "stop"

            stream = await self._client.chat.completions.create(**kwargs)
            async for chunk in stream:
                choice = chunk.choices[0]
                delta = choice.delta

                if delta.content:
                    accumulated_content += delta.content
                    if on_token:
                        await on_token(delta.content)

                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in accumulated_tool_calls:
                            accumulated_tool_calls[idx] = {"id": "", "name": "", "args": ""}
                        if tc_delta.id:
                            accumulated_tool_calls[idx]["id"] = tc_delta.id
                        if tc_delta.function and tc_delta.function.name:
                            accumulated_tool_calls[idx]["name"] = tc_delta.function.name
                        if tc_delta.function and tc_delta.function.arguments:
                            accumulated_tool_calls[idx]["args"] += tc_delta.function.arguments

                if choice.finish_reason:
                    finish_reason = choice.finish_reason

            tool_calls = [
                ToolCallRequest(
                    id=tc["id"] or f"tc_{idx}",
                    name=tc["name"],
                    arguments=json_repair.loads(tc["args"]) if tc["args"] else {},
                )
                for idx, tc in sorted(accumulated_tool_calls.items())
            ]
            return LLMResponse(
                content=accumulated_content or None,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
            )
        except Exception as e:
            return LLMResponse(content=f"Error: {e}", finish_reason="error")

    def get_default_model(self) -> str:
        return self.default_model

