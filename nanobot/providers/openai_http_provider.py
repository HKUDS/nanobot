"""OpenAI-compatible HTTP provider using direct async requests."""

import json
from typing import Any

import aiohttp

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class OpenAIHTTPProvider(LLMProvider):
    """
    LLM provider using direct async HTTP requests to OpenAI-compatible APIs.

    This provider sends requests directly to any OpenAI-compatible API endpoint
    without using LiteLLM. Useful for custom deployments or when you want
    more control over the HTTP requests.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "gpt-4-turbo-preview",
        timeout: int = 300
    ):
        """
        Initialize the HTTP provider.

        Args:
            api_key: API key for authentication
            api_base: Base URL for the API (e.g., "https://api.openai.com/v1")
            default_model: Default model to use
            timeout: Request timeout in seconds
        """
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.timeout = timeout

        # Set default API base if not provided
        if not self.api_base:
            self.api_base = "https://api.openai.com/v1"

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """
        Send a chat completion request via direct HTTP.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions in OpenAI format.
            model: Model identifier (e.g., 'gpt-4-turbo-preview').
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.

        Returns:
            LLMResponse with content and/or tool calls.
        """
        model = model or self.default_model

        # Construct the API endpoint
        endpoint = f"{self.api_base.rstrip('/')}/chat/completions"

        # Build request payload
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        # Set up headers
        headers = {
            "Content-Type": "application/json",
        }

        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            # Make async HTTP request
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    endpoint,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
                    return self._parse_response(data)

        except aiohttp.ClientError as e:
            return LLMResponse(
                content=f"HTTP request error: {str(e)}",
                finish_reason="error",
            )
        except json.JSONDecodeError as e:
            return LLMResponse(
                content=f"Failed to parse response JSON: {str(e)}",
                finish_reason="error",
            )
        except Exception as e:
            return LLMResponse(
                content=f"Error calling LLM: {str(e)}",
                finish_reason="error",
            )

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        """Parse OpenAI API response into our standard format."""
        try:
            choice = data["choices"][0]
            message = choice["message"]

            # Parse tool calls if present
            tool_calls = []
            if "tool_calls" in message and message["tool_calls"]:
                for tc in message["tool_calls"]:
                    # Parse arguments from JSON string
                    args = tc["function"]["arguments"]
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {"raw": args}

                    tool_calls.append(ToolCallRequest(
                        id=tc["id"],
                        name=tc["function"]["name"],
                        arguments=args,
                    ))

            # Parse usage information if present
            usage = {}
            if "usage" in data:
                usage = {
                    "prompt_tokens": data["usage"].get("prompt_tokens", 0),
                    "completion_tokens": data["usage"].get("completion_tokens", 0),
                    "total_tokens": data["usage"].get("total_tokens", 0),
                }

            return LLMResponse(
                content=message.get("content"),
                tool_calls=tool_calls,
                finish_reason=choice.get("finish_reason", "stop"),
                usage=usage,
            )
        except (KeyError, IndexError) as e:
            return LLMResponse(
                content=f"Failed to parse response structure: {str(e)}",
                finish_reason="error",
            )

    def get_default_model(self) -> str:
        """Get the default model."""
        return self.default_model
