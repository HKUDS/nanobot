"""Native OpenAI provider implementation."""

import asyncio
import logging
from typing import Any

from openai import AsyncOpenAI, APITimeoutError, APIError, RateLimitError, AuthenticationError

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

logger = logging.getLogger(__name__)

# Default timeout for API requests (seconds)
DEFAULT_TIMEOUT = 120


class OpenAIProvider(LLMProvider):
    """
    Native OpenAI provider with OpenAI-compatible API support.

    Supports:
    - OpenAI (GPT-4, GPT-3.5)
    - OpenAI-compatible providers (DeepSeek, Groq, Together, etc.)
    - Local models (Ollama, vLLM, LM Studio, etc.)

    Automatically handles retries for rate limits and transient errors.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "gpt-4o",
        timeout: int = DEFAULT_TIMEOUT,
    ):
        """
        Initialize OpenAI provider.

        Args:
            api_key: OpenAI API key or compatible provider key.
            api_base: Custom base URL for compatible providers.
            default_model: Default model to use.
            timeout: Request timeout in seconds.
        """
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.timeout = timeout

        # Initialize async client
        client_kwargs: dict[str, Any] = {
            "timeout": timeout,
        }
        if api_key:
            client_kwargs["api_key"] = api_key
        if api_base:
            client_kwargs["base_url"] = api_base

        self.client = AsyncOpenAI(**client_kwargs)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        top_p: float | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Send a chat completion request via OpenAI API.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions in OpenAI format.
            model: Model identifier.
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature (0-2).
            top_p: Nucleus sampling parameter.
            **kwargs: Additional provider-specific parameters.

        Returns:
            LLMResponse with content and/or tool calls.
        """
        model = model or self.default_model

        # Build request kwargs
        request_kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        if tools:
            request_kwargs["tools"] = tools

        if top_p is not None:
            request_kwargs["top_p"] = top_p

        try:
            response = await self.client.chat.completions.create(**request_kwargs)
            return self._parse_response(response)
        except AuthenticationError as e:
            logger.error(f"OpenAI authentication error: {e}", exc_info=True)
            return LLMResponse(
                content=f"OpenAI API authentication failed. Check your API key.",
                finish_reason="error",
            )
        except RateLimitError as e:
            logger.error(f"OpenAI rate limit error: {e}", exc_info=True)
            return LLMResponse(
                content=f"OpenAI API rate limit exceeded. Please try again later.",
                finish_reason="error",
            )
        except APITimeoutError as e:
            logger.error(f"OpenAI timeout error: {e}", exc_info=True)
            return LLMResponse(
                content=f"OpenAI API timeout after {self.timeout}s",
                finish_reason="error",
            )
        except APIError as e:
            logger.error(f"OpenAI API error: {e}", exc_info=True)
            return LLMResponse(
                content=f"OpenAI API error: {e.message}",
                finish_reason="error",
            )
        except Exception as e:
            logger.exception("Unexpected OpenAI API error")
            return LLMResponse(
                content=f"Error calling OpenAI API: {str(e)}",
                finish_reason="error",
            )

    def _parse_response(self, response: Any) -> LLMResponse:
        """
        Parse OpenAI response into our standard format.

        Args:
            response: Raw response from OpenAI API.

        Returns:
            LLMResponse with parsed content, tool calls, and metadata.
        """
        choice = response.choices[0]
        message = choice.message

        # Parse tool calls
        tool_calls = []
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append(ToolCallRequest(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=tc.function.arguments,
                ))

        # Parse usage
        usage = {}
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        # Map finish_reason
        finish_reason = choice.finish_reason or "stop"

        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
        )

    def get_default_model(self) -> str:
        """Get the default model."""
        return self.default_model
