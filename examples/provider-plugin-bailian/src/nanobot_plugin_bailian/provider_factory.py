"""Provider factory for Alibaba Cloud BaiLian plugin.

This plugin intentionally goes beyond nanobot's default provider surface:
it maps plugin config to DashScope OpenAI-compatible `extra_body` controls
such as `enable_thinking` and `enable_search`.
"""

from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

_DEFAULT_API_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_MODEL_PREFIX = "dashscope/"


def _extract_extra_body(
    provider_extra_body: dict[str, Any] | None,
    extra_headers: dict[str, str] | None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Build DashScope extra_body from standard plugin config fields."""
    extra_body: dict[str, Any] = dict(provider_extra_body or {})
    passthrough_headers = dict(extra_headers or {})
    return extra_body, passthrough_headers


class BaiLianPluginProvider(LLMProvider):
    """Custom BaiLian provider with native extra_body support."""

    def __init__(
        self,
        *,
        api_key: str,
        api_base: str,
        default_model: str,
        extra_body: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ):
        super().__init__(api_key=api_key, api_base=api_base)
        self.default_model = default_model
        self.extra_body = dict(extra_body or {})
        self.extra_headers = dict(extra_headers or {})
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=api_base,
            default_headers=self.extra_headers or None,
        )

    @staticmethod
    def _normalize_model(model: str) -> str:
        return model[len(_MODEL_PREFIX) :] if model.startswith(_MODEL_PREFIX) else model

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self._normalize_model(model or self.default_model),
            "messages": self._sanitize_request_messages(
                self._sanitize_empty_content(messages),
                frozenset({"role", "content", "tool_calls", "tool_call_id", "name"}),
            ),
            "max_tokens": max(1, max_tokens),
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        merged_extra_body = dict(self.extra_body)
        if reasoning_effort:
            merged_extra_body["reasoning_effort"] = reasoning_effort
        if merged_extra_body:
            payload["extra_body"] = merged_extra_body

        try:
            resp = await self._client.chat.completions.create(**payload)
        except Exception as exc:
            return LLMResponse(content=f"Error calling BaiLian: {exc}", finish_reason="error")

        choice = resp.choices[0]
        msg = choice.message
        tool_calls: list[ToolCallRequest] = []
        for tc in msg.tool_calls or []:
            args = tc.function.arguments
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {"raw": args}
            tool_calls.append(
                ToolCallRequest(id=tc.id or "call", name=tc.function.name, arguments=args or {})
            )

        usage: dict[str, int] = {}
        if resp.usage is not None:
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens or 0,
                "completion_tokens": resp.usage.completion_tokens or 0,
                "total_tokens": resp.usage.total_tokens or 0,
            }
        return LLMResponse(
            content=msg.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage=usage,
        )

    def get_default_model(self) -> str:
        return self.default_model


def create_provider(*, config, model, provider_name, provider_config):
    """Entry point target for `nanobot.provider_factories`."""
    if provider_config is None or not provider_config.api_key:
        raise ValueError(
            "aliyun_bailian plugin requires providers.plugins.aliyun_bailian.apiKey"
        )

    api_base = provider_config.api_base or _DEFAULT_API_BASE
    extra_body, passthrough_headers = _extract_extra_body(
        provider_config.extra_body,
        provider_config.extra_headers,
    )
    return BaiLianPluginProvider(
        api_key=provider_config.api_key,
        api_base=api_base,
        default_model=model,
        extra_body=extra_body,
        extra_headers=passthrough_headers,
    )
