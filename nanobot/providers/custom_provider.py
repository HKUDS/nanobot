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
                   reasoning_effort: str | None = None) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": self._sanitize_empty_content(messages),
            "max_tokens": max(1, max_tokens),
            "temperature": temperature,
        }
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
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
        content = msg.content
        # Fallback: some models (e.g. Qwen via Ollama) output tool-call JSON in
        # the text content instead of the structured tool_calls field.
        if not tool_calls and content:
            tool_calls, content = self._extract_text_tool_calls(content)
        u = response.usage
        return LLMResponse(
            content=content, tool_calls=tool_calls, finish_reason=choice.finish_reason or "stop",
            usage={"prompt_tokens": u.prompt_tokens, "completion_tokens": u.completion_tokens, "total_tokens": u.total_tokens} if u else {},
            reasoning_content=getattr(msg, "reasoning_content", None) or None,
        )

    @staticmethod
    def _extract_text_tool_calls(content: str) -> tuple[list[ToolCallRequest], str | None]:
        """Parse tool calls embedded as JSON in text content.

        Returns (tool_calls, remaining_content). If the entire content is a
        tool-call envelope the remaining content is set to None so the agent
        loop doesn't forward raw JSON to the user.
        """
        import re

        # Find the first { or [ in the content — models sometimes emit preamble text.
        match = re.search(r"[{\[]", content)
        if not match:
            return [], content
        json_start = match.start()
        candidate = content[json_start:].strip()

        try:
            parsed = json_repair.loads(candidate)
        except Exception:
            return [], content

        candidates = parsed if isinstance(parsed, list) else [parsed]
        calls = []
        for obj in candidates:
            if (isinstance(obj, dict)
                    and isinstance(obj.get("name"), str)
                    and isinstance(obj.get("arguments"), dict)):
                calls.append(ToolCallRequest(
                    id=f"txt_{uuid.uuid4().hex[:8]}",
                    name=obj["name"],
                    arguments=obj["arguments"],
                ))
        if calls:
            # Keep any preamble text before the JSON as the content, or None if nothing useful.
            preamble = content[:json_start].strip() or None
            return calls, preamble
        return [], content

    def get_default_model(self) -> str:
        return self.default_model

