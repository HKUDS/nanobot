"""Shared tool loop: the LLM ↔ tool execution cycle used by all agents.

Both AgentActor and SubagentActor call ``run_tool_loop()`` instead of
duplicating the same iteration logic.
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import ToolContext
from nanobot.agent.tools.registry import ToolRegistry


@dataclass
class AgentChunk:
    """A chunk yielded from the streaming agent process."""

    kind: str  # "token", "tool_call", "tool_result", "done"
    text: str = ""
    tool_name: str | None = None


async def run_tool_loop(
    provider: Any,
    tools: ToolRegistry,
    messages: list[dict[str, Any]],
    ctx: ToolContext,
    model: str | None = None,
    max_iterations: int = 20,
) -> str:
    """Run the LLM ↔ tool execution loop, return the final text response.

    Messages list is mutated in place.  No callbacks needed — the actor
    communication pattern (ask/tell) already covers sync vs async semantics.
    """
    for _ in range(max_iterations):
        response = await provider.chat(
            messages=messages,
            tools=tools.get_definitions(),
            model=model,
        )

        if not response.has_tool_calls:
            return response.content or "I've completed processing but have no response to give."

        tc_dicts = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
            }
            for tc in response.tool_calls
        ]

        messages.append({
            "role": "assistant",
            "content": response.content or "",
            "tool_calls": tc_dicts,
        })

        for tc in response.tool_calls:
            logger.info(f"Tool call: {tc.name}({json.dumps(tc.arguments, ensure_ascii=False)[:200]})")
            result = await tools.execute(tc.name, tc.arguments, ctx)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": tc.name,
                "content": result,
            })

    return "I've completed processing but have no response to give."


async def run_tool_loop_stream(
    provider: Any,
    tools: ToolRegistry,
    messages: list[dict[str, Any]],
    ctx: ToolContext,
    model: str | None = None,
    max_iterations: int = 20,
) -> AsyncIterator[AgentChunk]:
    """Run the LLM tool loop with streaming for the final text response.

    Tool-calling iterations use non-streaming chat(); only the final text
    response (after all tool calls) streams token-by-token.
    """
    had_tool_calls = False

    for iteration in range(max_iterations):
        # After tool calls, try streaming for the final text response
        if had_tool_calls and iteration > 0:
            streamed = False
            async for chunk in provider.chat_stream(messages=messages, model=model):
                if chunk.delta:
                    streamed = True
                    yield AgentChunk(kind="token", text=chunk.delta)
            if streamed:
                yield AgentChunk(kind="done")
                return

        response = await provider.chat(
            messages=messages,
            tools=tools.get_definitions(),
            model=model,
        )

        if not response.has_tool_calls:
            content = response.content or ""
            if content:
                yield AgentChunk(kind="token", text=content)
            yield AgentChunk(kind="done")
            return

        had_tool_calls = True
        tc_dicts = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
            }
            for tc in response.tool_calls
        ]

        messages.append({
            "role": "assistant",
            "content": response.content or "",
            "tool_calls": tc_dicts,
        })

        for tc in response.tool_calls:
            logger.info(f"Tool call: {tc.name}({json.dumps(tc.arguments, ensure_ascii=False)[:200]})")
            yield AgentChunk(kind="tool_call", tool_name=tc.name)

            result = await tools.execute(tc.name, tc.arguments, ctx)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": tc.name,
                "content": result,
            })

            yield AgentChunk(kind="tool_result", text=result[:200], tool_name=tc.name)

    yield AgentChunk(kind="token", text="I've completed processing but have no response to give.")
    yield AgentChunk(kind="done")
