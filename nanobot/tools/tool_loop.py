"""Shared lightweight agent loop for background execution contexts.

``run_tool_loop`` is the reusable think→act→observe engine used by both
``MissionManager``.  It was extracted from ``subagent.py`` to decouple it
from the deprecated ``SubagentManager``.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from nanobot.observability.langfuse import tool_span
from nanobot.providers.base import LLMProvider
from nanobot.tools.base import ToolResult
from nanobot.tools.executor import ToolExecutor
from nanobot.tools.registry import ToolRegistry

# Compress the message list when it exceeds this threshold to prevent unbounded growth.
# Keeps system-role messages + the most recent exchanges.
_MAX_MESSAGES_BEFORE_COMPRESS = 40
_MESSAGES_TO_KEEP_AFTER_COMPRESS = 20


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
    executor = ToolExecutor(tools)

    while iteration < max_iterations:
        iteration += 1

        # Compress context if the message list has grown too large to prevent token
        # budget exhaustion. Preserve system-role messages and keep recent exchanges.
        if len(messages) > _MAX_MESSAGES_BEFORE_COMPRESS:
            original_count = len(messages)
            system_msgs = [m for m in messages if m.get("role") == "system"]
            recent_msgs = messages[-_MESSAGES_TO_KEEP_AFTER_COMPRESS:]
            recent_ids = {id(m) for m in recent_msgs}
            prefix = [m for m in system_msgs if id(m) not in recent_ids]
            messages = prefix + recent_msgs
            logger.debug(
                "run_tool_loop: compressed context {} → {} messages",
                original_count,
                len(messages),
            )

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

            # Execute tools — readonly tools run in parallel, writes sequentially.
            tool_results = await executor.execute_batch(response.tool_calls)
            for tool_call, result in zip(response.tool_calls, tool_results):
                args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                logger.debug("Executed: {} with arguments: {}", tool_call.name, args_str[:200])
                tools_used.append(tool_call.name)
                result_str = (
                    result.to_llm_string() if isinstance(result, ToolResult) else str(result)
                )
                # Record a per-tool observability span with the execution result.
                async with tool_span(
                    name=tool_call.name,
                    input=tool_call.arguments,
                ) as obs:
                    if obs is not None:
                        obs.update(output=result_str[:500])
                # Wrap in XML tags to create a structural boundary between untrusted
                # tool output and agent instructions (prompt-injection mitigation, LAN-43).
                # Avoid double-wrapping if the content is already tagged.
                if result_str.startswith("<tool_result>"):
                    wrapped_result = result_str
                else:
                    wrapped_result = f"<tool_result>\n{result_str}\n</tool_result>"
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.name,
                        "content": wrapped_result,
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
        except Exception as exc:  # crash-barrier: LLM provider errors
            logger.debug("Summary LLM call failed: {}", exc)

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
