"""Shared tool loop: the LLM ↔ tool execution cycle used by all agents.

Both AgentActor and SubagentActor call ``run_tool_loop()`` instead of
duplicating the same iteration logic. Supports native tool_calls and
DSML-style function_calls in content (e.g. <|DSML|invoke name="...">).
"""

import json
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import ToolContext
from nanobot.agent.tools.registry import ToolRegistry


def _content_str(raw: Any) -> str:
    """Normalize LLM content to a single string (handles list of content parts)."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        parts = []
        for block in raw:
            if isinstance(block, dict):
                parts.append(block.get("text", block.get("content", "")) or "")
            elif hasattr(block, "text"):
                parts.append(getattr(block, "text", "") or "")
            else:
                parts.append(str(block))
        return "\n".join(p for p in parts if p)
    return str(raw)


def _parse_dsml_calls(content: str) -> list[tuple[str, str, dict]] | None:
    """If content contains DSML function_calls, return [(id, name, arguments), ...]; else None.
    Handles <|DSML|invoke name="..."> and <|DSML|parameter name="..." ...>value</|DSML|parameter>.
    """
    content = _content_str(content)
    if not content or "invoke" not in content or "DSML" not in content:
        return None
    # Match pipe or fullwidth pipe
    pipe = r"[\|\uFF5C]"
    invoke_re = re.compile(
        rf"<{pipe}DSML{pipe}\s*invoke\s+name=[\"']([^\"']+)[\"']\s*>",
        re.IGNORECASE,
    )
    param_re = re.compile(
        rf"<{pipe}DSML{pipe}\s*parameter\s+name=[\"']([^\"']+)[\"'][^>]*>([^<]*)</{pipe}DSML{pipe}\s*parameter\s*>",
        re.IGNORECASE,
    )
    calls = []
    for m in invoke_re.finditer(content):
        name = m.group(1).strip()
        start = m.end()
        # Find next invoke or end of content to bound parameter search
        next_invoke = invoke_re.search(content, start)
        end = next_invoke.start() if next_invoke else len(content)
        block = content[start:end]
        args = {}
        for pm in param_re.finditer(block):
            args[pm.group(1).strip()] = pm.group(2).strip()
        call_id = f"dsml_{uuid.uuid4().hex[:8]}"
        calls.append((call_id, name, args))
    return calls if calls else None


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
    """Run the tool loop, return the final text (consumes stream internally)."""
    parts = []
    async for chunk in run_tool_loop_stream(
        provider, tools, messages, ctx, model=model, max_iterations=max_iterations
    ):
        if chunk.kind == "token":
            parts.append(chunk.text)
        elif chunk.kind == "done":
            break
    return "".join(parts) or "I've completed processing but have no response to give."


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

        tool_calls = list(response.tool_calls) if response.has_tool_calls else []
        content = _content_str(response.content)

        if not tool_calls:
            dsml = _parse_dsml_calls(content)
            if dsml:
                tool_calls = [
                    SimpleNamespace(id=i, name=n, arguments=a) for i, n, a in dsml
                ]
            else:
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
            for tc in tool_calls
        ]

        messages.append(
            {
                "role": "assistant",
                "content": content,
                "tool_calls": tc_dicts,
            }
        )

        for tc in tool_calls:
            logger.info(
                f"Tool call: {tc.name}({json.dumps(tc.arguments, ensure_ascii=False)[:200]})"
            )
            yield AgentChunk(kind="tool_call", tool_name=tc.name)

            try:
                result = await tools.execute(tc.name, tc.arguments, ctx)
            except Exception as e:
                result = f"Error: {e}"
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": result,
                }
            )

            yield AgentChunk(kind="tool_result", text=result[:200], tool_name=tc.name)

    yield AgentChunk(
        kind="token", text="I've completed processing but have no response to give."
    )
    yield AgentChunk(kind="done")
