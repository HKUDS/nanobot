"""LiteLLM provider implementation for multi-provider support."""

import json
import os
from typing import Any

import httpx
import litellm
from litellm import acompletion

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.providers.registry import find_by_model, find_gateway, find_by_name


# Copilot token manager singleton (lazy-loaded)
_copilot_token_manager = None
_copilot_api_base = None


def _get_copilot_token_manager():
    """Get or create Copilot token manager singleton."""
    global _copilot_token_manager
    if _copilot_token_manager is None:
        from nanobot.providers.copilot_token import CopilotTokenManager
        _copilot_token_manager = CopilotTokenManager()
    return _copilot_token_manager


class LiteLLMProvider(LLMProvider):
    """
    LLM provider using LiteLLM for multi-provider support.

    Supports OpenRouter, Anthropic, OpenAI, Gemini, GitHub Copilot, and many other
    providers through a unified interface. Provider-specific logic is driven by the
    registry (see providers/registry.py) — no if-elif chains needed here.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "anthropic/claude-opus-4-5",
        extra_headers: dict[str, str] | None = None,
        provider_name: str | None = None,
        github_token: str | None = None,
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.extra_headers = extra_headers or {}
        self._github_token = github_token
        self._is_copilot = False
        self._copilot_token: str | None = None
        self._copilot_api_base: str | None = None

        # Detect gateway / local deployment.
        # provider_name (from config key) is the primary signal;
        # api_key / api_base are fallback for auto-detection.
        self._gateway = find_gateway(provider_name, api_key, api_base)

        # Check if this is Copilot provider
        spec = self._gateway or find_by_model(default_model)

        # Additional check: Copilot uses GitHub tokens (ghu_ prefix)
        # This ensures we detect Copilot even when model name doesn't contain "copilot"
        is_copilot_by_key = api_key and api_key.startswith("ghu_")
        is_copilot_by_name = spec and spec.name == "copilot"

        if is_copilot_by_name or is_copilot_by_key:
            self._is_copilot = True
            # For Copilot, api_key should be the GitHub token
            if api_key and not github_token:
                self._github_token = api_key
            # Update gateway if detected by key
            if is_copilot_by_key and not self._gateway:
                self._gateway = find_by_name("copilot")

        # Configure environment variables
        if api_key and not self._is_copilot:
            self._setup_env(api_key, api_base, default_model)

        if api_base:
            litellm.api_base = api_base

        # Disable LiteLLM logging noise
        litellm.suppress_debug_info = True
        # Drop unsupported parameters for providers (e.g., gpt-5 rejects some params)
        litellm.drop_params = True

    async def _refresh_copilot_token(self) -> tuple[str, str]:
        """Refresh Copilot token and return (token, api_base)."""
        if not self._github_token:
            raise RuntimeError(
                "GitHub token is required for Copilot. "
                "Set providers.copilot.api_key to your GitHub OAuth token (ghu_...)."
            )

        manager = _get_copilot_token_manager()
        manager.github_token = self._github_token

        token, api_base = await manager.get_copilot_token()
        self._copilot_token = token
        self._copilot_api_base = api_base
        return token, api_base
    
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

        # Handle Copilot token refresh
        if self._is_copilot:
            # Copilot: Use direct httpx call instead of litellm
            # litellm doesn't properly handle custom headers for Copilot
            return await self._call_copilot_direct(messages, tools, model, max_tokens, temperature)

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

    def _normalize_copilot_model(self, model: str) -> str:
        """Normalize model name for Copilot API.

        Copilot expects simple names like 'gpt-4o', not 'gpt-4o-2024-08-06'.
        Just strip any provider prefix and return the base name.
        """
        # Strip provider prefix if present (e.g., "openai/gpt-4o" -> "gpt-4o")
        return model.split("/")[-1]

    async def _call_copilot_direct(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        """Call Copilot API directly using httpx (bypassing litellm header issues)."""
        copilot_token, copilot_api_base = await self._refresh_copilot_token()

        # Normalize model name for Copilot API
        copilot_model = self._normalize_copilot_model(model)

        # Build request body
        body: dict[str, Any] = {
            "model": copilot_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }

        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        # Call Copilot API directly
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{copilot_api_base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {copilot_token}",
                    "Content-Type": "application/json",
                    "User-Agent": "GitHubCopilotChat/0.26.7",
                    "Editor-Version": "vscode/1.96.2",
                },
                json=body,
            )

            if response.status_code != 200:
                return LLMResponse(
                    content=f"Error calling Copilot API: HTTP {response.status_code} - {response.text[:200]}",
                    finish_reason="error",
                )

            # Parse response directly (httpx returns dict, not object)
            return self._parse_copilot_response(response.json())

    def _parse_copilot_response(self, data: dict[str, Any]) -> LLMResponse:
        """Parse Copilot API response (dict) into our standard format."""
        choice = data["choices"][0]
        message = choice["message"]

        tool_calls = []
        if "tool_calls" in message and message["tool_calls"]:
            for tc in message["tool_calls"]:
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

        usage = {}
        if "usage" in data and data["usage"]:
            usage = {
                "prompt_tokens": data["usage"]["prompt_tokens"],
                "completion_tokens": data["usage"]["completion_tokens"],
                "total_tokens": data["usage"]["total_tokens"],
            }

        reasoning_content = message.get("reasoning_content")

        return LLMResponse(
            content=message.get("content"),
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason", "stop"),
            usage=usage,
            reasoning_content=reasoning_content,
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
