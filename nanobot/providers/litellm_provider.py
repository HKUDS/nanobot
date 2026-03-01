"""LiteLLM provider implementation for multi-provider support."""

import asyncio
import json
import json_repair
import os
import random
import secrets
import string
from typing import Any

import litellm
from litellm import acompletion
from loguru import logger

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.providers.registry import find_by_model, find_gateway


# Standard OpenAI chat-completion message keys plus reasoning_content for
# thinking-enabled models (Kimi k2.5, DeepSeek-R1, etc.).
_ALLOWED_MSG_KEYS = frozenset({"role", "content", "tool_calls", "tool_call_id", "name", "reasoning_content", "thinking_blocks"})
_ALNUM = string.ascii_letters + string.digits

def _short_tool_id() -> str:
    """Generate a 9-char alphanumeric ID compatible with all providers (incl. Mistral)."""
    return "".join(secrets.choice(_ALNUM) for _ in range(9))


class LiteLLMProvider(LLMProvider):
    """
    LLM provider using LiteLLM for multi-provider support.
    
    Supports OpenRouter, Anthropic, OpenAI, Gemini, MiniMax, and many other providers through
    a unified interface.  Provider-specific logic is driven by the registry
    (see providers/registry.py) — no if-elif chains needed here.
    """
    
    RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}
    DEFAULT_MAX_RETRIES = 4
    DEFAULT_RETRY_BASE_DELAY_SEC = 0.75
    DEFAULT_RETRY_MAX_DELAY_SEC = 8.0

    def __init__(
        self, 
        api_key: str | None = None, 
        api_base: str | None = None,
        default_model: str = "anthropic/claude-opus-4-5",
        fallback_model: str | None = None,
        llm_policy: Any | None = None,
        extra_headers: dict[str, str] | None = None,
        provider_name: str | None = None,
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.fallback_model = fallback_model.strip() if fallback_model and fallback_model.strip() else None
        self._llm_policy = self._coerce_policy(llm_policy)
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
            model = self._canonicalize_explicit_prefix(model, spec.name, spec.litellm_prefix)
            if not any(model.startswith(s) for s in spec.skip_prefixes):
                model = f"{spec.litellm_prefix}/{model}"

        return model

    @staticmethod
    def _canonicalize_explicit_prefix(model: str, spec_name: str, canonical_prefix: str) -> str:
        """Normalize explicit provider prefixes like `github-copilot/...`."""
        if "/" not in model:
            return model
        prefix, remainder = model.split("/", 1)
        if prefix.lower().replace("-", "_") != spec_name:
            return model
        return f"{canonical_prefix}/{remainder}"

    @staticmethod
    def _coerce_policy(policy: Any) -> dict[str, Any]:
        """Normalize policy object into a plain dict."""
        if policy is None:
            return {}
        if isinstance(policy, dict):
            return policy
        model_dump = getattr(policy, "model_dump", None)
        if callable(model_dump):
            try:
                data = model_dump()
                if isinstance(data, dict):
                    return data
            except Exception:
                return {}
        return {}

    def _policy_section(self, key: str) -> dict[str, Any]:
        section = self._llm_policy.get(key, {})
        return section if isinstance(section, dict) else {}

    @staticmethod
    def _parse_bool(value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        if not isinstance(value, str):
            return None
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        return None

    def _retryable_status_codes(self) -> set[int]:
        retry_policy = self._policy_section("retry")
        from_policy = retry_policy.get("retryable_status_codes")
        if isinstance(from_policy, list):
            parsed = {
                int(v)
                for v in from_policy
                if isinstance(v, int) or (isinstance(v, str) and v.isdigit())
            }
            if parsed:
                return parsed

        raw = os.getenv("NANOBOT_LLM_RETRYABLE_STATUS_CODES")
        if raw:
            parsed = {
                int(part.strip())
                for part in raw.split(",")
                if part.strip().isdigit()
            }
            if parsed:
                return parsed

        return set(self.RETRYABLE_STATUS_CODES)

    def _retry_settings(self) -> tuple[int, float, float]:
        """Read retry settings with precedence: config policy > env > defaults."""
        retry_policy = self._policy_section("retry")

        max_retries = self.DEFAULT_MAX_RETRIES
        base_delay = self.DEFAULT_RETRY_BASE_DELAY_SEC
        max_delay = self.DEFAULT_RETRY_MAX_DELAY_SEC

        from_policy_retries = retry_policy.get("max_retries")
        if isinstance(from_policy_retries, int):
            max_retries = max(0, from_policy_retries)
        else:
            raw_max_retries = os.getenv("NANOBOT_LLM_MAX_RETRIES")
            if raw_max_retries is not None:
                try:
                    max_retries = max(0, int(raw_max_retries))
                except ValueError:
                    pass

        from_policy_base = retry_policy.get("base_delay_sec")
        if isinstance(from_policy_base, (int, float)):
            base_delay = max(0.0, float(from_policy_base))
        else:
            raw_base_delay = os.getenv("NANOBOT_LLM_RETRY_BASE_DELAY_SEC")
            if raw_base_delay is not None:
                try:
                    base_delay = max(0.0, float(raw_base_delay))
                except ValueError:
                    pass

        from_policy_max = retry_policy.get("max_delay_sec")
        if isinstance(from_policy_max, (int, float)):
            max_delay = max(0.0, float(from_policy_max))
        else:
            raw_max_delay = os.getenv("NANOBOT_LLM_RETRY_MAX_DELAY_SEC")
            if raw_max_delay is not None:
                try:
                    max_delay = max(0.0, float(raw_max_delay))
                except ValueError:
                    pass

        if max_delay < base_delay:
            max_delay = base_delay

        return max_retries, base_delay, max_delay

    def _fallback_settings(self) -> tuple[bool, bool]:
        """Read fallback settings with precedence: config policy > env > defaults."""
        fallback_policy = self._policy_section("fallback")
        enabled = True
        retryable_only = True

        from_policy_enabled = fallback_policy.get("enabled")
        if isinstance(from_policy_enabled, bool):
            enabled = from_policy_enabled
        else:
            raw_enabled = os.getenv("NANOBOT_LLM_FALLBACK_ENABLED")
            parsed_enabled = self._parse_bool(raw_enabled)
            if parsed_enabled is not None:
                enabled = parsed_enabled

        from_policy_retryable_only = fallback_policy.get("retryable_errors_only")
        if isinstance(from_policy_retryable_only, bool):
            retryable_only = from_policy_retryable_only
        else:
            raw_retryable_only = os.getenv("NANOBOT_LLM_FALLBACK_RETRYABLE_ONLY")
            parsed_retryable_only = self._parse_bool(raw_retryable_only)
            if parsed_retryable_only is not None:
                retryable_only = parsed_retryable_only

        return enabled, retryable_only

    def _extract_status_code(self, error: Exception) -> int | None:
        """Extract HTTP status code from provider exception when available."""
        status_code = getattr(error, "status_code", None)
        if isinstance(status_code, int):
            return status_code

        response = getattr(error, "response", None)
        if response is not None:
            response_status = getattr(response, "status_code", None)
            if isinstance(response_status, int):
                return response_status

        return None

    def _is_retryable_error(self, error: Exception) -> bool:
        """Decide whether this exception is safe to retry."""
        status_code = self._extract_status_code(error)
        if status_code in self._retryable_status_codes():
            return True

        retryable_error_names = {
            "RateLimitError",
            "Timeout",
            "TimeoutError",
            "APIConnectionError",
            "ServiceUnavailableError",
            "InternalServerError",
        }
        return error.__class__.__name__ in retryable_error_names

    def _retry_delay(self, attempt: int, base_delay: float, max_delay: float) -> float:
        """Exponential backoff with small jitter."""
        delay = min(max_delay, base_delay * (2 ** attempt))
        jitter = random.uniform(0.0, min(0.4, delay * 0.2))
        return delay + jitter
    
    def _supports_cache_control(self, model: str) -> bool:
        """Return True when the provider supports cache_control on content blocks."""
        if self._gateway is not None:
            return self._gateway.supports_prompt_caching
        spec = find_by_model(model)
        return spec is not None and spec.supports_prompt_caching

    def _apply_cache_control(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
        """Return copies of messages and tools with cache_control injected."""
        new_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                content = msg["content"]
                if isinstance(content, str):
                    new_content = [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}]
                else:
                    new_content = list(content)
                    new_content[-1] = {**new_content[-1], "cache_control": {"type": "ephemeral"}}
                new_messages.append({**msg, "content": new_content})
            else:
                new_messages.append(msg)

        new_tools = tools
        if tools:
            new_tools = list(tools)
            new_tools[-1] = {**new_tools[-1], "cache_control": {"type": "ephemeral"}}

        return new_messages, new_tools

    def _apply_model_overrides(self, model: str, kwargs: dict[str, Any]) -> None:
        """Apply model-specific parameter overrides from the registry."""
        model_lower = model.lower()
        spec = find_by_model(model)
        if spec:
            for pattern, overrides in spec.model_overrides:
                if pattern in model_lower:
                    kwargs.update(overrides)
                    return
    
    @staticmethod
    def _sanitize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Strip non-standard keys and ensure assistant messages have a content key."""
        sanitized = []
        for msg in messages:
            clean = {k: v for k, v in msg.items() if k in _ALLOWED_MSG_KEYS}
            # Strict providers require "content" even when assistant only has tool_calls
            if clean.get("role") == "assistant" and "content" not in clean:
                clean["content"] = None
            sanitized.append(clean)
        return sanitized

    def _build_chat_kwargs(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
        temperature: float,
        reasoning_effort: str | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": self._sanitize_messages(self._sanitize_empty_content(messages)),
            "max_tokens": max_tokens,
            "temperature": temperature,
            # Keep retry behavior in this class for cross-provider consistency.
            "num_retries": 0,
            "max_retries": 0,
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

        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
            kwargs["drop_params"] = True

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        return kwargs

    async def _call_with_retries(
        self,
        kwargs: dict[str, Any],
        max_retries: int,
        base_delay: float,
        max_delay: float,
    ) -> tuple[Any | None, Exception | None]:
        last_error: Exception | None = None
        model_name = str(kwargs.get("model", "unknown"))

        for attempt in range(max_retries + 1):
            try:
                return await acompletion(**kwargs), None
            except Exception as e:
                last_error = e
                if attempt >= max_retries or not self._is_retryable_error(e):
                    break

                wait_sec = self._retry_delay(
                    attempt=attempt,
                    base_delay=base_delay,
                    max_delay=max_delay,
                )
                logger.warning(
                    "LLM call failed ({err}) model={model}; retry {retry}/{total} in {wait:.2f}s",
                    err=e.__class__.__name__,
                    model=model_name,
                    retry=attempt + 1,
                    total=max_retries,
                    wait=wait_sec,
                )
                await asyncio.sleep(wait_sec)

        return None, last_error

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
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
        primary_raw_model = model or self.default_model
        primary_model = self._resolve_model(primary_raw_model)
        fallback_raw_model = self.fallback_model if self.fallback_model else None
        fallback_model = self._resolve_model(fallback_raw_model) if fallback_raw_model else None

        if self._supports_cache_control(primary_raw_model):
            messages, tools = self._apply_cache_control(messages, tools)

        # Clamp max_tokens to at least 1 — negative or zero values cause
        # LiteLLM to reject the request with "max_tokens must be at least 1".
        max_tokens = max(1, max_tokens)

        max_retries, base_delay, max_delay = self._retry_settings()
        primary_kwargs = self._build_chat_kwargs(
            model=primary_model,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
        )

        response, primary_error = await self._call_with_retries(
            kwargs=primary_kwargs,
            max_retries=max_retries,
            base_delay=base_delay,
            max_delay=max_delay,
        )
        if response is not None:
            return self._parse_response(response)

        last_error = primary_error

        fallback_enabled, retryable_only = self._fallback_settings()
        can_fallback = (
            fallback_enabled
            and fallback_model
            and fallback_model != primary_model
            and primary_error is not None
            and (self._is_retryable_error(primary_error) if retryable_only else True)
        )
        if can_fallback:
            logger.warning(
                "Primary model failed after retries; switching fallback model {fallback}",
                fallback=fallback_model,
            )
            fallback_kwargs = self._build_chat_kwargs(
                model=fallback_model,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
            )
            response, fallback_error = await self._call_with_retries(
                kwargs=fallback_kwargs,
                max_retries=max_retries,
                base_delay=base_delay,
                max_delay=max_delay,
            )
            if response is not None:
                return self._parse_response(response)
            last_error = fallback_error or primary_error

        # Return error as content for graceful handling.
        return LLMResponse(
            content=f"Error calling LLM: {str(last_error) if last_error else 'unknown error'}",
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
                    id=_short_tool_id(),
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
        
        reasoning_content = getattr(message, "reasoning_content", None) or None
        thinking_blocks = getattr(message, "thinking_blocks", None) or None
        
        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage=usage,
            reasoning_content=reasoning_content,
            thinking_blocks=thinking_blocks,
        )
    
    def get_default_model(self) -> str:
        """Get the default model."""
        return self.default_model
