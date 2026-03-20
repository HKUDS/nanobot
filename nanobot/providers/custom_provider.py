"""Direct OpenAI-compatible provider — bypasses LiteLLM."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import json_repair
from openai import AsyncOpenAI, _types as openai_types

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class _StainlessStripTransport(httpx.AsyncBaseTransport):
    """Wraps an async transport and strips X-Stainless-* headers before sending."""

    def __init__(self, transport: httpx.AsyncBaseTransport):
        self._inner = transport

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        keys_to_remove = [k for k in request.headers.keys() if k.lower().startswith("x-stainless")]
        for k in keys_to_remove:
            del request.headers[k]
        return await self._inner.handle_async_request(request)


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
        # Keep affinity stable for this provider instance to improve backend cache locality.
        headers: dict[str, str | openai_types.Omit] = {"x-session-affinity": uuid.uuid4().hex}
        strip_stainless = False
        if extra_headers:
            headers.update(extra_headers)
            # When User-Agent is explicitly set (e.g. for Kimi Code compatibility),
            # strip SDK fingerprint headers that reveal the true client identity.
            if "User-Agent" in extra_headers:
                strip_stainless = True
                for key in (
                    "X-Stainless-Lang",
                    "X-Stainless-Package-Version",
                    "X-Stainless-OS",
                    "X-Stainless-Arch",
                    "X-Stainless-Runtime",
                    "X-Stainless-Runtime-Version",
                    "X-Stainless-Async",
                ):
                    headers[key] = openai_types.Omit()

        kwargs: dict[str, Any] = {
            "api_key": api_key,
            "base_url": api_base,
            "default_headers": headers,
        }
        if strip_stainless:
            # Use a custom transport to strip dynamically injected X-Stainless-* headers
            base_transport = httpx.AsyncHTTPTransport()
            kwargs["http_client"] = httpx.AsyncClient(transport=_StainlessStripTransport(base_transport))

        self._client = AsyncOpenAI(**kwargs)

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
            # JSONDecodeError.doc / APIError.response.text may carry the raw body
            # (e.g. "unsupported model: xxx") which is far more useful than the
            # generic "Expecting value …" message.  Truncate to avoid huge HTML pages.
            body = getattr(e, "doc", None) or getattr(getattr(e, "response", None), "text", None)
            if body and body.strip():
                return LLMResponse(content=f"Error: {body.strip()[:500]}", finish_reason="error")
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

    def get_default_model(self) -> str:
        return self.default_model

