"""NVIDIA provider for Kimi AI model execution."""

import json
from typing import Any, Dict, List, Optional

import httpx

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class NvidiaProvider(LLMProvider):
    """
    LLM provider for NVIDIA API model execution.

    Supports running NVIDIA-hosted models like moonshotai/kimi-k2.5
    through NVIDIA's integration API.
    """

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str = "moonshotai/kimi-k2.5",
        timeout: float = 60.0,
        usage_tracker: Any = None
    ):
        """
        Initialize NVIDIA provider.

        Args:
            api_key: NVIDIA API key (from NVIDIA_API_KEY env var or config)
            default_model: Default model to use (moonshotai/kimi-k2.5)
            timeout: Request timeout in seconds
            usage_tracker: Usage tracking instance
        """
        super().__init__(api_key=api_key, api_base=None, usage_tracker=usage_tracker)
        self.default_model = default_model
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=timeout)

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """
        Send a chat completion request to NVIDIA API.

        Args:
            messages: List of message dicts with 'role' and 'content'
            tools: Optional list of tool definitions (not supported yet)
            model: Model name (e.g., 'moonshotai/kimi-k2.5')
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature

        Returns:
            LLMResponse with content and usage information
        """
        if not self.api_key:
            return LLMResponse(
                content="Error: NVIDIA_API_KEY not configured",
                finish_reason="error",
            )

        model = model or self.default_model
        url = "https://integrate.api.nvidia.com/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        # Prepare request payload
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": 1.00,
            "stream": False,  # Non-streaming for simplicity
            "chat_template_kwargs": {"thinking": True},
        }

        # Note: NVIDIA API may not support tools in the same way as OpenAI
        if tools:
            # Log that tools are not supported or implement if available
            pass

        try:
            response = await self.client.post(
                url,
                json=payload,
                headers=headers
            )
            response.raise_for_status()

            data = response.json()
            return self._parse_response(data, model)

        except httpx.RequestError as e:
            return LLMResponse(
                content=f"Error connecting to NVIDIA API: {str(e)}",
                finish_reason="error",
            )
        except httpx.HTTPStatusError as e:
            return LLMResponse(
                content=f"NVIDIA API error ({e.response.status_code}): {e.response.text}",
                finish_reason="error",
            )

    def _parse_response(self, data: Dict[str, Any], model: str) -> LLMResponse:
        """Parse NVIDIA API response into our standard format."""
        try:
            choice = data["choices"][0]
            message = choice["message"]
            content = message.get("content", "")

            # Extract usage information
            usage_data = data.get("usage", {})
            usage = {
                "prompt_tokens": usage_data.get("prompt_tokens", 0),
                "completion_tokens": usage_data.get("completion_tokens", 0),
                "total_tokens": usage_data.get("total_tokens", 0),
            }

            # NVIDIA API may support tool calls in the future
            tool_calls = []

            finish_reason = choice.get("finish_reason", "stop")

            return LLMResponse(
                content=content,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
                usage=usage,
            )

        except (KeyError, IndexError) as e:
            return LLMResponse(
                content=f"Error parsing NVIDIA API response: {str(e)}",
                finish_reason="error",
            )

    def get_default_model(self) -> str:
        """Get the default model for this provider."""
        return self.default_model

    async def list_models(self) -> List[str]:
        """
        List available models in NVIDIA API.

        Note: NVIDIA API may not have a models endpoint, so we'll return known models.
        """
        # NVIDIA API doesn't seem to have a public models listing endpoint
        # Return known available models
        return [
            "moonshotai/kimi-k2.5",
            # Add other known NVIDIA models as they become available
        ]

    async def check_status(self) -> Dict[str, Any]:
        """
        Check NVIDIA API service status.

        Returns:
            Status information dictionary
        """
        if not self.api_key:
            return {
                "available": False,
                "error": "NVIDIA_API_KEY not configured",
            }

        try:
            # Try a simple request to check API availability
            # Using a minimal payload to avoid costs
            test_payload = {
                "model": self.default_model,
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 1,
                "temperature": 0.0,
            }

            response = await self.client.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                json=test_payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
            )

            if response.status_code == 200:
                return {
                    "available": True,
                    "models": await self.list_models(),
                    "endpoint": "https://integrate.api.nvidia.com/v1"
                }
            else:
                return {
                    "available": False,
                    "error": f"API returned status {response.status_code}",
                    "endpoint": "https://integrate.api.nvidia.com/v1"
                }

        except Exception as e:
            return {
                "available": False,
                "error": str(e),
                "endpoint": "https://integrate.api.nvidia.com/v1"
            }

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
