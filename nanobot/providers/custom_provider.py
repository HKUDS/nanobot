"""Direct OpenAI-compatible provider — bypasses LiteLLM."""

from __future__ import annotations

from typing import Any

import json_repair
from openai import AsyncOpenAI

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class CustomProvider(LLMProvider):

    def __init__(self, api_key: str = "no-key", api_base: str = "http://localhost:8000/v1",
                 default_model: str = "default", stream: bool = False):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.stream = stream
        self._client = AsyncOpenAI(api_key=api_key, base_url=api_base)

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                   model: str | None = None, max_tokens: int = 4096, temperature: float = 0.7) -> LLMResponse:
        kwargs: dict[str, Any] = {"model": model or self.default_model, "messages": messages,
                                  "max_tokens": max(1, max_tokens), "temperature": temperature}
        if tools:
            kwargs.update(tools=tools, tool_choice="auto")
        if self.stream:
            kwargs["stream"] = True
            kwargs["stream_options"] = {"include_usage": True}
        try:
            response = await self._client.chat.completions.create(**kwargs)
            if self.stream:
                return await self._consume_stream(response)
            return self._parse(response)
        except Exception as e:
            return LLMResponse(content=f"Error: {e}", finish_reason="error")

    async def _consume_stream(self, stream: Any) -> LLMResponse:
        """Aggregate an async stream of ChatCompletionChunks into an LLMResponse."""
        content_parts: list[str] = []
        # tool_calls indexed by position: {index: {"id": ..., "name": ..., "arguments": ...}}
        tool_calls_by_index: dict[int, dict[str, str]] = {}
        finish_reason = "stop"
        usage: dict[str, int] = {}
        reasoning_parts: list[str] = []

        async for chunk in stream:
            if not chunk.choices and chunk.usage:
                # Final usage-only chunk (stream_options={"include_usage": True})
                u = chunk.usage
                usage = {"prompt_tokens": u.prompt_tokens, "completion_tokens": u.completion_tokens,
                         "total_tokens": u.total_tokens}
                continue

            if not chunk.choices:
                continue

            choice = chunk.choices[0]

            if choice.finish_reason:
                finish_reason = choice.finish_reason

            delta = choice.delta
            if delta is None:
                continue

            # Content
            if delta.content:
                content_parts.append(delta.content)

            # Reasoning content (DeepSeek-R1 etc.)
            rc = getattr(delta, "reasoning_content", None)
            if rc:
                reasoning_parts.append(rc)

            # Tool calls
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_calls_by_index:
                        tool_calls_by_index[idx] = {"id": "", "name": "", "arguments": ""}
                    entry = tool_calls_by_index[idx]
                    if tc_delta.id:
                        entry["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            entry["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            entry["arguments"] += tc_delta.function.arguments

        # Assemble tool calls
        tool_calls = [
            ToolCallRequest(
                id=tc["id"],
                name=tc["name"],
                arguments=json_repair.loads(tc["arguments"]) if tc["arguments"] else {},
            )
            for _, tc in sorted(tool_calls_by_index.items())
        ]

        return LLMResponse(
            content="".join(content_parts) or None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            reasoning_content="".join(reasoning_parts) or None,
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
            reasoning_content=getattr(msg, "reasoning_content", None),
        )

    def get_default_model(self) -> str:
        return self.default_model
