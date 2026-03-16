"""Direct OpenAI-compatible provider — bypasses LiteLLM."""

from __future__ import annotations

import uuid
from typing import Any

import json_repair
from openai import AsyncOpenAI

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class CustomProvider(LLMProvider):

    def __init__(self, api_key: str = "no-key", api_base: str = "http://localhost:8000/v1", default_model: str = "default"):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        # Keep affinity stable for this provider instance to improve backend cache locality.
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=api_base,
            default_headers={"x-session-affinity": uuid.uuid4().hex},
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
            "stream": True,
        }
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
        if tools:
            kwargs.update(tools=tools, tool_choice=tool_choice or "auto")
        try:
            stream = await self._client.chat.completions.create(**kwargs)
            return await self._parse_stream(stream)
        except Exception as e:
            return LLMResponse(content=f"Error: {e}", finish_reason="error")

    async def _parse_stream(self, stream: Any) -> LLMResponse:
        """Collect streaming chunks and assemble into LLMResponse."""
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls_map: dict[int, dict[str, Any]] = {}  # index -> {id, name, arguments}
        finish_reason = "stop"
        usage: dict[str, int] = {}

        async for chunk in stream:
            if not chunk.choices:
                # Handle usage info in final chunk (some APIs send it separately)
                if hasattr(chunk, "usage") and chunk.usage:
                    u = chunk.usage
                    usage = {"prompt_tokens": u.prompt_tokens, "completion_tokens": u.completion_tokens, "total_tokens": u.total_tokens}
                continue

            choice = chunk.choices[0]
            delta = choice.delta

            # Collect content
            if delta.content:
                content_parts.append(delta.content)

            # Collect reasoning content if present
            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                reasoning_parts.append(delta.reasoning_content)

            # Collect tool calls
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_map:
                        tool_calls_map[idx] = {"id": "", "name": "", "arguments": ""}
                    if tc.id:
                        tool_calls_map[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_calls_map[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_calls_map[idx]["arguments"] += tc.function.arguments

            # Capture finish reason
            if choice.finish_reason:
                finish_reason = choice.finish_reason

        # Build tool_calls list
        tool_calls = []
        for idx in sorted(tool_calls_map.keys()):
            tc_data = tool_calls_map[idx]
            args = tc_data["arguments"]
            tool_calls.append(ToolCallRequest(
                id=tc_data["id"],
                name=tc_data["name"],
                arguments=json_repair.loads(args) if isinstance(args, str) and args else {}
            ))

        return LLMResponse(
            content="".join(content_parts) or None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            reasoning_content="".join(reasoning_parts) or None,
        )

    def get_default_model(self) -> str:
        return self.default_model

