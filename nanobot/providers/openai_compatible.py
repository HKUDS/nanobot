"""OpenAI-compatible LLM provider using LiteLLM."""

import os
from typing import Any

import litellm
from litellm import acompletion, completion

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class OpenAICompatibleLLMProvider(LLMProvider):
    """
    LLM provider for OpenAI-compatible APIs using LiteLLM.
    
    Supports any API that follows the OpenAI chat completion format,
    including OpenAI, vLLM, LocalAI, OpenRouter, and other compatible services.
    """
    
    def __init__(
        self, 
        api_key: str | None = None, 
        api_base: str | None = None,
        default_model: str = "gpt-3.5-turbo"
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        
        # Set environment variables for LiteLLM
        litellm.suppress_debug_info = False
    
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """
        Send a chat completion request via LiteLLM to an OpenAI-compatible API.
        
        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions in OpenAI format.
            model: Model identifier (e.g., 'gpt-4', 'claude-3-opus').
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.
        
        Returns:
            LLMResponse with content and/or tool calls.
        """
        model = model or self.default_model
        
        # Ensure model has appropriate prefix for LiteLLM
        # If model doesn't have a provider prefix and is not a known OpenAI model,
        # assume it's an OpenAI model (LiteLLM will handle it)
        # For custom endpoints, we can keep as-is
        kwargs: dict[str, Any] = {
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        
        try:
            response = await litellm.acompletion(
                model= model,
                api_base= self.api_base,
                api_key= self.api_key,
                messages= messages,
                **kwargs
            )
            return self._parse_response(response)
        except Exception as e:
            # Return error as content for graceful handling
            return LLMResponse(
                content=f"Error calling OpenAI-compatible API: {str(e)}",
                finish_reason="error",
            )
    
    def _parse_response(self, response: Any) -> LLMResponse:
        """Parse LiteLLM response into our standard format."""
        choice = response.choices[0]
        message = choice.message
        
        tool_calls = []
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                # Parse arguments from JSON string if needed
                args = tc.function.arguments
                if isinstance(args, str):
                    import json
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw": args}
                
                tool_calls.append(ToolCallRequest(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                ))
        
        usage = {}
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        
        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage=usage,
        )
    
    def get_default_model(self) -> str:
        """Get the default model."""
        return self.default_model