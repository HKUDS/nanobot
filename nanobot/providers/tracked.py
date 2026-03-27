"""Wrapper around LLMProvider.chat that automatically reports token usage."""

import asyncio
from typing import Any

from nanobot.coordinator.client import report_usage
from nanobot.providers.base import LLMProvider, LLMResponse


async def tracked_chat(
    provider: LLMProvider,
    *,
    messages: list[dict[str, Any]],
    source: str = "agent_loop",
    model: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.7,
    reasoning_effort: str | None = None,
) -> LLMResponse:
    """Call provider.chat and fire-and-forget report usage to the coordinator."""
    response = await provider.chat(
        messages=messages,
        tools=tools,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
    )

    if response.usage:
        asyncio.create_task(report_usage(
            prompt_tokens=response.usage.get("prompt_tokens", 0),
            completion_tokens=response.usage.get("completion_tokens", 0),
            model=model or "",
            source=source,
        ))

    return response
