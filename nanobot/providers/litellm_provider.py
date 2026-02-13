"""LiteLLM provider implementation for multi-provider support."""

import asyncio
import json
import os
from typing import Any

import litellm
from litellm import acompletion

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.providers.registry import find_by_model, find_by_name, find_gateway


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
        self._selected_spec = find_by_name(provider_name) if provider_name else None
        api_base = self._normalize_api_base(api_base)
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

    def _normalize_api_base(self, api_base: str | None) -> str | None:
        """Normalize provider-specific base URLs before passing to LiteLLM."""
        if not api_base:
            return api_base
        if self._selected_spec and self._selected_spec.name in {"ollama_local", "ollama_cloud"}:
            # LiteLLM Ollama provider expects host base and appends /api/* internally.
            if api_base.endswith("/api"):
                return api_base[:-4]
            if api_base.endswith("/api/"):
                return api_base[:-5]
        return api_base
    
    def _setup_env(self, api_key: str, api_base: str | None, model: str) -> None:
        """Set environment variables based on detected provider."""
        spec = self._gateway or self._selected_spec or find_by_model(model)
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
        spec = self._selected_spec or find_by_model(model)
        if spec and spec.litellm_prefix:
            if not any(model.startswith(s) for s in spec.skip_prefixes):
                model = f"{spec.litellm_prefix}/{model}"
        
        return model
    
    def _apply_model_overrides(self, model: str, kwargs: dict[str, Any]) -> None:
        """Apply model-specific parameter overrides from the registry."""
        model_lower = model.lower()
        spec = self._selected_spec or find_by_model(model)
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
        """
        model = self._resolve_model(model or self.default_model)
        
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
        
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                response = await acompletion(**kwargs)
                return self._parse_response(response)
            except Exception as e:
                if attempt < max_attempts and self._is_transient_network_error(e):
                    await asyncio.sleep(0.5 * attempt)
                    continue
                # Return error as content for graceful handling
                return LLMResponse(
                    content=f"Error calling LLM: {str(e)}",
                    finish_reason="error",
                )

        return LLMResponse(
            content="Error calling LLM: retries exhausted",
            finish_reason="error",
        )

    def _is_transient_network_error(self, error: Exception) -> bool:
        """Detect retryable transient network/provider gateway errors."""
        msg = str(error).lower()
        retry_signals = (
            "apiconnectionerror",
            "connection reset",
            "connection aborted",
            "temporary failure",
            "timed out",
            "timeout",
            "502",
            "503",
            "504",
            "bad gateway",
            "service unavailable",
        )
        return any(signal in msg for signal in retry_signals)
    
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
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw": args}
                
                tool_calls.append(ToolCallRequest(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                ))

        if not tool_calls and isinstance(message.content, str):
            fallback_call = self._parse_tool_call_from_content(message.content)
            if fallback_call:
                tool_calls.append(fallback_call)
        
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

    def _parse_tool_call_from_content(self, content: str) -> ToolCallRequest | None:
        """Best-effort parser for models that emit tool calls as plain JSON text."""
        decoder = json.JSONDecoder()

        for idx, char in enumerate(content):
            if char != "{":
                continue
            try:
                obj, _ = decoder.raw_decode(content[idx:])
            except Exception:
                continue

            if not isinstance(obj, dict):
                continue

            # format A: {"name": "web_search", "arguments": {...}}
            name = obj.get("name")
            arguments = obj.get("arguments")
            if isinstance(name, str) and isinstance(arguments, dict):
                return ToolCallRequest(
                    id="tool_call_fallback_1",
                    name=name,
                    arguments=arguments,
                )

            # format B: {"function": {"name": "...", "arguments": {...}}}
            function = obj.get("function")
            if isinstance(function, dict):
                func_name = function.get("name")
                func_args = function.get("arguments")
                if isinstance(func_name, str):
                    if isinstance(func_args, str):
                        try:
                            func_args = json.loads(func_args)
                        except Exception:
                            func_args = {"raw": func_args}
                    if isinstance(func_args, dict):
                        return ToolCallRequest(
                            id="tool_call_fallback_1",
                            name=func_name,
                            arguments=func_args,
                        )

        return None
    
    def get_default_model(self) -> str:
        """Get the default model."""
        return self.default_model
