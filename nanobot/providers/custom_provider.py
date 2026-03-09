"""Direct OpenAI-compatible provider — bypasses LiteLLM."""

from __future__ import annotations

from typing import Any

import httpx
import json_repair
from openai import AsyncOpenAI

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class CustomProvider(LLMProvider):

    def __init__(self, api_key: str = "no-key", api_base: str = "http://localhost:8000/v1", default_model: str = "default"):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self._client = AsyncOpenAI(api_key=api_key, base_url=api_base)

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                   model: str | None = None, max_tokens: int = 4096, temperature: float = 0.7,
                   reasoning_effort: str | None = None) -> LLMResponse:
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
            kwargs.update(tools=tools, tool_choice="auto")
        try:
            return self._parse(await self._client.chat.completions.create(**kwargs))
        except Exception as e:
            fallback = await self._chat_via_http(kwargs)
            if fallback is not None:
                return fallback
            return LLMResponse(content=f"Error: {e}", finish_reason="error")

    async def _chat_via_http(self, kwargs: dict[str, Any]) -> LLMResponse | None:
        """Fallback for OpenAI-compatible endpoints that reject the official SDK."""
        try:
            base = (self.api_base or "").rstrip("/")
            if not base:
                return None
            url = f"{base}/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            }
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url, headers=headers, json=kwargs)
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
