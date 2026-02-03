"""Ollama provider for local LLM execution."""

import json
from typing import Any, Dict, List, Optional

import httpx

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class OllamaProvider(LLMProvider):
    """
    LLM provider for Ollama local model execution.

    Supports running large language models locally through Ollama's REST API.
    Typically runs on http://localhost:11434
    """

    def __init__(
        self,
        api_base: str = "http://localhost:11434",
        default_model: str = "llama3.2",
        timeout: float = 120.0,
        usage_tracker: Any = None
    ):
        """
        Initialize Ollama provider.

        Args:
            api_base: Base URL for Ollama API (default: http://localhost:11434)
            default_model: Default model to use
            timeout: Request timeout in seconds
            usage_tracker: Usage tracking instance
        """
        super().__init__(api_key=None, api_base=api_base, usage_tracker=usage_tracker)
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
        Send a chat completion request to Ollama.

        Args:
            messages: List of message dicts with 'role' and 'content'
            tools: Optional list of tool definitions (Ollama has limited tool support)
            model: Model name (e.g., 'llama3.2', 'mistral', 'codellama')
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature

        Returns:
            LLMResponse with content and usage information
        """
        model = model or self.default_model

        # Convert messages to Ollama format
        ollama_messages = self._convert_messages(messages)

        # Prepare request payload
        payload = {
            "model": model,
            "messages": ollama_messages,
            "stream": False,  # We handle non-streaming for simplicity
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        }

        # Ollama doesn't have great tool support yet, so we'll skip for now
        if tools:
            # Log that tools are not supported
            pass

        try:
            response = await self.client.post(
                f"{self.api_base}/api/chat",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()

            data = response.json()
            return self._parse_response(data, model)

        except httpx.RequestError as e:
            return LLMResponse(
                content=f"Error connecting to Ollama: {str(e)}. Make sure Ollama is running.",
                finish_reason="error",
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return LLMResponse(
                    content=f"Model '{model}' not found. Use 'ollama pull {model}' to install it.",
                    finish_reason="error",
                )
            return LLMResponse(
                content=f"Ollama API error ({e.response.status_code}): {e.response.text}",
                finish_reason="error",
            )

    def _convert_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert standard chat messages to Ollama format."""
        ollama_messages = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # Handle system messages
            if role == "system":
                ollama_messages.append({
                    "role": "system",
                    "content": content
                })
            elif role == "user":
                ollama_messages.append({
                    "role": "user",
                    "content": content
                })
            elif role == "assistant":
                ollama_messages.append({
                    "role": "assistant",
                    "content": content
                })
            # Skip tool-related messages for now as Ollama has limited tool support

        return ollama_messages

    def _parse_response(self, data: Dict[str, Any], model: str) -> LLMResponse:
        """Parse Ollama response into our standard format."""
        message = data.get("message", {})
        content = message.get("content", "")

        # Ollama doesn't provide token usage in a standard way
        # We'll estimate based on content length (rough approximation)
        prompt_tokens = data.get("prompt_eval_count", 0)
        completion_tokens = data.get("eval_count", 0)
        total_tokens = prompt_tokens + completion_tokens

        # If no token counts provided, estimate
        if total_tokens == 0 and content:
            # Rough estimation: ~4 chars per token
            estimated_tokens = len(content) // 4
            completion_tokens = estimated_tokens
            total_tokens = estimated_tokens

        usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }

        # Ollama doesn't support tool calls in the same way
        tool_calls = []

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=data.get("done_reason", "stop"),
            usage=usage,
        )

    def get_default_model(self) -> str:
        """Get the default model for this provider."""
        return self.default_model

    async def list_models(self) -> List[str]:
        """
        List available models in Ollama.

        Returns:
            List of model names
        """
        try:
            response = await self.client.get(f"{self.api_base}/api/tags")
            response.raise_for_status()
            data = response.json()

            models = data.get("models", [])
            return [model["name"] for model in models]

        except Exception:
            return []

    async def check_status(self) -> Dict[str, Any]:
        """
        Check Ollama service status.

        Returns:
            Status information dictionary
        """
        try:
            # Try to get version info
            response = await self.client.get(f"{self.api_base}/api/version")
            response.raise_for_status()
            version_data = response.json()

            # Try to list models
            models = await self.list_models()

            return {
                "available": True,
                "version": version_data.get("version", "unknown"),
                "models": models,
                "endpoint": self.api_base
            }

        except Exception as e:
            return {
                "available": False,
                "error": str(e),
                "endpoint": self.api_base
            }

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
