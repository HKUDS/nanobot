"""ADK lifecycle callbacks for scorpion agent.

Callback signatures (from ADK type hints):
  before_agent_callback(ctx: CallbackContext) -> Content | None
  after_model_callback(ctx: CallbackContext, response: LlmResponse) -> LlmResponse | None
  before_tool_callback(tool: BaseTool, args: dict, ctx: ToolContext) -> dict | None
  after_tool_callback(tool: BaseTool, args: dict, ctx: ToolContext, result: dict) -> dict | None
"""

from __future__ import annotations

import re
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types
from loguru import logger


def _strip_think(text: str | None) -> str | None:
    """Remove <think>...</think> blocks that some models embed in content."""
    if not text:
        return None
    return re.sub(r"<think>[\s\S]*?</think>", "", text).strip() or None


def _extract_text(content: types.Content | None) -> str | None:
    """Extract concatenated text from a Content object's parts."""
    if not content or not content.parts:
        return None
    texts = [p.text for p in content.parts if p.text]
    return "\n".join(texts) if texts else None


def _tool_hint_str(name: str, args: dict) -> str:
    """Format a tool call as a concise hint string."""
    val = next(iter(args.values()), None) if args else None
    if isinstance(val, str):
        return f'{name}("{val[:40]}...")' if len(val) > 40 else f'{name}("{val}")'
    return name


# ── Callback factories ───────────────────────────────────────────────────────
# These return closures that capture the progress callback.


def make_before_agent_callback():
    """before_agent_callback: runs before the agent starts each invocation."""

    async def before_agent(*, callback_context: CallbackContext, **kwargs) -> types.Content | None:
        # Initialize per-turn state
        callback_context.state["temp:sent_in_turn"] = "false"
        iteration = int(callback_context.state.get("temp:iteration_count", "0"))
        callback_context.state["temp:iteration_count"] = str(iteration)
        return None

    return before_agent


def make_after_model_callback(on_progress=None):
    """after_model_callback: runs after each LLM response.

    Streams intermediate text and enforces max iterations.
    """

    async def after_model(*, callback_context: CallbackContext, llm_response: LlmResponse, **kwargs) -> LlmResponse | None:
        # Increment iteration count
        iteration = int(callback_context.state.get("temp:iteration_count", "0")) + 1
        callback_context.state["temp:iteration_count"] = str(iteration)

        max_iter = int(callback_context.state.get("app:max_iterations", "40"))
        if iteration > max_iter:
            logger.warning("Max iterations ({}) reached", max_iter)
            stop_text = (
                f"I reached the maximum number of tool call iterations ({max_iter}) "
                "without completing the task. You can try breaking the task into smaller steps."
            )
            return LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part(text=stop_text)],
                ),
                turn_complete=True,
            )

        # Stream intermediate text as progress
        if on_progress and llm_response.content:
            text = _extract_text(llm_response.content)
            clean = _strip_think(text)

            # Check if model is requesting tool calls (function_call parts)
            has_tool_calls = any(
                p.function_call for p in (llm_response.content.parts or [])
                if p.function_call
            )

            if has_tool_calls and clean:
                await on_progress(clean)

        return None

    return after_model


def make_before_tool_callback(on_progress=None):
    """before_tool_callback: emit tool hints before tool execution."""

    async def before_tool(
        tool: BaseTool, args: dict[str, Any], tool_context: ToolContext, **kwargs
    ) -> dict | None:
        tool_name = getattr(tool, "name", str(tool))
        logger.info("Tool call: {}({})", tool_name, str(args)[:200])

        if on_progress:
            hint = _tool_hint_str(tool_name, args)
            await on_progress(hint, tool_hint=True)

        return None

    return before_tool


# Module-level set for reliable tool tracking (ADK state can be flaky)
_turn_tools_used: set[str] = set()


def clear_turn_tools() -> None:
    """Clear the per-turn tool tracker. Called before each agent run."""
    _turn_tools_used.clear()


def get_turn_tools() -> list[str]:
    """Get the list of tools used this turn."""
    return list(_turn_tools_used)


def make_after_tool_callback():
    """after_tool_callback: track tools used."""

    async def after_tool(
        tool: BaseTool, args: dict[str, Any], tool_context: ToolContext, tool_response: dict, **kwargs
    ) -> dict | None:
        tool_name = getattr(tool, "name", str(tool))
        # Track in both ADK state and module-level set
        used = tool_context.state.get("temp:tools_used", "")
        if used:
            tool_context.state["temp:tools_used"] = f"{used},{tool_name}"
        else:
            tool_context.state["temp:tools_used"] = tool_name
        _turn_tools_used.add(tool_name)
        return None

    return after_tool
