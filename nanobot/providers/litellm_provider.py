"""LiteLLM provider implementation for multi-provider support."""

import json
import os
import codecs
import re
import secrets
import string
from typing import Any
from uuid import uuid4

import json_repair
import litellm
from litellm import acompletion
from loguru import logger

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.providers.registry import find_by_model, find_gateway

# Standard OpenAI chat-completion message keys plus reasoning_content for
# thinking-enabled models (Kimi k2.5, DeepSeek-R1, etc.).
_ALLOWED_MSG_KEYS = frozenset({"role", "content", "tool_calls", "tool_call_id", "name", "reasoning_content"})
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

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "anthropic/claude-opus-4-5",
        extra_headers: dict[str, str] | None = None,
        provider_name: str | None = None,
        default_stream: bool = False,
    ):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.extra_headers = extra_headers or {}
        self.default_stream = default_stream

        # Detect gateway / local deployment.
        # provider_name (from config key) is the primary signal;
        # api_key / api_base are fallback for auto-detection.
        self._gateway = find_gateway(provider_name, api_key, api_base)

        # Configure environment variables
        if api_key:
            self._setup_env(api_key, api_base, default_model)

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
            if spec.name == "gemini":
                if model.startswith("gemini/models/"):
                    model = f"gemini/{model[len('gemini/models/'):]}"
                elif model.startswith("models/"):
                    model = model[len("models/"):]
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

    def _preview_text(self, text: str | None, limit: int = 240) -> str:
        """Build a single-line truncated preview for logs."""
        if text is None:
            return "<none>"
        compact = text.replace("\n", "\\n")
        if compact.strip() == "":
            return "<blank>"
        if len(compact) > limit:
            return f"{compact[:limit]}...(truncated)"
        return compact

    @staticmethod
    def _coerce_int(value: Any) -> int:
        """Best-effort conversion for token counters."""
        if value is None:
            return 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _usage_get(source: Any, key: str) -> Any:
        """Read a usage field from either dict-like or object-like payloads."""
        if source is None:
            return None
        if isinstance(source, dict):
            return source.get(key)
        return getattr(source, key, None)

    @classmethod
    def _extract_usage(cls, usage_obj: Any) -> dict[str, int]:
        """Normalize usage payload across providers (OpenAI/Anthropic/etc.)."""
        if not usage_obj:
            return {}

        prompt = cls._coerce_int(
            cls._usage_get(usage_obj, "prompt_tokens") or cls._usage_get(usage_obj, "input_tokens")
        )
        completion = cls._coerce_int(
            cls._usage_get(usage_obj, "completion_tokens") or cls._usage_get(usage_obj, "output_tokens")
        )
        total_raw = cls._usage_get(usage_obj, "total_tokens")
        total = cls._coerce_int(total_raw) if total_raw is not None else prompt + completion

        raw_cache_create = cls._usage_get(usage_obj, "cache_creation_input_tokens")
        cache_create = cls._coerce_int(raw_cache_create)
        cache_read = cls._coerce_int(cls._usage_get(usage_obj, "cache_read_input_tokens"))
        read_from_openai_prompt_details = False

        # OpenAI-style cache metric lives under prompt_tokens_details.cached_tokens.
        if cache_read == 0:
            prompt_details = cls._usage_get(usage_obj, "prompt_tokens_details")
            cache_read = cls._coerce_int(cls._usage_get(prompt_details, "cached_tokens"))
            read_from_openai_prompt_details = cache_read > 0

        # OpenAI doesn't expose cache_creation_input_tokens directly in chat completions.
        # Derive uncached prompt tokens so log hit_rate is meaningful.
        if read_from_openai_prompt_details and raw_cache_create is None:
            cache_create = max(prompt - cache_read, 0)

        usage: dict[str, int] = {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": total,
        }
        if cache_create > 0:
            usage["cache_creation_input_tokens"] = cache_create
        if cache_read > 0:
            usage["cache_read_input_tokens"] = cache_read
        return usage

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

    def _log_response_summary(self, response: LLMResponse) -> None:
        """Log a compact summary of the model response."""
        content_preview = self._preview_text(response.content)
        if response.has_tool_calls:
            names = ", ".join(tc.name for tc in response.tool_calls[:5])
            if len(response.tool_calls) > 5:
                names = f"{names}, ..."
            logger.debug(
                "LLM Response: mode=function_call, "
                f"finish_reason={response.finish_reason}, "
                f"tool_calls={len(response.tool_calls)}, "
                f"tool_names=[{names}], "
                f"content={content_preview}"
            )
        else:
            logger.debug(
                "LLM Response: mode=text, "
                f"finish_reason={response.finish_reason}, "
                f"content={content_preview}"
            )

    @staticmethod
    def _format_exception(exc: Exception) -> str:
        """Return a stable, searchable exception summary."""
        name = type(exc).__name__
        msg = str(exc).strip()
        if msg:
            # Best effort: decode escaped unicode/byte sequences in upstream error payloads.
            try:
                decoded = codecs.decode(msg, "unicode_escape")
                if "\\x" in msg:
                    try:
                        decoded = decoded.encode("latin-1").decode("utf-8")
                    except Exception:
                        pass
                if decoded and decoded != msg:
                    msg = decoded
            except Exception:
                pass
        return f"{name}: {msg}" if msg else name

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        thinking: str | None = None,
        thinking_budget: int = 10000,
        effort: str | None = None,
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

        # Apply model-specific overrides (e.g. kimi-k2.5 temperature)
        self._apply_model_overrides(model, kwargs)

        # Pass api_key directly — more reliable than env vars alone
        if self.api_key:
            kwargs["api_key"] = self.api_key

        # Pass api_base for custom endpoints
        if self.api_base:
            kwargs["api_base"] = self.api_base

        # Pass api_key explicitly to avoid env var interference
        if self.api_key:
            kwargs["api_key"] = self.api_key

        # Pass extra headers (e.g. APP-Code for AiHubMix)
        if self.extra_headers:
            kwargs["extra_headers"] = self.extra_headers

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        # Extended thinking (Anthropic models)
        if thinking == "enabled":
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
        elif thinking == "adaptive":
            kwargs["thinking"] = {"type": "adaptive"}

        # Effort control via output_config (Anthropic native)
        if effort is not None:
            kwargs["output_config"] = {"effort": effort}

        try:
            logger.debug(
                f"LLM Request: model={kwargs.get('model')}, api_base={kwargs.get('api_base')}, "
                f"default_stream={self.default_stream}"
            )
            if self.default_stream:
                stream_kwargs = self._prepare_stream_kwargs(kwargs)
                return await self._stream_chat(stream_kwargs)

            non_stream_kwargs = self._prepare_non_stream_kwargs(kwargs)
            response = await acompletion(**non_stream_kwargs)
            parsed = self._parse_response(response)
            self._log_response_summary(parsed)
            return parsed
        except Exception as e:
            # 根据默认模式互相兜底
            if self.default_stream:
                logger.warning(
                    "Stream call failed, falling back to non-stream: "
                    f"{self._format_exception(e)}"
                )
            else:
                logger.warning(
                    "Non-stream call failed, falling back to stream: "
                    f"{self._format_exception(e)}"
                )
            try:
                if self.default_stream:
                    non_stream_kwargs = self._prepare_non_stream_kwargs(kwargs)
                    response = await acompletion(**non_stream_kwargs)
                    parsed = self._parse_response(response)
                    self._log_response_summary(parsed)
                    return parsed

                stream_kwargs = self._prepare_stream_kwargs(kwargs)
                return await self._stream_chat(stream_kwargs)
            except Exception as fallback_e:
                err = self._format_exception(fallback_e)
                logger.warning(f"LLM Response: mode=error, error={err}")
                return LLMResponse(
                    content=f"Error calling LLM: {err}",
                    finish_reason="error",
                )

    async def _stream_chat(self, kwargs: dict[str, Any]) -> LLMResponse:
        """Stream 调用并拼装完整响应"""
        kwargs["stream"] = True

        content_parts: list[str] = []
        tool_calls_map: dict[int, dict] = {}  # index -> {id, name, arguments}
        finish_reason = "stop"
        usage: dict[str, Any] = {}
        reasoning_parts: list[str] = []

        async for chunk in await acompletion(**kwargs):
            choice = chunk.choices[0] if chunk.choices else None
            if not choice:
                continue

            delta = choice.delta

            # 收集 content
            if delta.content:
                content_parts.append(delta.content)

            # 收集 reasoning_content（如果有）
            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                reasoning_parts.append(delta.reasoning_content)

            # 收集 tool_calls（分片合并）
            if hasattr(delta, "tool_calls") and delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_map:
                        tool_calls_map[idx] = {
                            "id": tc.id or "",
                            "name": tc.function.name if tc.function else "",
                            "arguments": "",
                        }
                    if tc.id:
                        tool_calls_map[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_calls_map[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_calls_map[idx]["arguments"] += tc.function.arguments

            # 获取 finish_reason
            if choice.finish_reason:
                finish_reason = choice.finish_reason

            # 获取 usage（通常在最后一个 chunk）
            if hasattr(chunk, "usage") and chunk.usage:
                usage = self._extract_usage(chunk.usage)

        # 构建 tool_calls 列表
        tool_calls = []
        for idx in sorted(tool_calls_map.keys()):
            tc_data = tool_calls_map[idx]
            args = tc_data["arguments"]
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"raw": args}
            tool_calls.append(
                ToolCallRequest(
                    id=tc_data["id"],
                    name=tc_data["name"],
                    arguments=args,
                )
            )

        content = "".join(content_parts) if content_parts else None
        reasoning_content = "".join(reasoning_parts) if reasoning_parts else None

        # Stream some proxy/model variants emit textual pseudo tool calls:
        #   [tool_call] message({...})
        # Coerce them into structured tool calls (stream-only fallback).
        if not tool_calls:
            content, parsed_tool_calls = self._coerce_stream_text_tool_calls(content)
            if parsed_tool_calls:
                tool_calls = parsed_tool_calls
                logger.warning(
                    "Stream text tool_call marker detected; coerced "
                    f"{len(parsed_tool_calls)} tool call(s)."
                )

        response = LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            reasoning_content=reasoning_content,
        )

        self._log_response_summary(response)
        return response

    def _prepare_stream_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Clone kwargs for stream calls."""
        return dict(kwargs)

    def _prepare_non_stream_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Clone kwargs for non-stream calls."""
        return dict(kwargs)

    def _coerce_stream_text_tool_calls(
        self, content: str | None
    ) -> tuple[str | None, list[ToolCallRequest]]:
        """Parse textual [tool_call] markers from stream text into ToolCallRequest."""
        if not content or "[tool_call]" not in content:
            return content, []

        token = "[tool_call]"
        decoder = json.JSONDecoder()
        calls: list[ToolCallRequest] = []
        spans: list[tuple[int, int]] = []
        pos = 0

        while True:
            start = content.find(token, pos)
            if start < 0:
                break

            idx = start + len(token)
            header = re.match(r"\s*([A-Za-z_]\w*)\s*\(", content[idx:])
            if not header:
                pos = start + len(token)
                continue

            name = header.group(1)
            idx += header.end()

            tail = content[idx:].lstrip()
            idx += len(content[idx:]) - len(tail)
            if not tail.startswith("{"):
                pos = start + len(token)
                continue

            try:
                args_obj, consumed = decoder.raw_decode(tail)
            except json.JSONDecodeError:
                pos = start + len(token)
                continue

            idx += consumed
            trailing = content[idx:].lstrip()
            idx += len(content[idx:]) - len(trailing)
            if idx >= len(content) or content[idx] != ")":
                pos = start + len(token)
                continue

            end = idx + 1
            spans.append((start, end))
            calls.append(
                ToolCallRequest(
                    id=f"text_toolcall_{uuid4().hex[:12]}",
                    name=name,
                    arguments=args_obj if isinstance(args_obj, dict) else {"raw": args_obj},
                )
            )
            pos = end

        if not calls:
            return content, []

        parts: list[str] = []
        cursor = 0
        for start, end in spans:
            parts.append(content[cursor:start])
            cursor = end
        parts.append(content[cursor:])

        cleaned = "".join(parts)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        return (cleaned or None), calls

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
                        try:
                            args = json_repair.loads(args)
                        except Exception:
                            args = {"raw": args}

                tool_calls.append(ToolCallRequest(
                    id=_short_tool_id(),
                    name=tc.function.name,
                    arguments=args,
                ))

        usage = self._extract_usage(response.usage if hasattr(response, "usage") else None)
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
