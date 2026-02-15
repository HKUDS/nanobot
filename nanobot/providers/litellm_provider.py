"""LiteLLM provider implementation for multi-provider support."""

import json
import json_repair
import os
from typing import Any

import litellm
from litellm import acompletion

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.providers.registry import find_by_model, find_gateway
from nanobot.providers.opencode import is_opencode_model, strip_opencode_prefix, chat_opencode
from nanobot.providers.custom.kilocode import is_kilocode_model, resolve_kilocode_model


class LiteLLMProvider(LLMProvider):
    """
    LLM provider using LiteLLM for multi-provider support.
    
    Supports OpenRouter, Anthropic, OpenAI, Gemini, MiniMax, and many other providers through
    a unified interface.  Provider-specific logic is driven by the registry
    (see providers/registry.py) — no if-elif chains needed here.
    """
    
    def __init__(
        self, 
        api_key: str | None = None, 
        api_base: str | None = None,
        default_model: str = "anthropic/claude-opus-4-5",
        extra_headers: dict[str, str] | None = None,
        provider_name: str | None = None,
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.extra_headers = extra_headers or {}
        
        # Detect gateway / local deployment.
        # provider_name (from config key) is the primary signal;
        # api_key / api_base are fallback for auto-detection.
        self._gateway = find_gateway(provider_name, api_key, api_base)
        
        # Configure environment variables
        if api_key:
            self._setup_env(api_key, api_base, default_model)
        
        if api_base:
            litellm.api_base = api_base
        
        # Disable LiteLLM logging noise
        litellm.suppress_debug_info = True
        # Drop unsupported parameters for providers (e.g., gpt-5 rejects some params)
        litellm.drop_params = True
    
    def _setup_env(self, api_key: str, api_base: str | None, model: str) -> None:
        """Set environment variables based on detected provider."""
        spec = self._gateway or find_by_model(model)
        if not spec:
            return

        # Gateway/local overrides existing env; standard provider doesn't
        if self._gateway:
            os.environ[spec.env_key] = api_key
        else:
            os.environ.setdefault(spec.env_key, api_key)

        # Resolve env_extras placeholders:
        #   {api_key}  → user's API key
        #   {api_base} → user's api_base, falling back to spec.default_api_base
        effective_base = api_base or spec.default_api_base
        for env_name, env_val in spec.env_extras:
            resolved = env_val.replace("{api_key}", api_key)
            resolved = resolved.replace("{api_base}", effective_base)
            os.environ.setdefault(env_name, resolved)
    
    def _resolve_model(self, model: str) -> str:
        """Resolve model name by applying provider/gateway prefixes."""
        if self._gateway:
            # Gateway mode: apply gateway prefix, skip provider-specific prefixes
            prefix = self._gateway.litellm_prefix
            if self._gateway.strip_model_prefix:
                model = model.split("/")[-1]
            if prefix and not model.startswith(f"{prefix}/"):
                model = f"{prefix}/{model}"
            return model
        
        # Standard mode: auto-prefix for known providers
        spec = find_by_model(model)
        if spec and spec.litellm_prefix:
            if not any(model.startswith(s) for s in spec.skip_prefixes):
                model = f"{spec.litellm_prefix}/{model}"
        
        return model
    
    def _apply_model_overrides(self, model: str, kwargs: dict[str, Any]) -> None:
        """Apply model-specific parameter overrides from the registry."""
        model_lower = model.lower()
        spec = find_by_model(model)
        if spec:
            for pattern, overrides in spec.model_overrides:
                if pattern in model_lower:
                    kwargs.update(overrides)
                    return
    
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        job_id: str | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
    ) -> LLMResponse:
        """
        Send a chat completion request via LiteLLM.
        
        Args:
            messages: List of message dicts with 'role' and 'content'.
            tools: Optional list of tool definitions in OpenAI format.
            model: Model identifier (e.g., 'anthropic/claude-sonnet-4-5').
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.
            job_id: Optional job ID for timeline tracking.
            channel: Optional channel name for timeline tracking.
            chat_id: Optional chat ID for timeline tracking.
        
        Returns:
            LLMResponse with content and/or tool calls.
        """
        original_model = model or self.default_model

        # Clamp max_tokens to at least 1 — negative or zero values cause
        # LiteLLM to reject the request with "max_tokens must be at least 1".
        max_tokens = max(1, max_tokens)

        # Route OpenCode models FIRST (before resolving) - uses separate OpenAI client
        if is_opencode_model(original_model):
            return await chat_opencode(
                model=strip_opencode_prefix(original_model),
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
                job_id=job_id,
                channel=channel,
                chat_id=chat_id,
            )

        # Route Kilo Code models (requires custom headers)
        if is_kilocode_model(original_model):
            from nanobot.providers.custom.kilocode import chat_kilocode
            content, tool_calls, finish_reason, usage, thinking = await chat_kilocode(
                model=resolve_kilocode_model(original_model),
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
                api_key=self.api_key or "",
            )
            # Convert tuple response to LLMResponse
            tool_call_requests = []
            for tc in tool_calls:
                tool_call_requests.append(ToolCallRequest(
                    id=tc.get("id", ""),
                    name=tc.get("name", ""),
                    arguments=tc.get("arguments", {})
                ))
            return LLMResponse(
                content=content,
                tool_calls=tool_call_requests,
                finish_reason=finish_reason,
                usage=usage,
                thinking=thinking,
            )

        model = self._resolve_model(original_model)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        
        # Apply model-specific overrides (e.g. kimi-k2.5 temperature)
        self._apply_model_overrides(model, kwargs)
        
        # Pass api_key directly — more reliable than env vars alone
        if self.api_key:
            kwargs["api_key"] = self.api_key
        
        # Pass api_base for custom endpoints
        if self.api_base:
            kwargs["api_base"] = self.api_base
        
        # Pass extra headers (e.g. APP-Code for AiHubMix)
        if self.extra_headers:
            kwargs["extra_headers"] = self.extra_headers
        
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
                    args = json_repair.loads(args)
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

        # Extract thinking/reasoning content from various places
        thinking_content = None
        if hasattr(message, "thinking") and message.thinking:
            thinking_content = message.thinking
        elif hasattr(message, "reasoning_content") and message.reasoning_content:
            thinking_content = message.reasoning_content
        elif hasattr(message, "reasoning") and message.reasoning:
            thinking_content = message.reasoning

        # Check provider_specific_fields for thinking content
        if not thinking_content and hasattr(response, "provider_specific_fields"):
            psf = response.provider_specific_fields
            if psf:
                if "thinking" in psf:
                    thinking_content = psf["thinking"]
                elif "reasoning_content" in psf:
                    thinking_content = psf["reasoning_content"]

        content = message.content
        if not content and thinking_content:
            # Use thinking as main content if content is empty
            content = thinking_content
            thinking_content = None

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage=usage,
            reasoning_content=thinking_content,
            thinking=thinking_content,
        )
    
    def get_default_model(self) -> str:
        """Get the default model."""
        return self.default_model
