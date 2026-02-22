"""Direct OpenAI-compatible provider — bypasses LiteLLM."""

from __future__ import annotations

from typing import Any

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
            "messages": self._prevent_empty_text_blocks(messages),
            "max_tokens": max(1, max_tokens),
            "temperature": temperature,
        }
        if tools:
            kwargs.update(tools=tools, tool_choice="auto")
        try:
            return self._parse(await self._client.chat.completions.create(**kwargs))
        except Exception as e:
            return LLMResponse(content=f"Error: {e}", finish_reason="error")

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

    @staticmethod
    def _prevent_empty_text_blocks(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Filter empty text content blocks that cause provider 400 errors.

        When MCP tools return empty content, messages may contain empty-string
        text blocks. Most providers (OpenAI-compatible) reject these with 400.
        This method filters them out before sending to the API.
        """
        patched: list[dict[str, Any]] = []
        for msg in messages:
            content = msg.get("content")

            # Empty string content
            if isinstance(content, str) and content == "":
                clean = dict(msg)
                if msg.get("role") == "assistant" and msg.get("tool_calls"):
                    clean["content"] = None
                else:
                    clean["content"] = "(empty)"
                patched.append(clean)
                continue

            # List content — filter out empty text items
            if isinstance(content, list):
                filtered = [
                    item for item in content
                    if not (isinstance(item, dict)
                            and item.get("type") in {"text", "input_text", "output_text"}
                            and item.get("text") == "")
                ]
                if filtered != content:
                    clean = dict(msg)
                    if filtered:
                        clean["content"] = filtered
                    elif msg.get("role") == "assistant" and msg.get("tool_calls"):
                        clean["content"] = None
                    else:
                        clean["content"] = "(empty)"
                    patched.append(clean)
                    continue

            patched.append(msg)
        return patched
