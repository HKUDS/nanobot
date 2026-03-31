"""Azure OpenAI provider using the OpenAI SDK Responses API.

Uses ``AsyncOpenAI`` pointed at ``https://{endpoint}/openai/v1/`` which
routes to the Responses API (``/responses``).  Reuses shared conversion
helpers from :mod:`nanobot.providers.openai_responses_common`.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from openai import AsyncOpenAI

from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.providers.openai_responses_common import (
    consume_sse,
    convert_messages,
    convert_tools,
    parse_response_output,
)


class AzureOpenAIProvider(LLMProvider):
    """Azure OpenAI provider backed by the Responses API.

    Features:
    - Uses the OpenAI Python SDK (``AsyncOpenAI``) with
      ``base_url = {endpoint}/openai/v1/``
    - Calls ``client.responses.create()`` (Responses API)
    - Reuses shared message/tool/SSE conversion from
      ``openai_responses_common``
    """

    def __init__(
        self,
        api_key: str = "",
        api_base: str = "",
        default_model: str = "gpt-5.2-chat",
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model

        if not api_key:
            raise ValueError("Azure OpenAI api_key is required")
        if not api_base:
            raise ValueError("Azure OpenAI api_base is required")

        # Normalise: ensure trailing slash
        if not api_base.endswith("/"):
            api_base += "/"
        self.api_base = api_base

        # SDK client targeting the Azure Responses API endpoint
        base_url = f"{api_base.rstrip('/')}/openai/v1/"
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers={"x-session-affinity": uuid.uuid4().hex},
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _supports_temperature(
        deployment_name: str,
        reasoning_effort: str | None = None,
    ) -> bool:
        """Return True when temperature is likely supported for this deployment."""
        if reasoning_effort:
            return False
        name = deployment_name.lower()
        return not any(token in name for token in ("gpt-5", "o1", "o3", "o4"))

    def _build_body(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        max_tokens: int,
        temperature: float,
        reasoning_effort: str | None,
        tool_choice: str | dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Build the Responses API request body from Chat-Completions-style args."""
        deployment = model or self.default_model
        instructions, input_items = convert_messages(messages)

        body: dict[str, Any] = {
            "model": deployment,
            "instructions": instructions or None,
            "input": input_items,
            "store": False,
            "stream": False,
        }

        if self._supports_temperature(deployment, reasoning_effort):
            body["temperature"] = temperature

        if reasoning_effort:
            body["reasoning"] = {"effort": reasoning_effort}
            body["include"] = ["reasoning.encrypted_content"]

        if tools:
            body["tools"] = convert_tools(tools)
            body["tool_choice"] = tool_choice or "auto"

        return body

    @staticmethod
    def _handle_error(e: Exception) -> LLMResponse:
        body = getattr(e, "body", None) or getattr(getattr(e, "response", None), "text", None)
        msg = f"Error: {str(body).strip()[:500]}" if body else f"Error calling Azure OpenAI: {e}"
        return LLMResponse(content=msg, finish_reason="error")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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
        body = self._build_body(
            messages, tools, model, max_tokens, temperature,
            reasoning_effort, tool_choice,
        )
        try:
            response = await self._client.responses.create(**body)
            return parse_response_output(response)
        except Exception as e:
            return self._handle_error(e)

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        body = self._build_body(
            messages, tools, model, max_tokens, temperature,
            reasoning_effort, tool_choice,
        )
        body["stream"] = True

        try:
            # Use raw httpx stream via the SDK's base URL so we can reuse
            # the shared Responses-API SSE parser (same as Codex provider).
            base_url = str(self._client.base_url).rstrip("/")
            url = f"{base_url}/responses"
            headers = {
                "Authorization": f"Bearer {self._client.api_key}",
                "Content-Type": "application/json",
                **(self._client._custom_headers or {}),
            }
            async with httpx.AsyncClient(timeout=60.0, verify=True) as http:
                async with http.stream("POST", url, headers=headers, json=body) as response:
                    if response.status_code != 200:
                        text = await response.aread()
                        return LLMResponse(
                            content=f"Azure OpenAI API Error {response.status_code}: {text.decode('utf-8', 'ignore')}",
                            finish_reason="error",
                        )
                    content, tool_calls, finish_reason = await consume_sse(
                        response, on_content_delta,
                    )
                    return LLMResponse(
                        content=content or None,
                        tool_calls=tool_calls,
                        finish_reason=finish_reason,
                    )
        except Exception as e:
            return self._handle_error(e)

    def get_default_model(self) -> str:
        return self.default_model