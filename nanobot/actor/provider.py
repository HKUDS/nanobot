"""ProviderActor: Pulsing actor wrapping an LLM provider.

Spawned once as ``name="provider"`` and resolved by any actor that
needs LLM access -- no more passing provider objects across actor boundaries.

Usage from any actor::

    from nanobot.actor.provider import ProviderActor
    provider = await ProviderActor.resolve("provider")
    response = await provider.chat(messages=..., tools=..., model=...)
"""

from collections.abc import AsyncIterator
from typing import Any

import pulsing as pul

from nanobot.providers.base import LLMProvider, LLMResponse, StreamChunk


@pul.remote
class ProviderActor:
    """
    Shared LLM provider actor.

    Wraps a concrete ``LLMProvider`` and exposes ``chat()``,
    ``chat_stream()``, and ``get_default_model()`` as remote methods.
    """

    def __init__(self, provider: LLMProvider):
        self._provider = provider

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Proxy to the underlying provider's chat()."""
        return await self._provider.chat(
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> AsyncIterator[StreamChunk]:
        """Proxy to the underlying provider's chat_stream()."""
        async for chunk in self._provider.chat_stream(
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        ):
            yield chunk

    def get_default_model(self) -> str:
        """Return the provider's default model name."""
        return self._provider.get_default_model()
