"""Multi-model provider with automatic fallback on failure."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from nanobot.providers.base import LLMProvider, LLMResponse


class MultiModelProvider(LLMProvider):
    """Provider that tries multiple models in order, falling back on failure.

    Each child provider is a fully instantiated ``LLMProvider`` paired with
    its model string. On ``chat()`` or ``chat_stream()``, requests are tried
    against models in priority order. Transient errors trigger fallback to
    the next model; non-transient errors and successes are returned immediately.

    Usage:
        provider = MultiModelProvider(children=[
            (openai_provider, "gpt-4o"),
            (anthropic_provider, "claude-3-opus"),
        ], default_model="gpt-4o")
    """

    def __init__(
        self,
        children: list[tuple[LLMProvider, str]],
        default_model: str,
    ):
        """
        Args:
            children: List of (provider, model_string) pairs in priority order.
            default_model: The primary model identifier (for ``get_default_model``).
        """
        super().__init__()
        self._children = children
        self._default_model = default_model
        self._active_model = default_model

    @property
    def active_model(self) -> str:
        """The model that last succeeded (or the default if none have been tried)."""
        return self._active_model

    def get_default_model(self) -> str:
        """Return the default (primary) model identifier."""
        return self._default_model

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Try each child provider in order until one succeeds."""
        last_response: LLMResponse | None = None
        last_error: Exception | None = None

        for idx, (child, child_model) in enumerate(self._children):
            try:
                response = await child.chat(
                    messages=messages,
                    tools=tools,
                    model=child_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    reasoning_effort=reasoning_effort,
                    tool_choice=tool_choice,
                )
            except Exception as exc:
                last_error = exc
                response = LLMResponse(
                    content=f"Error calling LLM ({child_model}): {exc}",
                    finish_reason="error",
                )

            if response.finish_reason != "error":
                self._active_model = child_model
                if idx > 0:
                    logger.info(
                        "Multi-model fallback succeeded: {} -> {} (attempt {})",
                        self._default_model,
                        child_model,
                        idx + 1,
                    )
                return response

            # Check if this is a transient error worth falling back from
            if not child._is_transient_response(response):
                # Non-transient error — don't waste time on other providers
                # that would likely fail the same way (auth, quota, etc.)
                return response

            last_response = response
            logger.warning(
                "Multi-model fallback: {} failed (transient), trying next model",
                child_model,
            )

        if last_response is not None:
            return last_response
        # Should not happen, but safety fallback
        return LLMResponse(
            content=f"All models failed. Last error: {last_error}",
            finish_reason="error",
        )

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        """Stream with fallback — tries each child in order until one succeeds."""
        last_response: LLMResponse | None = None
        last_error: Exception | None = None

        for idx, (child, child_model) in enumerate(self._children):
            try:
                response = await child.chat_stream(
                    messages=messages,
                    tools=tools,
                    model=child_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    reasoning_effort=reasoning_effort,
                    tool_choice=tool_choice,
                    on_content_delta=on_content_delta if idx == 0 else None,
                )
            except Exception as exc:
                last_error = exc
                response = LLMResponse(
                    content=f"Error calling LLM ({child_model}): {exc}",
                    finish_reason="error",
                )

            if response.finish_reason != "error":
                self._active_model = child_model
                if idx > 0:
                    logger.info(
                        "Multi-model fallback succeeded: {} -> {} (attempt {})",
                        self._default_model,
                        child_model,
                        idx + 1,
                    )
                return response

            if not child._is_transient_response(response):
                return response

            last_response = response
            logger.warning(
                "Multi-model fallback: {} failed (transient), trying next model",
                child_model,
            )

        if last_response is not None:
            return last_response
        return LLMResponse(
            content=f"All models failed. Last error: {last_error}",
            finish_reason="error",
        )
