"""LiteLLM provider implementation for multi-provider support."""

import os
from typing import TYPE_CHECKING, Any

import litellm
from litellm import acompletion

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

if TYPE_CHECKING:
    from nanobot.config.schema import Config


class LiteLLMProvider(LLMProvider):
    """
    LLM provider using LiteLLM for multi-provider support.

    Supports OpenRouter, Anthropic, OpenAI, Gemini, and many other providers through
    a unified interface.
    """

    def __init__(self, config: "Config"):
        self.config = config
        self.default_model = config.agents.defaults.model
        super().__init__(None, None)

        # Set up all provider API keys
        self._setup_provider_keys()

        # Disable LiteLLM logging noise
        litellm.suppress_debug_info = True

    def _setup_provider_keys(self):
        """Set up API keys for all configured providers."""
        providers = self.config.providers

        if providers.openrouter.api_key:
            os.environ["OPENROUTER_API_KEY"] = providers.openrouter.api_key
        if providers.anthropic.api_key:
            os.environ["ANTHROPIC_API_KEY"] = providers.anthropic.api_key
        if providers.openai.api_key:
            os.environ["OPENAI_API_KEY"] = providers.openai.api_key
        if providers.deepseek.api_key:
            os.environ["DEEPSEEK_API_KEY"] = providers.deepseek.api_key
        if providers.gemini.api_key:
            os.environ["GEMINI_API_KEY"] = providers.gemini.api_key
        if providers.zhipu.api_key:
            os.environ["ZAI_API_KEY"] = providers.zhipu.api_key
            os.environ["ZHIPUAI_API_KEY"] = providers.zhipu.api_key
        if providers.dashscope.api_key:
            os.environ["DASHSCOPE_API_KEY"] = providers.dashscope.api_key
        if providers.groq.api_key:
            os.environ["GROQ_API_KEY"] = providers.groq.api_key
        if providers.moonshot.api_key:
            os.environ["MOONSHOT_API_KEY"] = providers.moonshot.api_key
        if providers.vllm.api_key:
            os.environ["HOSTED_VLLM_API_KEY"] = providers.vllm.api_key


    def _normalize_model(self, model: str) -> tuple[str, str | None]:
        """
        Normalize model name and return (model, api_base).
        Adds provider prefix if needed based on model name.
        """
        model_lower = model.lower()

        # Check for explicit provider prefix first
        if "/" in model:
            model.split("/")[0].lower()
            matched = self.config._match_provider(model)
            if matched:
                return model, matched.api_base

        # Auto-detect provider and add prefix
        if "openrouter" in model_lower:
            return f"openrouter/{model}" if not model.startswith("openrouter/") else model, self.config.providers.openrouter.api_base
        if "glm" in model_lower or "zhipu" in model_lower:
            return f"zai/{model}" if not model.startswith(("zai/", "zhipu/")) else model, self.config.providers.zhipu.api_base
        if "qwen" in model_lower or "dashscope" in model_lower:
            return f"dashscope/{model}" if not model.startswith("dashscope/") else model, self.config.providers.dashscope.api_base
        if "moonshot" in model_lower or "kimi" in model_lower:
            return f"moonshot/{model}" if not model.startswith("moonshot/") else model, self.config.providers.moonshot.api_base
        if "gemini" in model_lower:
            return f"gemini/{model}" if not model.startswith("gemini/") else model, self.config.providers.gemini.api_base
        if "vllm" in model_lower:
            return f"hosted_vllm/{model}" if not model.startswith("hosted_vllm/") else model, self.config.providers.vllm.api_base

        # Default: no prefix change
        return model, None

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """
        Send a chat completion request via LiteLLM.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions in OpenAI format.
            model: Model identifier (e.g., 'anthropic/claude-sonnet-4-5').
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.

        Returns:
            LLMResponse with content and/or tool calls.
        """
        model = model or self.default_model
        model, api_base = self._normalize_model(model)

        # kimi-k2.5 only supports temperature=1.0
        if "kimi-k2.5" in model.lower():
            temperature = 1.0

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        # Pass api_base if configured for this provider
        if api_base:
            kwargs["api_base"] = api_base

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            response = await acompletion(**kwargs)
            return self._parse_response(response)
        except Exception as e:
            # Return error as content for graceful handling
            return LLMResponse(
                content=f"Error calling LLM: {str(e)}",
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
