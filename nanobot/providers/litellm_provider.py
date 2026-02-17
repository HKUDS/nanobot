"""LiteLLM provider implementation for multi-provider support."""

import json
import json_repair
import os
import re
from typing import Any

import litellm
from litellm import acompletion
from loguru import logger

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.providers.registry import find_by_model, find_gateway
from nanobot.utils.errors import (
    ProviderError,
    ProviderConnectionError,
    ProviderRateLimitError,
    ProviderAuthError,
    ProviderModelNotFoundError,
    ProviderResponseError,
    ErrorInfo,
    log_error,
)


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
        if not spec.env_key:
            # OAuth/provider-only specs (for example: openai_codex)
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
        
        Raises:
            ProviderRateLimitError: If rate limit is exceeded.
            ProviderConnectionError: If connection fails.
            ProviderAuthError: If authentication fails.
            ProviderModelNotFoundError: If model is not found.
            ProviderError: For other provider errors.
        """
        model = self._resolve_model(model or self.default_model)
        
        # Clamp max_tokens to at least 1 — negative or zero values cause
        # LiteLLM to reject the request with "max_tokens must be at least 1".
        max_tokens = max(1, max_tokens)
        
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
            # Convert to typed provider errors
            raise self._classify_error(e, model) from e
    
    def _classify_error(self, error: Exception, model: str) -> ProviderError:
        """
        Classify a LiteLLM exception into a typed provider error.
        
        Args:
            error: The original exception from LiteLLM.
            model: The model being used when the error occurred.
        
        Returns:
            Appropriate ProviderError subclass.
        """
        error_str = str(error).lower()
        error_type = type(error).__name__
        
        # Extract retry-after header if present
        retry_after = self._extract_retry_after(error)
        
        # Rate limit errors
        if "rate limit" in error_str or "too many requests" in error_str or "429" in error_str:
            log_error(error, "Rate limit exceeded", extra_context={"model": model})
            return ProviderRateLimitError(
                f"Rate limit exceeded for {model}",
                retry_after=retry_after,
                context={"model": model, "error_type": error_type}
            )
        
        # Authentication errors
        if any(s in error_str for s in ["unauthorized", "invalid api key", "authentication", "401", "403"]):
            log_error(error, "Authentication failed", extra_context={"model": model})
            return ProviderAuthError(
                f"Authentication failed for {model}. Check your API key.",
                context={"model": model, "error_type": error_type}
            )
        
        # Model not found errors
        if any(s in error_str for s in ["model not found", "does not exist", "unknown model", "404"]):
            log_error(error, "Model not found", extra_context={"model": model})
            return ProviderModelNotFoundError(
                f"Model '{model}' not found or not available.",
                context={"model": model, "error_type": error_type}
            )
        
        # Connection errors
        if any(s in error_str for s in ["connection", "timeout", "network", "unreachable", "refused"]):
            log_error(error, "Connection failed", extra_context={"model": model})
            return ProviderConnectionError(
                f"Failed to connect to provider for {model}",
                context={"model": model, "error_type": error_type}
            )
        
        # Context length exceeded
        if "context length" in error_str or "maximum context" in error_str or "token limit" in error_str:
            log_error(error, "Context length exceeded", extra_context={"model": model})
            return ProviderResponseError(
                f"Context length exceeded for {model}. Try reducing the conversation length.",
                context={"model": model, "error_type": error_type}
            )
        
        # Content filter / safety
        if any(s in error_str for s in ["content filter", "safety", "inappropriate", "flagged"]):
            log_error(error, "Content filtered", extra_context={"model": model})
            return ProviderResponseError(
                f"Request blocked by content filter for {model}",
                context={"model": model, "error_type": error_type}
            )
        
        # Overloaded / service unavailable
        if any(s in error_str for s in ["overloaded", "503", "service unavailable", "capacity"]):
            log_error(error, "Service overloaded", extra_context={"model": model})
            return ProviderConnectionError(
                f"Provider is overloaded. Please try again later.",
                context={"model": model, "error_type": error_type}
            )
        
        # Generic provider error
        log_error(error, "Provider error", extra_context={"model": model})
        return ProviderError(
            f"Error from provider: {error}",
            context={"model": model, "error_type": error_type}
        )
    
    def _extract_retry_after(self, error: Exception) -> float | None:
        """
        Extract retry-after value from error if available.
        
        Args:
            error: The exception to extract from.
        
        Returns:
            Retry-after seconds if found, None otherwise.
        """
        error_str = str(error)
        
        # Try to parse retry-after from error message
        # Common patterns: "retry after 30s", "wait 60 seconds"
        patterns = [
            r"retry.?after\s*(\d+(?:\.\d+)?)\s*s?",
            r"wait\s*(\d+(?:\.\d+)?)\s*s?econds?",
            r"retry.?in\s*(\d+(?:\.\d+)?)\s*s?",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, error_str, re.IGNORECASE)
            if match:
                return float(match.group(1))
        
        # Check for LiteLLM specific attributes
        if hasattr(error, "response"):
            response = error.response
            if hasattr(response, "headers"):
                retry_after = response.headers.get("retry-after")
                if retry_after:
                    try:
                        return float(retry_after)
                    except ValueError:
                        pass
        
        return None
    
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
        
        reasoning_content = getattr(message, "reasoning_content", None)
        
        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage=usage,
            reasoning_content=reasoning_content,
        )
    
    def get_default_model(self) -> str:
        """Get the default model."""
        return self.default_model
