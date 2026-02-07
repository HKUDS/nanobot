"""Spawn tool for creating background subagents."""

import asyncio
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool, ToolContext


class SpawnTool(Tool):
    """
    Tool to spawn a SubagentActor for background task execution.

    Accepts ``Config`` — forwards it to SubagentActor so it can extract
    what it needs without the caller unpacking every field.
    """

    def __init__(self, config: Any, provider_name: str = "provider"):
        self._config = config
        self._provider_name = provider_name

    @property
    def name(self) -> str:
        return "spawn"

    @property
    def description(self) -> str:
        return (
            "Spawn a subagent to handle a task in the background. "
            "Use this for complex or time-consuming tasks that can run independently. "
            "The subagent will complete the task and report back when done."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task for the subagent to complete",
                },
                "label": {
                    "type": "string",
                    "description": "Optional short label for the task (for display)",
                },
            },
            "required": ["task"],
        }

    async def execute(self, ctx: ToolContext, task: str, label: str | None = None, **kwargs: Any) -> str:
        """Spawn a SubagentActor to execute the given task."""
        from nanobot.actor.subagent import SubagentActor

        display_label = label or task[:30] + ("..." if len(task) > 30 else "")

        try:
            subagent = await SubagentActor.spawn(
                config=self._config,
                task=task,
                label=display_label,
                origin_channel=ctx.channel or "cli",
                origin_chat_id=ctx.chat_id or "direct",
                agent_name=ctx.agent_name,
                provider_name=self._provider_name,
            )

            # Fire-and-forget: schedule run() in the background
            asyncio.create_task(subagent.run())

            logger.info(f"Spawned SubagentActor: {display_label}")
            return f"Subagent [{display_label}] started. I'll notify you when it completes."

        except Exception as e:
            logger.error(f"Failed to spawn subagent: {e}")
            return f"Error spawning subagent: {str(e)}"
