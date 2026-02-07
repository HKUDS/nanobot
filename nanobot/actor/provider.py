"""ProviderActor: Pulsing actor for LLM access via litellm.

Single layer: ``@pul.remote`` → ``litellm.acompletion()``.
Passes ``api_key`` directly to litellm — no env var setup needed.

Usage::

    provider = await ProviderActor.resolve("provider")
    response = await provider.chat(messages=..., tools=..., model=...)
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import litellm
import pulsing as pul
from litellm import acompletion

from nanobot.errors import ProviderCallError

# ── Data types ──────────────────────────────────────────────────────


@dataclass
class ToolCallRequest:
    """A tool call request from the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """Response from an LLM provider."""

    content: str | None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


@dataclass
class StreamChunk:
    """A single chunk from a streaming LLM response."""

    delta: str
    finish_reason: str | None = None


# ── Gateway detection (data-driven) ────────────────────────────────

# Known provider domains — these are NOT gateways even though they
# appear as api_base.  litellm handles them natively.
_KNOWN_PROVIDERS = [
    "deepseek",
    "anthropic",
    "openai.com",
    "googleapis",
    "bigmodel.cn",
    "groq",
    "moonshot",
    "dashscope",
    "together",
]


def _detect_gateway(api_base: str | None) -> str | None:
    """Return the litellm routing prefix for known gateways, or None."""
    if not api_base:
        return None
    base = api_base.lower()
    if "openrouter" in base:
        return "openrouter/"
    if "aihubmix" in base:
        return "openai/"
    # Known provider endpoint — not a gateway
    if any(d in base for d in _KNOWN_PROVIDERS):
        return None
    # Unknown custom endpoint → assume vLLM / OpenAI-compatible
    return "hosted_vllm/"


# ── Actor ───────────────────────────────────────────────────────────


@pul.remote
class ProviderActor:
    """Shared LLM provider actor.

    Accepts ``Config``; passes ``api_key`` directly to litellm
    (no env-var gymnastics).  Only adds a routing prefix when
    ``api_base`` points to a known gateway (openrouter / aihubmix / vllm).
    """

    def __init__(self, config: Any):
        p = config.get_provider()
        self.default_model = config.agents.defaults.model
        self._api_key = p.api_key if p else None
        self._api_base = config.get_api_base()
        self._extra_headers = (p.extra_headers if p else None) or {}
        self._gateway = _detect_gateway(self._api_base)
        litellm.suppress_debug_info = True

    def _resolve_model(self, model: str | None) -> str:
        """Add gateway prefix when needed."""
        model = model or self.default_model
        if self._gateway and not model.startswith(self._gateway):
            if self._gateway == "openai/":
                model = model.split("/")[-1]  # aihubmix: strip existing prefix
            model = f"{self._gateway}{model}"
        return model

    def _kwargs(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        """Build kwargs for litellm.acompletion()."""
        kw: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if self._api_key:
            kw["api_key"] = self._api_key
        if self._api_base:
            kw["api_base"] = self._api_base
        if self._extra_headers:
            kw["extra_headers"] = self._extra_headers
        return kw

    # ── Public API ──────────────────────────────────────────────

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Send a chat completion request."""
        model = self._resolve_model(model)
        kw = self._kwargs(model, messages, max_tokens, temperature)
        if tools:
            kw["tools"] = tools
            kw["tool_choice"] = "auto"
        try:
            return self._parse(await acompletion(**kw))
        except Exception as e:
            raise ProviderCallError(str(e)) from e

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a chat completion response token by token."""
        model = self._resolve_model(model)
        kw = self._kwargs(model, messages, max_tokens, temperature)
        kw["stream"] = True
        try:
            async for chunk in await acompletion(**kw):
                delta = chunk.choices[0].delta
                text = getattr(delta, "content", None) or ""
                finish = chunk.choices[0].finish_reason
                if text or finish:
                    yield StreamChunk(delta=text, finish_reason=finish)
        except Exception as e:
            raise ProviderCallError(str(e)) from e

    def get_default_model(self) -> str:
        return self.default_model

    # ── Response parsing ────────────────────────────────────────

    def _parse(self, response: Any) -> LLMResponse:
        choice = response.choices[0]
        msg = choice.message

        tool_calls = []
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                args = tc.function.arguments
                if isinstance(args, str):
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
            content=msg.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage=usage,
        )
