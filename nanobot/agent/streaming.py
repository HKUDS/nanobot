"""Streaming LLM call helper.

``StreamingLLMCaller`` wraps the provider's chat/stream_chat methods
and handles:

- Non-streaming fallback when no progress callback is given.
- Streaming with full-response progress delivery on completion.
- Trace logging of latency, token usage, and tool calls.

``strip_think`` is a utility for removing ``<think>…</think>`` blocks
that some reasoning models embed in their responses.

Extracted from ``AgentLoop`` per ADR-002 to keep the main loop focused
on orchestration.
"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.callbacks import ProgressCallback, StatusEvent, TextChunk
from nanobot.agent.tracing import bind_trace

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider, LLMResponse

# LAN-90: pre-compile static regexes to avoid recompilation on every call.
_THINK_RE = re.compile(r"<think>[\s\S]*?</think>")
_ANALYSIS_PREFIX_RE = re.compile(r"^(assistant\s*)?analysis[^\n]*\n?", re.IGNORECASE)


def strip_think(text: str | None) -> str | None:
    """Remove ``<think>…</think>`` blocks that some models embed in content."""
    if not text:
        return None
    clean = _THINK_RE.sub("", text).strip()
    if not clean:
        logger.warning(
            "strip_think removed all content from non-empty response (first 100 chars): {}",
            text[:100],
        )
        return None
    # Strip common reasoning prefixes that sometimes leak into final answers.
    while True:
        stripped = _ANALYSIS_PREFIX_RE.sub("", clean).lstrip()
        if stripped == clean:
            break
        clean = stripped
    return clean or None


class StreamingLLMCaller:
    """Handles LLM calls with optional streaming and progress flushing."""

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
        on_progress: ProgressCallback | None,
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

        full_content = "".join(content_parts) or None
        full_reasoning = "".join(reasoning_parts) or None
        full_clean = strip_think(full_content) if full_content else None

        # LAN-5: some providers omit completion_tokens from streaming chunks.
        # Fall back to a character-based estimate (≈ 1 token per 4 chars) so
        # Langfuse spans record a non-zero output count instead of 0.
        if not usage.get("completion_tokens") and full_content:
            usage = dict(usage)  # don't mutate the chunk's dict
            usage["completion_tokens"] = max(1, len(full_content) // 4)

        if tool_calls:
            # Intermediate LLM call — text is thinking/planning, not the final
            # response.  Route as a status event so it appears in the header
            # indicator rather than polluting the message body.
            if full_clean:
                label = full_clean.split("\n")[0][:80].strip()
                await on_progress(StatusEvent(status_code="thinking", label=label or "Thinking…"))
        else:
            # Final response — emit full text so the channel can display it.
            if full_clean:
                await on_progress(TextChunk(content=full_clean, streaming=True))

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
