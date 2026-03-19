"""Shared lightweight agent loop for background execution contexts.

``run_tool_loop`` is the reusable think→act→observe engine used by both
``MissionManager`` and ``DelegationDispatcher``.  It was extracted from
``subagent.py`` to decouple it from the deprecated ``SubagentManager``.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from nanobot.agent.observability import tool_span
from nanobot.agent.tools.base import ToolResult
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.providers.base import LLMProvider


async def run_tool_loop(
    *,
    provider: LLMProvider,
    tools: ToolRegistry,
    messages: list[dict[str, Any]],
    model: str,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    max_iterations: int = 15,
) -> tuple[str | None, list[str], list[dict[str, Any]]]:
    """A reusable think→act→observe loop shared between the main agent and subagents.

    Returns ``(final_content, tools_used, messages)``.
    """
    iteration = 0
    final_result: str | None = None
    tools_used: list[str] = []
    # P-20: compute tool definitions once before the loop — they are static
    # within a run_tool_loop invocation.
    tool_definitions = tools.get_definitions()

    while iteration < max_iterations:
        iteration += 1

        response = await provider.chat(
            messages=messages,
            tools=tool_definitions,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        if response.has_tool_calls:
            # Add assistant message with tool calls
            tool_call_dicts = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in response.tool_calls
            ]
            messages.append(
                {
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": tool_call_dicts,
                }
            )

            # Execute tools
            for tool_call in response.tool_calls:
                tools_used.append(tool_call.name)
                args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                logger.debug("Executing: {} with arguments: {}", tool_call.name, args_str[:200])
                async with tool_span(
                    name=tool_call.name,
                    input=tool_call.arguments,
                ) as obs:
                    result = await tools.execute(tool_call.name, tool_call.arguments)
                    result_str = (
                        result.to_llm_string() if isinstance(result, ToolResult) else str(result)
                    )
                    if obs is not None:
                        obs.update(output=result_str[:500])
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.name,
                        "content": result_str,
                    }
                )
        else:
            final_result = response.content
            break

    if final_result is None:
        # Iteration budget exhausted — ask the model for a final summary without tools
        messages.append(
            {
                "role": "system",
                "content": (
                    "You have used all available tool iterations. "
                    "Based on everything above, produce a concise final answer now."
                ),
            }
        )
        try:
            summary_resp = await provider.chat(
                messages=messages,
                tools=None,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            final_result = summary_resp.content
        except Exception:  # crash-barrier: LLM provider errors
            pass

    if not final_result:
        # Last resort: collect recent tool results as the answer
        tool_snippets = []
        for m in reversed(messages):
            if m.get("role") == "tool" and isinstance(m.get("content"), str):
                tool_snippets.append(m["content"][:500])
                if len(tool_snippets) >= 3:
                    break
        if tool_snippets:
            tool_snippets.reverse()
            final_result = "\n\n".join(tool_snippets)
        else:
            final_result = "Task completed but no final response was generated."

    return final_result, tools_used, messages
