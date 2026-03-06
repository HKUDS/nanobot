"""Azure OpenAI provider implementation with API version 2024-10-21."""

from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import urljoin

import httpx
import json_repair

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class AzureOpenAIProvider(LLMProvider):
    """
    Azure OpenAI provider with API version 2024-10-21 compliance.
    
    Features:
    - Hardcoded API version 2024-10-21
    - Uses model field as Azure deployment name in URL path
    - Uses api-key header instead of Authorization Bearer
    - Uses max_completion_tokens instead of max_tokens
    - Direct HTTP calls, bypasses LiteLLM
    """

    def __init__(
        self,
        api_key: str = "",
        api_base: str = "",
        default_model: str = "gpt-5.2-chat",
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.api_version = "2024-10-21"
        
        # Validate required parameters
        if not api_key:
            raise ValueError("Azure OpenAI api_key is required")
        if not api_base:
            raise ValueError("Azure OpenAI api_base is required")
        
        # Ensure api_base ends with /
        if not api_base.endswith('/'):
            api_base += '/'
        self.api_base = api_base

    def _build_chat_url(self, deployment_name: str) -> str:
        """Build the Azure OpenAI chat completions URL."""
        # Azure OpenAI URL format:
        # https://{resource}.openai.azure.com/openai/deployments/{deployment}/chat/completions?api-version={version}
        base_url = self.api_base
        if not base_url.endswith('/'):
            base_url += '/'
        
        url = urljoin(
            base_url, 
            f"openai/deployments/{deployment_name}/chat/completions"
        )
        return f"{url}?api-version={self.api_version}"

    def _build_headers(self) -> dict[str, str]:
        """Build headers for Azure OpenAI API with api-key header."""
        return {
            "Content-Type": "application/json",
            "api-key": self.api_key,  # Azure OpenAI uses api-key header, not Authorization
            "x-session-affinity": uuid.uuid4().hex,  # For cache locality
        }

    def _prepare_request_payload(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
        reasoning_effort: str | None = None,
    ) -> dict[str, Any]:
        """Prepare the request payload with Azure OpenAI 2024-10-21 compliance."""
        payload: dict[str, Any] = {
            "messages": self._sanitize_empty_content(messages),
            "max_completion_tokens": max(1, max_tokens),  # Azure API 2024-10-21 uses max_completion_tokens
        }

        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        return payload

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
    ) -> LLMResponse:
        """
        Send a chat completion request to Azure OpenAI.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions in OpenAI format.
            model: Model identifier (used as deployment name).
            max_tokens: Maximum tokens in response (mapped to max_completion_tokens).
            temperature: Sampling temperature.
            reasoning_effort: Optional reasoning effort parameter.

        Returns:
            LLMResponse with content and/or tool calls.
        """
        deployment_name = model or self.default_model
        url = self._build_chat_url(deployment_name)
        headers = self._build_headers()
        payload = self._prepare_request_payload(
            messages, tools, max_tokens, reasoning_effort
        )

        try:
            async with httpx.AsyncClient(timeout=60.0, verify=True) as client:
                response = await client.post(url, headers=headers, json=payload)
                if response.status_code != 200:
                    return LLMResponse(
                        content=f"Azure OpenAI API Error {response.status_code}: {response.text}",
                        finish_reason="error",
                    )
                
                response_data = response.json()
                return self._parse_response(response_data)

        except Exception as e:
            return LLMResponse(
                content=f"Error calling Azure OpenAI: {repr(e)}",
                finish_reason="error",
            )

    def _parse_response(self, response: dict[str, Any]) -> LLMResponse:
        """Parse Azure OpenAI response into our standard format."""
        try:
            choice = response["choices"][0]
            message = choice["message"]

            tool_calls = []
            if message.get("tool_calls"):
                for tc in message["tool_calls"]:
                    # Parse arguments from JSON string if needed
                    args = tc["function"]["arguments"]
                    if isinstance(args, str):
                        args = json_repair.loads(args)

                    tool_calls.append(
                        ToolCallRequest(
                            id=tc["id"],
                            name=tc["function"]["name"],
                            arguments=args,
                        )
                    )

            usage = {}
            if response.get("usage"):
                usage_data = response["usage"]
                usage = {
                    "prompt_tokens": usage_data.get("prompt_tokens", 0),
                    "completion_tokens": usage_data.get("completion_tokens", 0),
                    "total_tokens": usage_data.get("total_tokens", 0),
                }

            reasoning_content = message.get("reasoning_content") or None

            return LLMResponse(
                content=message.get("content"),
                tool_calls=tool_calls,
                finish_reason=choice.get("finish_reason", "stop"),
                usage=usage,
                reasoning_content=reasoning_content,
            )

        except (KeyError, IndexError) as e:
            return LLMResponse(
                content=f"Error parsing Azure OpenAI response: {str(e)}",
                finish_reason="error",
            )

    def get_default_model(self) -> str:
        """Get the default model (also used as default deployment name)."""
        return self.default_model