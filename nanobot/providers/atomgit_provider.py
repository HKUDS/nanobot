"""AtomGit (api-ai.gitcode.com) provider — bypasses LiteLLM."""

from __future__ import annotations

import uuid
from typing import Any

import json_repair
from openai import AsyncOpenAI

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class AtomGitProvider(LLMProvider):
    """Provider for AtomGit's OpenAI-compatible API (api-ai.gitcode.com).

    The AtomGit API always returns responses in SSE (Server-Sent Events) format
    even when ``stream=False`` is requested, so this provider always uses
    streaming mode and accumulates the chunks into a single response.
    """

    DEFAULT_API_BASE = "https://api-ai.gitcode.com/v1"

    def __init__(
        self,
        api_key: str = "no-key",
        api_base: str = DEFAULT_API_BASE,
        default_model: str = "zai/glm-5",
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=api_base,
            default_headers={"x-session-affinity": uuid.uuid4().hex},
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
    ) -> LLMResponse:
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
            kwargs.update(tools=tools, tool_choice="auto")
        try:
            return await self._collect_stream(kwargs)
        except Exception as e:
            return LLMResponse(content=f"Error: {e}", finish_reason="error")

    async def _collect_stream(self, kwargs: dict[str, Any]) -> LLMResponse:
        """Stream the response and accumulate chunks into a single LLMResponse."""
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        finish_reason: str = "stop"
        usage: dict[str, int] = {}

        # tool-call accumulators keyed by index
        tc_ids: dict[int, str] = {}
        tc_names: dict[int, str] = {}
        tc_args: dict[int, list[str]] = {}

        stream = await self._client.chat.completions.create(**kwargs)
        async for chunk in stream:
            if not chunk.choices:
                # Some providers send usage-only chunks with no choices
                if hasattr(chunk, "usage") and chunk.usage:
                    u = chunk.usage
                    usage = {
                        "prompt_tokens": u.prompt_tokens or 0,
                        "completion_tokens": u.completion_tokens or 0,
                        "total_tokens": u.total_tokens or 0,
                    }
                continue

            choice = chunk.choices[0]
            if choice.finish_reason:
                finish_reason = choice.finish_reason

            delta = choice.delta
            if delta.content:
                content_parts.append(delta.content)

            reasoning = getattr(delta, "reasoning", None) or getattr(delta, "reasoning_content", None)
            if reasoning:
                reasoning_parts.append(reasoning)

            for tc in delta.tool_calls or []:
                idx = tc.index
                if tc.id:
                    tc_ids[idx] = tc.id
                if tc.function and tc.function.name:
                    tc_names[idx] = tc.function.name
                if tc.function and tc.function.arguments:
                    tc_args.setdefault(idx, []).append(tc.function.arguments)

        tool_calls = [
            ToolCallRequest(
                id=tc_ids.get(i, f"call_{i}"),
                name=tc_names[i],
                arguments=json_repair.loads("".join(tc_args.get(i, [])))
                if tc_args.get(i)
                else {},
            )
            for i in sorted(tc_names)
        ]

        return LLMResponse(
            content="".join(content_parts) or None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            reasoning_content="".join(reasoning_parts) or None,
        )

    def get_default_model(self) -> str:
        return self.default_model
