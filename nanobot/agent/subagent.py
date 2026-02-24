"""Subagent manager for background task execution."""

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool, EditFileTool, ListDirTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebSearchTool, WebFetchTool


# Mapping of tool names to their classes and required init kwargs
_TOOL_BUILDERS: dict[str, type] = {
    "read_file": ReadFileTool,
    "write_file": WriteFileTool,
    "edit_file": EditFileTool,
    "list_dir": ListDirTool,
    "exec": ExecTool,
    "web_search": WebSearchTool,
    "web_fetch": WebFetchTool,
}


class SubagentManager:
    """
    Manages background subagent execution.

    Subagents are lightweight agent instances that run in the background
    to handle specific tasks. They share the same LLM provider but have
    isolated context and a focused system prompt.

    When subagent_profiles are configured, each profile can specify its own
    tools, skills, model, and iteration limits.
    """

    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        bus: MessageBus,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        brave_api_key: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        restrict_to_workspace: bool = False,
        profiles: dict | None = None,
        skills_loader: Any | None = None,
    ):
        from nanobot.config.schema import ExecToolConfig
        self.provider = provider
        self.workspace = workspace
        self.bus = bus
        self.model = model or provider.get_default_model()
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.restrict_to_workspace = restrict_to_workspace
        self._profiles = profiles or {}
        self._skills_loader = skills_loader
        self._running_tasks: dict[str, asyncio.Task[None]] = {}

    def get_profile_names(self) -> list[str]:
        """Return available profile names."""
        return list(self._profiles.keys())

    def get_profiles_description(self) -> str:
        """Return a formatted description of available profiles for the LLM."""
        if not self._profiles:
            return ""
        lines = []
        for name, profile in self._profiles.items():
            desc = profile.description or "No description"
            tools_info = ", ".join(profile.tools) if profile.tools else "all tools"
            lines.append(f"- {name}: {desc} (tools: {tools_info})")
        return "\n".join(lines)

    def _resolve_profile(self, profile_name: str | None) -> "SubagentProfile | None":
        """Resolve a profile by name, returning None for default behavior."""
        if not profile_name or not self._profiles:
            return None
        profile = self._profiles.get(profile_name)
        if profile is None:
            logger.warning("Unknown subagent profile '{}', falling back to default", profile_name)
        return profile

    async def spawn(
        self,
        task: str,
        label: str | None = None,
        profile: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
        session_key: str | None = None,
    ) -> str:
        """
        Spawn a subagent to execute a task in the background.

        Args:
            task: The task description for the subagent.
            label: Optional human-readable label for the task.
            profile: Optional profile name for specialized behavior.
            origin_channel: The channel to announce results to.
            origin_chat_id: The chat ID to announce results to.

        Returns:
            Status message indicating the subagent was started.
        """
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")
        resolved_profile = self._resolve_profile(profile)

        origin = {
            "channel": origin_channel,
            "chat_id": origin_chat_id,
        }

        bg_task = asyncio.create_task(
            self._run_subagent(task_id, task, display_label, origin, resolved_profile)
        )
        self._running_tasks[task_id] = bg_task
        bg_task.add_done_callback(lambda _: self._running_tasks.pop(task_id, None))

        profile_info = f" [profile: {profile}]" if profile else ""
        logger.info("Spawned subagent [{}]{}: {}", task_id, profile_info, display_label)
        return f"Subagent [{display_label}] started (id: {task_id}). I'll notify you when it completes."

    def _build_tools_for_profile(self, profile: "SubagentProfile | None") -> ToolRegistry:
        """Build a ToolRegistry based on the profile's tool allow/deny lists."""
        tools = ToolRegistry()
        allowed_dir = self.workspace if self.restrict_to_workspace else None

        # Determine which tool names to register
        if profile and profile.tools:
            # Explicit allow list
            tool_names = set(profile.tools)
        else:
            # All tools by default
            tool_names = set(_TOOL_BUILDERS.keys())

        # Apply deny list
        if profile and profile.disallowed_tools:
            tool_names -= set(profile.disallowed_tools)

        # Register tools
        for name in tool_names:
            if name not in _TOOL_BUILDERS:
                logger.warning("Unknown tool '{}' in subagent profile, skipping", name)
                continue
            cls = _TOOL_BUILDERS[name]
            if cls in (ReadFileTool, WriteFileTool, EditFileTool, ListDirTool):
                tools.register(cls(workspace=self.workspace, allowed_dir=allowed_dir))
            elif cls is ExecTool:
                tools.register(ExecTool(
                    working_dir=str(self.workspace),
                    timeout=self.exec_config.timeout,
                    restrict_to_workspace=self.restrict_to_workspace,
                ))
            elif cls is WebSearchTool:
                tools.register(WebSearchTool(api_key=self.brave_api_key))
            elif cls is WebFetchTool:
                tools.register(WebFetchTool())

        return tools

    def _load_skills_content(self, skill_names: list[str]) -> str:
        """Load skill content for injection into the subagent system prompt."""
        if not skill_names or not self._skills_loader:
            return ""
        parts = []
        for name in skill_names:
            content = self._skills_loader.load_skill(name)
            if content:
                parts.append(f"### Skill: {name}\n\n{content}")
            else:
                logger.warning("Skill '{}' not found for subagent profile", name)
        if not parts:
            return ""
        return "\n# Skills\n\n" + "\n\n---\n\n".join(parts)

    async def _run_subagent(
        self,
        task_id: str,
        task: str,
        label: str,
        origin: dict[str, str],
        profile: "SubagentProfile | None" = None,
    ) -> None:
        """Execute the subagent task and announce the result."""
        logger.info("Subagent [{}] starting task: {}", task_id, label)

        try:
            # Build tools based on profile
            tools = self._build_tools_for_profile(profile)

            # Resolve model/temperature/max_tokens from profile or defaults
            model = (profile.model if profile and profile.model else None) or self.model
            temperature = (profile.temperature if profile and profile.temperature is not None else None) or self.temperature
            max_tokens = (profile.max_tokens if profile and profile.max_tokens is not None else None) or self.max_tokens
            max_iterations = profile.max_iterations if profile else 15

            # Build system prompt with optional skills
            skills_content = ""
            if profile and profile.skills:
                skills_content = self._load_skills_content(profile.skills)
            system_prompt = self._build_subagent_prompt(task, profile, skills_content)

            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ]

            # Run agent loop
            iteration = 0
            final_result: str | None = None

            while iteration < max_iterations:
                iteration += 1

                response = await self.provider.chat(
                    messages=messages,
                    tools=tools.get_definitions(),
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                if response.has_tool_calls:
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
                    messages.append({
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": tool_call_dicts,
                    })

                    for tool_call in response.tool_calls:
                        args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                        logger.debug("Subagent [{}] executing: {} with arguments: {}", task_id, tool_call.name, args_str)
                        result = await tools.execute(tool_call.name, tool_call.arguments)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                            "content": result,
                        })
                else:
                    final_result = response.content
                    break

            if final_result is None:
                final_result = "Task completed but no final response was generated."

            logger.info("Subagent [{}] completed successfully", task_id)
            await self._announce_result(task_id, label, task, final_result, origin, "ok")

        except Exception as e:
            error_msg = f"Error: {str(e)}"
            logger.error("Subagent [{}] failed: {}", task_id, e)
            await self._announce_result(task_id, label, task, error_msg, origin, "error")

    async def _announce_result(
        self,
        task_id: str,
        label: str,
        task: str,
        result: str,
        origin: dict[str, str],
        status: str,
    ) -> None:
        """Announce the subagent result to the main agent via the message bus."""
        status_text = "completed successfully" if status == "ok" else "failed"

        announce_content = f"""[Subagent '{label}' {status_text}]

Task: {task}

Result:
{result}

Summarize this naturally for the user. Keep it brief (1-2 sentences). Do not mention technical details like "subagent" or task IDs."""

        msg = InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id=f"{origin['channel']}:{origin['chat_id']}",
            content=announce_content,
        )

        await self.bus.publish_inbound(msg)
        logger.debug("Subagent [{}] announced result to {}:{}", task_id, origin['channel'], origin['chat_id'])

    def _build_subagent_prompt(
        self,
        task: str,
        profile: "SubagentProfile | None" = None,
        skills_content: str = "",
    ) -> str:
        """Build a focused system prompt for the subagent."""
        from datetime import datetime
        import time as _time
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        tz = _time.strftime("%Z") or "UTC"

        role_section = ""
        if profile and profile.description:
            role_section = f"\n## Role\n{profile.description}\n"

        return f"""# Subagent

## Current Time
{now} ({tz})

You are a subagent spawned by the main agent to complete a specific task.
{role_section}
## Rules
1. Stay focused - complete only the assigned task, nothing else
2. Your final response will be reported back to the main agent
3. Do not initiate conversations or take on side tasks
4. Be concise but informative in your findings

## What You Can Do
- Read and write files in the workspace
- Execute shell commands
- Search the web and fetch web pages
- Complete the task thoroughly

## What You Cannot Do
- Send messages directly to users (no message tool available)
- Spawn other subagents
- Access the main agent's conversation history

## Workspace
Your workspace is at: {self.workspace}
Skills are available at: {self.workspace}/skills/ (read SKILL.md files as needed)
{skills_content}
When you have completed the task, provide a clear summary of your findings or actions."""
    
    async def cancel_by_session(self, session_key: str) -> int:
        """Cancel all subagents for the given session. Returns count cancelled."""
        tasks = [self._running_tasks[tid] for tid in self._session_tasks.get(session_key, [])
                 if tid in self._running_tasks and not self._running_tasks[tid].done()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return len(tasks)

    def get_running_count(self) -> int:
        """Return the number of currently running subagents."""
        return len(self._running_tasks)
