"""LiteLLM provider implementation for multi-provider support."""

from __future__ import annotations

from typing import Any, AsyncIterator

import json_repair
import litellm
from litellm import acompletion

from nanobot.providers.base import LLMProvider, LLMResponse, StreamChunk, ToolCallRequest
from nanobot.providers.registry import find_by_model, find_gateway

# Standard OpenAI chat-completion message keys; extras (e.g. reasoning_content) are stripped for strict providers.
_ALLOWED_MSG_KEYS = frozenset({"role", "content", "tool_calls", "tool_call_id", "name"})


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
        *,
        llm_timeout_s: float = 60.0,
        llm_max_retries: int = 1,
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.extra_headers = extra_headers or {}
        self._timeout_s = max(1.0, llm_timeout_s)
        self._max_retries = max(0, llm_max_retries)

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
        import os

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
                    new_content = [
                        {"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}
                    ]
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
        """Strip non-standard keys, ensure content key, and repair orphaned tool_calls."""
        sanitized = []
        for msg in messages:
            clean = {k: v for k, v in msg.items() if k in _ALLOWED_MSG_KEYS}
            # Strict providers require "content" even when assistant only has tool_calls
            if clean.get("role") == "assistant" and "content" not in clean:
                clean["content"] = None
            sanitized.append(clean)

        # Repair orphaned tool_calls: every tool_call_id in an assistant message
        # must have a following tool-role message with the same tool_call_id.
        # If a crash interrupted tool execution, the result messages may be missing.
        tool_result_ids: set[str] = {
            m["tool_call_id"] for m in sanitized if m.get("role") == "tool" and "tool_call_id" in m
        }
        repaired = []
        for msg in sanitized:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                orphaned = [
                    tc
                    for tc in msg["tool_calls"]
                    if tc.get("id") and tc["id"] not in tool_result_ids
                ]
                if orphaned:
                    # Keep only tool_calls that have matching results
                    valid = [tc for tc in msg["tool_calls"] if tc["id"] in tool_result_ids]
                    if valid:
                        repaired.append({**msg, "tool_calls": valid})
                    else:
                        # No valid tool_calls remain — drop them entirely
                        repaired.append({k: v for k, v in msg.items() if k != "tool_calls"})
                    continue
            repaired.append(msg)
        return repaired

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        metadata: dict[str, Any] | None = None,
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
        original_model = model or self.default_model
        model = self._resolve_model(original_model)

        if self._supports_cache_control(original_model):
            messages, tools = self._apply_cache_control(messages, tools)

        # Clamp max_tokens to at least 1 — negative or zero values cause
        # LiteLLM to reject the request with "max_tokens must be at least 1".
        max_tokens = max(1, max_tokens)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": self._sanitize_messages(self._sanitize_empty_content(messages)),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        # Bound remote latency and retry fan-out so a single request cannot block indefinitely.
        kwargs["timeout"] = self._timeout_s
        kwargs["num_retries"] = self._max_retries

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

        if metadata:
            kwargs["metadata"] = metadata

        try:
            response = await acompletion(**kwargs)
            return self._parse_response(response)
        except Exception as e:  # crash-barrier: LLM provider errors are varied
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

                tool_calls.append(
                    ToolCallRequest(
                        id=tc.id[:40] if tc.id else tc.id,
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

        reasoning_content = getattr(message, "reasoning_content", None) or None

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

    # ------------------------------------------------------------------
    # Streaming (Step 15)
    # ------------------------------------------------------------------

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream chat completion tokens via ``litellm.acompletion(stream=True)``."""
        original_model = model or self.default_model
        resolved = self._resolve_model(original_model)

        if self._supports_cache_control(original_model):
            messages, tools = self._apply_cache_control(messages, tools)

        max_tokens = max(1, max_tokens)

        kwargs: dict[str, Any] = {
            "model": resolved,
            "messages": self._sanitize_messages(self._sanitize_empty_content(messages)),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        kwargs["timeout"] = self._timeout_s
        kwargs["num_retries"] = self._max_retries

        self._apply_model_overrides(resolved, kwargs)

        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if self.extra_headers:
            kwargs["extra_headers"] = self.extra_headers
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if metadata:
            kwargs["metadata"] = metadata

        try:
            response = await acompletion(**kwargs)

            # Accumulators for tool-call fragments
            tc_fragments: dict[int, dict[str, Any]] = {}

            async for chunk in response:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta is None:
                    continue

                content_delta = getattr(delta, "content", None)
                reasoning_delta = getattr(delta, "reasoning_content", None)
                finish_reason = chunk.choices[0].finish_reason if chunk.choices else None

                # Accumulate tool-call deltas
                if hasattr(delta, "tool_calls") and delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index if hasattr(tc_delta, "index") else 0
                        if idx not in tc_fragments:
                            tc_fragments[idx] = {
                                "id": "",
                                "name": "",
                                "arguments": "",
                            }
                        frag = tc_fragments[idx]
                        if hasattr(tc_delta, "id") and tc_delta.id:
                            frag["id"] += tc_delta.id
                        if hasattr(tc_delta, "function") and tc_delta.function:
                            if tc_delta.function.name:
                                frag["name"] += tc_delta.function.name
                            if tc_delta.function.arguments:
                                frag["arguments"] += tc_delta.function.arguments

                # Parse usage from the final chunk if present
                usage: dict[str, int] = {}
                raw_usage = getattr(chunk, "usage", None)
                if raw_usage and hasattr(raw_usage, "total_tokens"):
                    usage = {
                        "prompt_tokens": getattr(raw_usage, "prompt_tokens", 0) or 0,
                        "completion_tokens": getattr(raw_usage, "completion_tokens", 0) or 0,
                        "total_tokens": getattr(raw_usage, "total_tokens", 0) or 0,
                    }

                done = finish_reason is not None

                # Build tool calls on the final chunk
                tool_calls: list[ToolCallRequest] = []
                if done and tc_fragments:
                    for _idx in sorted(tc_fragments):
                        frag = tc_fragments[_idx]
                        try:
                            args = json_repair.loads(frag["arguments"])
                        except (ValueError, KeyError, TypeError):
                            args = {}
                        tool_calls.append(
                            ToolCallRequest(
                                id=frag["id"][:40],
                                name=frag["name"],
                                arguments=args if isinstance(args, dict) else {},
                            )
                        )

                yield StreamChunk(
                    content_delta=content_delta,
                    reasoning_delta=reasoning_delta,
                    finish_reason=finish_reason,
                    usage=usage,
                    tool_calls=tool_calls,
                    done=done,
                )

        except Exception as e:  # crash-barrier: streaming errors are varied
            yield StreamChunk(
                content_delta=f"Error calling LLM: {e}",
                finish_reason="error",
                done=True,
            )

    async def aclose(self) -> None:
        """Close cached async clients used by LiteLLM."""
        close_async_clients = getattr(litellm, "close_litellm_async_clients", None)
        if not callable(close_async_clients):
            return
        try:
            await close_async_clients()
        except (RuntimeError, OSError, AttributeError):
            return
