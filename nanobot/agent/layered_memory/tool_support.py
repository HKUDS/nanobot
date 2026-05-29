"""Helpers shared by memory_search and conversation_search tools."""

from __future__ import annotations

from typing import Any

from nanobot.agent.layered_memory.search_budget import try_consume_memory_search_call
from nanobot.agent.tools.context import RequestContext
from nanobot.config.schema import LayeredMemoryConfig


def capture_tools_enabled(ctx: Any) -> bool:
    layered = getattr(ctx, "layered_memory", None)
    if layered is None:
        return False
    return layered.capture_enabled()


def session_key_from_request(ctx: RequestContext | None) -> str | None:
    if ctx is None:
        return None
    if ctx.session_key:
        return ctx.session_key
    if ctx.channel and ctx.chat_id:
        return f"{ctx.channel}:{ctx.chat_id}"
    return None


def consume_search_budget(layered: LayeredMemoryConfig) -> str | None:
    """Return an error message when the per-turn search budget is exhausted."""
    limit = layered.recall.max_search_calls_per_turn
    if try_consume_memory_search_call(limit=limit):
        return None
    return (
        f"Error: memory search limit reached ({limit} per turn). "
        "Use prior search results or ask the user."
    )
