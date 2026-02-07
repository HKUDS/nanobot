"""LiteLLM provider implementation for multi-provider support."""

import os
from typing import Any

import litellm
from litellm import acompletion

from collections.abc import AsyncIterator

from nanobot.providers.base import (
    LLMProvider,
    LLMResponse,
    StreamChunk,
    ToolCallRequest,
)


class LiteLLMProvider(LLMProvider):
    """
    LLM provider using LiteLLM for multi-provider support.

    Supports OpenRouter, Anthropic, OpenAI, Gemini, and many other providers through
    a unified interface.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "anthropic/claude-opus-4-5",
        extra_headers: dict[str, str] | None = None,
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.extra_headers = extra_headers or {}

        # Detect OpenRouter by api_key prefix or explicit api_base
        self.is_openrouter = (api_key and api_key.startswith("sk-or-")) or (
            api_base and "openrouter" in api_base
        )

        # Detect AiHubMix by api_base
        self.is_aihubmix = bool(api_base and "aihubmix" in api_base)

        # Track if using custom endpoint (vLLM, etc.)
        self.is_vllm = (
            bool(api_base) and not self.is_openrouter and not self.is_aihubmix
        )

        # Configure LiteLLM based on provider
        if api_key:
            if self.is_openrouter:
                # OpenRouter mode - set key
                os.environ["OPENROUTER_API_KEY"] = api_key
            elif self.is_aihubmix:
                # AiHubMix gateway - OpenAI-compatible
                os.environ["OPENAI_API_KEY"] = api_key
            elif self.is_vllm:
                # vLLM/custom endpoint - uses OpenAI-compatible API
                os.environ["HOSTED_VLLM_API_KEY"] = api_key
            elif "deepseek" in default_model:
                os.environ.setdefault("DEEPSEEK_API_KEY", api_key)
            elif "anthropic" in default_model:
                os.environ.setdefault("ANTHROPIC_API_KEY", api_key)
            elif "openai" in default_model or "gpt" in default_model:
                os.environ.setdefault("OPENAI_API_KEY", api_key)
            elif "gemini" in default_model.lower():
                os.environ.setdefault("GEMINI_API_KEY", api_key)
            elif (
                "zhipu" in default_model
                or "glm" in default_model
                or "zai" in default_model
            ):
                os.environ.setdefault("ZAI_API_KEY", api_key)
                os.environ.setdefault("ZHIPUAI_API_KEY", api_key)
            elif "dashscope" in default_model or "qwen" in default_model.lower():
                os.environ.setdefault("DASHSCOPE_API_KEY", api_key)
            elif "groq" in default_model:
                os.environ.setdefault("GROQ_API_KEY", api_key)
            elif "moonshot" in default_model or "kimi" in default_model:
                os.environ.setdefault("MOONSHOT_API_KEY", api_key)
                os.environ.setdefault(
                    "MOONSHOT_API_BASE", api_base or "https://api.moonshot.cn/v1"
                )

        if api_base:
            litellm.api_base = api_base

        # Disable LiteLLM logging noise
        litellm.suppress_debug_info = True

    def _prepare_model(
        self, model: str | None, temperature: float = 0.7
    ) -> tuple[str, float]:
        """Resolve and prefix the model name; adjust temperature if needed."""
        model = model or self.default_model

        # Auto-prefix model names for known providers
        _prefix_rules = [
            (
                ("glm", "zhipu"),
                "zai",
                ("zhipu/", "zai/", "openrouter/", "hosted_vllm/"),
            ),
            (("qwen", "dashscope"), "dashscope", ("dashscope/", "openrouter/")),
            (("moonshot", "kimi"), "moonshot", ("moonshot/", "openrouter/")),
            (("gemini",), "gemini", ("gemini/",)),
        ]
        model_lower = model.lower()
        for keywords, prefix, skip in _prefix_rules:
            if any(kw in model_lower for kw in keywords) and not any(
                model.startswith(s) for s in skip
            ):
                model = f"{prefix}/{model}"
                break

        # Gateway/endpoint-specific prefixes
        if self.is_openrouter and not model.startswith("openrouter/"):
            model = f"openrouter/{model}"
        elif self.is_aihubmix:
            model = f"openai/{model.split('/')[-1]}"
        elif self.is_vllm:
            model = f"hosted_vllm/{model}"

        if "kimi-k2.5" in model.lower():
            temperature = 1.0

        return model, temperature

    def _base_kwargs(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        """Build base kwargs common to chat and chat_stream."""
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if self.extra_headers:
            kwargs["extra_headers"] = self.extra_headers
        return kwargs

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Send a chat completion request via LiteLLM."""
        model, temperature = self._prepare_model(model, temperature)
        kwargs = self._base_kwargs(model, messages, max_tokens, temperature)

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            response = await acompletion(**kwargs)
            return self._parse_response(response)
        except Exception as e:
            return LLMResponse(
                content=f"Error calling LLM: {str(e)}",
                finish_reason="error",
            )

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a chat completion response token by token via LiteLLM."""
        model, temperature = self._prepare_model(model, temperature)
        kwargs = self._base_kwargs(model, messages, max_tokens, temperature)
        kwargs["stream"] = True

        try:
            response = await acompletion(**kwargs)
            async for chunk in response:
                delta = chunk.choices[0].delta
                text = getattr(delta, "content", None) or ""
                finish = chunk.choices[0].finish_reason
                if text or finish:
                    yield StreamChunk(delta=text, finish_reason=finish)
        except Exception as e:
            yield StreamChunk(
                delta=f"Error calling LLM: {str(e)}", finish_reason="error"
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

                tool_calls.append(
                    ToolCallRequest(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=args,
                    )
                )

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
