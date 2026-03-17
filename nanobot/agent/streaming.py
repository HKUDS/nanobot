"""Streaming LLM call helper.

``StreamingLLMCaller`` wraps the provider's chat/stream_chat methods
and handles:

- Non-streaming fallback when no progress callback is given.
- Periodic flushing of partial content for progressive display.
- Trace logging of latency, token usage, and tool calls.

``strip_think`` is a utility for removing ``<think>…</think>`` blocks
that some reasoning models embed in their responses.

Extracted from ``AgentLoop`` per ADR-002 to keep the main loop focused
on orchestration.
"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from nanobot.agent.tracing import bind_trace

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider, LLMResponse


def strip_think(text: str | None) -> str | None:
    """Remove ``<think>…</think>`` blocks that some models embed in content."""
    if not text:
        return None
    clean = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
    if not clean:
        logger.warning(
            "strip_think removed all content from non-empty response (first 100 chars): {}",
            text[:100],
        )
        return None
    # Strip common reasoning prefixes that sometimes leak into final answers.
    while True:
        stripped = re.sub(
            r"^(assistant\s*)?analysis[^\n]*\n?", "", clean, flags=re.IGNORECASE
        ).lstrip()
        if stripped == clean:
            break
        clean = stripped
    return clean or None


class StreamingLLMCaller:
    """Handles LLM calls with optional streaming and progress flushing."""

    STREAM_FLUSH_INTERVAL = 12  # flush partial content every N chunks

    def __init__(
        self,
        *,
        provider: LLMProvider,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> None:
        self.provider = provider
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    async def call(
        self,
        messages: list[dict],
        tools: list[dict[str, Any]] | None,
        on_progress: Callable[..., Awaitable[None]] | None,
    ) -> LLMResponse:
        """Call the LLM, streaming when *on_progress* is available.

        When streaming, partial content is periodically forwarded to
        *on_progress* so that channels supporting message editing can
        show tokens incrementally.  The final ``LLMResponse`` is
        assembled from the accumulated chunks.
        """
        t0 = time.monotonic()
        # Fall back to non-streaming when there's no progress callback
        if on_progress is None:
            resp = await self.provider.chat(
                messages=messages,
                tools=tools,
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                metadata={"generation_name": "chat_completion"},
            )
            latency_ms = (time.monotonic() - t0) * 1000
            bind_trace().debug(
                "LLM call model={} latency_ms={:.0f} input_tokens={} output_tokens={} "
                "tool_calls={}",
                self.model,
                latency_ms,
                resp.usage.get("prompt_tokens", 0),
                resp.usage.get("completion_tokens", 0),
                len(resp.tool_calls),
            )
            return resp

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: list = []
        finish_reason = "stop"
        usage: dict[str, int] = {}
        chunk_count = 0
        last_flushed = 0

        async for chunk in self.provider.stream_chat(
            messages=messages,
            tools=tools,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            metadata={"generation_name": "chat_completion"},
        ):
            if chunk.content_delta:
                content_parts.append(chunk.content_delta)
            if chunk.reasoning_delta:
                reasoning_parts.append(chunk.reasoning_delta)
            if chunk.finish_reason:
                finish_reason = chunk.finish_reason
            if chunk.usage:
                usage = chunk.usage
            if chunk.tool_calls:
                tool_calls = chunk.tool_calls

            chunk_count += 1

            # Periodically flush accumulated content to the channel
            chars_since = sum(len(p) for p in content_parts[last_flushed:])
            if (
                chars_since >= 80
                and chunk_count % self.STREAM_FLUSH_INTERVAL == 0
                and not chunk.done
            ):
                partial = "".join(content_parts)
                clean = strip_think(partial)
                if clean:
                    await on_progress(clean, streaming=True)
                last_flushed = len(content_parts)

        full_content = "".join(content_parts) or None
        full_reasoning = "".join(reasoning_parts) or None

        # Final flush: ensure the channel has the complete text before
        # post-processing (e.g. self-check/verifier) might alter it.
        if full_content:
            clean = strip_think(full_content)
            if clean:
                await on_progress(clean, streaming=True)

        from nanobot.providers.base import LLMResponse

        latency_ms = (time.monotonic() - t0) * 1000
        bind_trace().debug(
            "LLM stream model={} latency_ms={:.0f} input_tokens={} output_tokens={} "
            "tool_calls={} chunks={}",
            self.model,
            latency_ms,
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
            len(tool_calls),
            chunk_count,
        )

        return LLMResponse(
            content=full_content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            reasoning_content=full_reasoning,
        )
