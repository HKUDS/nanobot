"""SubagentActor: Pulsing actor for background task execution."""

import uuid
from typing import Any

import pulsing as pul
from loguru import logger

from nanobot.actor.tool_loop import run_tool_loop
from nanobot.agent.tools.base import ToolContext
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool, ListDirTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebSearchTool, WebFetchTool


@pul.remote
class SubagentActor:
    """
    A lightweight background agent for a specific task.

    Accepts ``Config`` — extracts what it needs internally.
    Resolves ProviderActor and AgentActor via Pulsing name resolution.
    """

    def __init__(
        self,
        config: Any,
        task: str,
        label: str,
        origin_channel: str,
        origin_chat_id: str,
        agent_name: str = "agent",
        provider_name: str = "provider",
    ):
        self.workspace = config.workspace_path
        self.task = task
        self.label = label
        self.origin_channel = origin_channel
        self.origin_chat_id = origin_chat_id
        self.agent_name = agent_name
        self.provider_name = provider_name

        self.model = config.agents.defaults.model
        self.brave_api_key = config.tools.web.search.api_key or None
        self.exec_config = config.tools.exec
        self.restrict_to_workspace = config.tools.restrict_to_workspace

        self.task_id = str(uuid.uuid4())[:8]
        self.tools = self._build_tools()

    def _build_tools(self) -> ToolRegistry:
        tools = ToolRegistry()
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        tools.register(ReadFileTool(allowed_dir=allowed_dir))
        tools.register(WriteFileTool(allowed_dir=allowed_dir))
        tools.register(ListDirTool(allowed_dir=allowed_dir))
        tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            restrict_to_workspace=self.restrict_to_workspace,
        ))
        tools.register(WebSearchTool(api_key=self.brave_api_key))
        tools.register(WebFetchTool())
        return tools

    async def run(self) -> str:
        """Execute the task and announce the result."""
        logger.info(f"SubagentActor [{self.task_id}] starting: {self.label}")

        try:
            from nanobot.actor.provider import ProviderActor
            provider = await ProviderActor.resolve(self.provider_name)
            model = self.model or provider.get_default_model()

            messages: list[dict[str, Any]] = [
                {"role": "system", "content": self._build_prompt()},
                {"role": "user", "content": self.task},
            ]

            result = await run_tool_loop(
                provider=provider,
                tools=self.tools,
                messages=messages,
                ctx=ToolContext(),
                model=model,
                max_iterations=15,
            )

            logger.info(f"SubagentActor [{self.task_id}] completed")
            await self._announce(result, "ok")
            return result

        except Exception as e:
            error_msg = f"Error: {str(e)}"
            logger.error(f"SubagentActor [{self.task_id}] failed: {e}")
            await self._announce(error_msg, "error")
            return error_msg

    async def _announce(self, result: str, status: str) -> None:
        status_text = "completed successfully" if status == "ok" else "failed"
        content = (
            f"[Subagent '{self.label}' {status_text}]\n\n"
            f"Task: {self.task}\n\nResult:\n{result}\n\n"
            "Summarize this naturally for the user. Keep it brief."
        )

        try:
            from nanobot.actor.agent import AgentActor
            agent = await AgentActor.resolve(self.agent_name)
            await agent.announce(
                origin_channel=self.origin_channel,
                origin_chat_id=self.origin_chat_id,
                content=content,
            )
        except Exception as e:
            logger.error(f"SubagentActor [{self.task_id}] failed to announce: {e}")

    def _build_prompt(self) -> str:
        return f"""# Subagent

You are a subagent spawned to complete a specific task.

## Your Task
{self.task}

## Rules
1. Stay focused - complete only the assigned task
2. Your final response will be reported back to the main agent
3. Be concise but informative

## Workspace: {self.workspace}

When done, provide a clear summary of your findings or actions."""
