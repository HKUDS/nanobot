"""Generic OpenAI Responses API provider — uses httpx + SSE streaming."""

from __future__ import annotations

import json
from typing import Any

import httpx
from loguru import logger

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.providers.openai_codex_provider import (
    _consume_sse,
    _convert_messages,
    _convert_tools,
    _friendly_error,
)


class OpenAIResponsesProvider(LLMProvider):
    """Call any OpenAI-compatible Responses API endpoint with a standard API key."""

    def __init__(
        self,
        api_key: str = "",
        api_base: str = "https://api.openai.com/v1",
        default_model: str = "gpt-4o",
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self._base_url = api_base.rstrip("/")
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(600.0, connect=10.0),
            proxy=None,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        logger.info(
            "OpenAIResponsesProvider init: base_url={}, model={}",
            self._base_url, default_model,
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        model = model or self.default_model
        if "/" in model:
            model = model.split("/", 1)[1]

        system_prompt, input_items = _convert_messages(messages)

        body: dict[str, Any] = {
            "model": model,
            "stream": True,
            "input": input_items,
            "tool_choice": tool_choice or "auto",
            "parallel_tool_calls": True,
        }

        if system_prompt:
            body["instructions"] = system_prompt

        if max_tokens:
            body["max_output_tokens"] = max(1, max_tokens)

        if temperature is not None:
            body["temperature"] = temperature

        if reasoning_effort:
            body["reasoning"] = {"effort": reasoning_effort}

        if tools:
            body["tools"] = _convert_tools(tools)

        url = f"{self._base_url}/responses"

        try:
            logger.debug("OpenAIResponsesProvider.chat: url={}, model={}", url, model)
            async with self._http.stream("POST", url, json=body) as response:
                if response.status_code != 200:
                    text = (await response.aread()).decode("utf-8", "ignore")
                    error_text = text[:300]
                    logger.error("Responses API error {}: {}", response.status_code, error_text)
                    return LLMResponse(
                        content=f"Error: HTTP {response.status_code}: {error_text}",
                        finish_reason="error",
                    )
                content, tool_calls, finish_reason = await _consume_sse(response)
                return LLMResponse(
                    content=content or None,
                    tool_calls=tool_calls,
                    finish_reason=finish_reason,
                )
        except Exception as e:
            logger.error("OpenAIResponsesProvider.chat error: {}", e)
            return LLMResponse(content=f"Error: {e}", finish_reason="error")

    def get_default_model(self) -> str:
        return self.default_model
