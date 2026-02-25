"""Subagent manager for background task execution."""

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
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


@dataclass
class SubagentTask:
    """Represents a subagent task with state tracking."""
    task_id: str
    label: str
    task: str
    profile: str | None = None
    status: str = "running"  # running, completed, failed, cancelled
    iteration: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    result: str | None = None
    error: str | None = None
    origin_channel: str = "cli"
    origin_chat_id: str = "direct"


class SubagentManager:
    """
    Manages background subagent execution.

    Subagents are lightweight agent instances that run in the background
    to handle specific tasks. They share the same LLM provider but have
    isolated context and a focused system prompt.
    """

    # Helper methods for formatting tool calls (same as AgentLoop)
    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        """Remove thinking blocks that some models embed in content."""
        if not text:
            return None
        import re
        return re.sub(r"<thinking>[\s\S]*?</thinking>", "", text).strip() or None

    @staticmethod
    def _tool_hint(tool_calls: list | None) -> str:
        """Format tool calls as concise hint, e.g. 'web_search("query")'."""
        if not tool_calls:
            return ""
        def _fmt(tc):
            val = next(iter(tc.arguments.values()), None) if tc.arguments else None
            if not isinstance(val, str):
                return tc.name
            return f'{tc.name}("{val[:40]}…")' if len(val) > 40 else f'{tc.name}("{val}")'
        return ", ".join(_fmt(tc) for tc in tool_calls)

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
        config: "Config | None" = None,
    ):
        from nanobot.config.schema import ExecToolConfig, Config
        self.provider = provider
        # Ensure workspace is expanded from ~ to absolute path
        if isinstance(workspace, Path):
            self.workspace = workspace
        else:
            self.workspace = Path(workspace).expanduser()
        self.bus = bus
        self.model = model or provider.get_default_model()
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.restrict_to_workspace = restrict_to_workspace
        self.config = config
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        self._task_states: dict[str, SubagentTask] = {}  # Track task state
        self._parallel_groups: dict[str, list[str]] = {}  # Track parallel groups

    async def spawn(
        self,
        task: str,
        label: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
        profile: "AgentProfile | None" = None,
    ) -> str:
        """
        Spawn a subagent to execute a task in the background.

        Args:
            task: The task description for the subagent.
            label: Optional human-readable label for the task.
            origin_channel: The channel to announce results to.
            origin_chat_id: The chat ID to announce results to.
            profile: Optional agent profile to use for this subagent.

        Returns:
            Status message indicating the subagent was started.
        """
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")

        # Get profile name if profile object provided
        profile_name = None
        if profile:
            # Find profile name from config
            if self.config:
                for name, p in self.config.agents.profiles.items():
                    if p == profile:
                        profile_name = name
                        break

        # Create task state
        task_state = SubagentTask(
            task_id=task_id,
            label=display_label,
            task=task,
            profile=profile_name,
            origin_channel=origin_channel,
            origin_chat_id=origin_chat_id,
        )
        self._task_states[task_id] = task_state

        origin = {
            "channel": origin_channel,
            "chat_id": origin_chat_id,
        }

        # Create background task
        bg_task = asyncio.create_task(
            self._run_subagent(task_id, task, display_label, origin, profile)
        )
        self._running_tasks[task_id] = bg_task

        # Cleanup when done
        def cleanup(_: asyncio.Task) -> None:
            self._running_tasks.pop(task_id, None)
            # Keep task state for history (don't delete immediately)

        bg_task.add_done_callback(cleanup)

        logger.info("Spawned subagent [{}]: {}", task_id, display_label)

        # Build detailed status message
        profile_suffix = f" (profile: {profile_name})" if profile_name else ""
        status_msg = (
            f"🤖 Subagent [{display_label}] started (id: {task_id}){profile_suffix}\n"
            f"Task: {task}\n"
            f"I'll notify you when it completes."
        )
        return status_msg

    def get_running_tasks(self) -> list[SubagentTask]:
        """Get all tracked tasks (running and recently completed)."""
        # Clean up very old completed tasks (older than 1 hour)
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(hours=1)
        self._task_states = {
            k: v for k, v in self._task_states.items()
            if v.status == "running" or v.completed_at and v.completed_at > cutoff
        }
        return list(self._task_states.values())

    async def cancel(self, task_id: str) -> bool:
        """Cancel a running subagent by task ID."""
        task = self._running_tasks.get(task_id)
        if not task:
            return False

        task.cancel()
        # Update state
        if task_id in self._task_states:
            self._task_states[task_id].status = "cancelled"
            self._task_states[task_id].completed_at = datetime.now()
            self._task_states[task_id].error = "Cancelled by user"

        logger.info("Subagent [{}] cancelled", task_id)
        return True
    
    async def _send_progress(
        self,
        origin: dict[str, str],
        content: str,
        message_type: str = "thinking",
    ) -> None:
        """Send a progress message to the original channel."""
        from nanobot.bus.events import OutboundMessage

        msg = OutboundMessage(
            channel=origin["channel"],
            chat_id=origin["chat_id"],
            content=content,
            metadata={"message_type": message_type},
        )
        await self.bus.publish_outbound(msg)

    def _log_monitor(self, msg_type: str, content: str, task_id: str, label: str) -> None:
        """Log a subagent message to the monitor file."""
        try:
            from nanobot.config.loader import get_data_dir
            from datetime import datetime

            monitor_dir = get_data_dir() / "monitor"
            monitor_dir.mkdir(parents=True, exist_ok=True)
            monitor_file = monitor_dir / "messages.log"

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # Safe content handling for None
            safe_content = (content or "")[:200]
            log_entry = f"[{timestamp}] [subagent:{task_id}|{label}] {msg_type}: {safe_content}\n"

            with open(monitor_file, "a", encoding="utf-8") as f:
                f.write(log_entry)
        except Exception:
            # Don't let monitor logging break the subagent
            pass

    async def _run_subagent(
        self,
        task_id: str,
        task: str,
        label: str,
        origin: dict[str, str],
        profile: "AgentProfile | None" = None,
    ) -> None:
        """Execute the subagent task and announce the result."""
        logger.info("Subagent [{}] starting task: {}", task_id, label)
        # Safe task preview
        task_preview = (task or "")[:100]
        self._log_monitor("start", f"Task: {task_preview}", task_id, label)

        task_state = self._task_states.get(task_id)
        if not task_state:
            logger.error("Subagent [{}] task state not found", task_id)
            return

        try:
            # Resolve model and temperature from profile if provided
            model = self.model
            temperature = self.temperature
            max_tokens = self.max_tokens

            if profile:
                model = profile.model or model
                temperature = profile.temperature or temperature
                max_tokens = profile.max_tokens or max_tokens

            # Build subagent tools (no message tool, no spawn tool)
            tools = ToolRegistry()
            allowed_dir = self.workspace if self.restrict_to_workspace else None
            tools.register(ReadFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(WriteFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(EditFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(ListDirTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(ExecTool(
                working_dir=str(self.workspace),
                timeout=self.exec_config.timeout,
                restrict_to_workspace=self.restrict_to_workspace,
            ))
            tools.register(WebSearchTool(api_key=self.brave_api_key))
            tools.register(WebFetchTool())

            # Scrapling web scraping tools
            from nanobot.agent.tools.scrapling import (
                ScrapePageTool,
                ScrapeStealthyTool,
                ScrapeDynamicTool,
                ScrapeSpiderTool
            )
            tools.register(ScrapePageTool())
            tools.register(ScrapeStealthyTool())
            tools.register(ScrapeDynamicTool())
            tools.register(ScrapeSpiderTool())

            # Build messages with subagent-specific prompt
            system_prompt = self._build_subagent_prompt(task, profile)
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ]

            # Run agent loop (limited iterations)
            max_iterations = 15
            iteration = 0
            final_result: str | None = None
            last_progress_update = datetime.now()

            while iteration < max_iterations:
                iteration += 1

                # Update task state
                if task_id in self._task_states:
                    self._task_states[task_id].iteration = iteration
                    self._task_states[task_id].last_activity = datetime.now()

                response = await self.provider.chat(
                    messages=messages,
                    tools=tools.get_definitions(),
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                if response.has_tool_calls:
                    # Send progress updates for tool calls
                    clean = self._strip_think(response.content)
                    if clean:
                        await self._send_progress(origin, f"[{label}] {clean}", message_type="thinking")
                        self._log_monitor("thinking", clean[:100], task_id, label)
                    tool_hint = self._tool_hint(response.tool_calls)
                    await self._send_progress(origin, f"[{label}] {tool_hint}", message_type="action")
                    self._log_monitor("action", tool_hint, task_id, label)

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
                    messages.append({
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": tool_call_dicts,
                    })

                    # Execute tools
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

                    # Send periodic "working on" update every 30 seconds
                    now = datetime.now()
                    if (now - last_progress_update).total_seconds() >= 30:
                        await self._send_progress(
                            origin,
                            f"[{label}] Working on task... (iteration {iteration}/{max_iterations})",
                            message_type="thinking"
                        )
                        last_progress_update = now
                else:
                    final_result = response.content
                    break

            if final_result is None:
                final_result = "Task completed but no final response was generated."

            logger.info("Subagent [{}] completed successfully", task_id)
            self._log_monitor("complete", f"Result: {final_result[:100]}", task_id, label)

            # Update task state
            if task_id in self._task_states:
                self._task_states[task_id].status = "completed"
                self._task_states[task_id].completed_at = datetime.now()
                self._task_states[task_id].result = final_result[:1000]  # Store first 1000 chars

            await self._announce_result(task_id, label, task, final_result, origin, "ok")

        except asyncio.CancelledError:
            logger.info("Subagent [{}] was cancelled", task_id)
            self._log_monitor("cancelled", "Task was cancelled", task_id, label)
            if task_id in self._task_states:
                self._task_states[task_id].status = "cancelled"
                self._task_states[task_id].completed_at = datetime.now()
                self._task_states[task_id].error = "Cancelled"
            await self._announce_result(task_id, label, task, "Task was cancelled", origin, "cancelled")
        except Exception as e:
            error_msg = f"Error: {str(e)}"
            logger.error("Subagent [{}] failed: {}", task_id, e)
            self._log_monitor("error", error_msg, task_id, label)
            if task_id in self._task_states:
                self._task_states[task_id].status = "failed"
                self._task_states[task_id].completed_at = datetime.now()
                self._task_states[task_id].error = error_msg[:500]
            await self._announce_result(task_id, label, task, error_msg, origin, "error")

    def _build_subagent_prompt(self, task: str, profile: "AgentProfile | None" = None) -> str:
        """Build a focused system prompt for the subagent."""
        from datetime import datetime
        import time as _time
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        tz = _time.strftime("%Z") or "UTC"

        # Build custom prompt section if profile has one
        custom_prompt = ""
        if profile and profile.system_prompt:
            if profile.inherit_base_prompt:
                custom_prompt = f"\n\n## Additional Instructions\n{profile.system_prompt}"
            else:
                custom_prompt = f"\n\n{profile.system_prompt}\n\n---\n\n"

        return f"""# Subagent

## Current Time
{now} ({tz})

You are a subagent spawned by the main agent to complete a specific task.{custom_prompt}

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

When you have completed the task, provide a clear summary of your findings or actions."""

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
        from nanobot.config.loader import get_data_dir
        from datetime import datetime

        status_text = "completed successfully" if status == "ok" else "failed"

        announce_content = f"""[Subagent '{label}' {status_text}]

Task: {task}

Result:
{result}

Summarize this naturally for the user. Keep it brief (1-2 sentences). Do not mention technical details like "subagent" or task IDs."""

        # Log to monitor
        try:
            monitor_dir = get_data_dir() / "monitor"
            monitor_dir.mkdir(parents=True, exist_ok=True)
            monitor_file = monitor_dir / "messages.log"
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            session = f"{origin['channel']}:{origin['chat_id']}"
            # Safe result handling for None
            safe_result = (result or "")[:200]
            log_entry = f"[{timestamp}] [subagent session:{session}] {label}: {safe_result}\n"
            with open(monitor_file, "a", encoding="utf-8") as f:
                f.write(log_entry)
        except Exception:
            pass

        # Inject as system message to trigger main agent
        msg = InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id=f"{origin['channel']}:{origin['chat_id']}",
            content=announce_content,
        )

        await self.bus.publish_inbound(msg)
        logger.debug("Subagent [{}] announced result to {}:{}", task_id, origin['channel'], origin['chat_id'])

    def get_running_count(self) -> int:
        """Return the number of currently running subagents."""
        return len(self._running_tasks)

    async def await_agent(self, task_id: str, timeout: float = 300.0) -> SubagentTask:
        """
        Wait for a specific subagent to complete and return its result.

        Args:
            task_id: The task ID to wait for
            timeout: Maximum wait time in seconds (default: 300)

        Returns:
            The completed SubagentTask with result

        Raises:
            asyncio.TimeoutError: If timeout is exceeded
            ValueError: If task_id not found
        """
        if task_id not in self._task_states:
            raise ValueError(f"Task '{task_id}' not found")

        task = self._running_tasks.get(task_id)
        if not task:
            # Task might already be complete
            state = self._task_states.get(task_id)
            if state and state.status in ("completed", "failed", "cancelled"):
                return state
            raise ValueError(f"Task '{task_id}' is not running")

        try:
            await asyncio.wait_for(task, timeout=timeout)
        except asyncio.TimeoutError:
            # Try to cancel the task
            await self.cancel(task_id)
            raise asyncio.TimeoutError(f"Task '{task_id}' timed out after {timeout}s")

        # Return the completed task state
        return self._task_states.get(task_id)

    def get_agent_result(self, task_id: str) -> str | None:
        """
        Get the result from a completed subagent.

        Args:
            task_id: The task ID to get result from

        Returns:
            The result string, or None if not available
        """
        state = self._task_states.get(task_id)
        if not state:
            return None

        if state.status != "completed":
            return None

        return state.result

    async def spawn_chain(self, tasks: list[dict[str, Any]]) -> list[SubagentTask]:
        """
        Execute a chain of tasks sequentially (pipeline pattern).

        Each task waits for the previous one to complete before starting.
        Results from previous tasks can be passed to subsequent tasks.

        Args:
            tasks: List of task dicts with keys:
                - task: The task description
                - label: Short label
                - profile: Optional agent profile
                - use_result: Optional bool to include previous result in context

        Returns:
            List of completed SubagentTask objects in order
        """
        completed = []
        previous_result = None
        origin_channel = "cli"
        origin_chat_id = "direct"

        for i, task_spec in enumerate(tasks):
            # Build task with context from previous result
            task_desc = task_spec.get("task", "")
            label = task_spec.get("label", f"Chain step {i+1}")
            profile = self._resolve_profile(task_spec.get("profile"))
            use_result = task_spec.get("use_result", False)

            if use_result and previous_result:
                task_desc = f"Previous result:\n{previous_result}\n\nNew task:\n{task_desc}"

            # Spawn and wait for completion
            await self.spawn(
                task=task_desc,
                label=label,
                origin_channel=origin_channel,
                origin_chat_id=origin_chat_id,
                profile=profile,
            )

            # Wait for this specific task
            # Get the most recent task_id
            task_id = list(self._running_tasks.keys())[-1]
            completed_task = await self.await_agent(task_id)
            completed.append(completed_task)

            # Store result for next task
            if completed_task.status == "completed":
                previous_result = completed_task.result
            else:
                # Task failed, stop the chain
                break

        return completed

    def _resolve_profile(self, profile_name: str | None) -> "AgentProfile | None":
        """Resolve profile name to AgentProfile object."""
        if not profile_name or not self.config:
            return None

        return self.config.agents.profiles.get(profile_name)

    async def create_parallel_group(self, group_id: str, tasks: list[dict[str, Any]]) -> list[str]:
        """
        Create a parallel group of subagents (hybrid pattern support).

        All tasks in the group are spawned simultaneously.
        Use await_group() to wait for all to complete.

        Args:
            group_id: Unique identifier for this group
            tasks: List of task dicts with keys:
                - task: The task description
                - label: Short label
                - profile: Optional agent profile

        Returns:
            List of task IDs for the spawned agents
        """
        task_ids = []
        origin_channel = "cli"
        origin_chat_id = "direct"

        for task_spec in tasks:
            task_desc = task_spec.get("task", "")
            label = task_spec.get("label", f"Group {group_id} task")
            profile_name = task_spec.get("profile")
            profile = self._resolve_profile(profile_name)

            # Spawn the subagent (non-blocking)
            result = await self.spawn(
                task=task_desc,
                label=label,
                origin_channel=origin_channel,
                origin_chat_id=origin_chat_id,
                profile=profile,
            )

            # Extract task_id from the result message
            # Format: "Subagent [label] started (id: {task_id})..."
            import re
            match = re.search(r'\(id:\s*([a-z0-9]+)\)', result)
            if match:
                task_ids.append(match.group(1))

        # Track the group
        self._parallel_groups[group_id] = task_ids

        return task_ids

    async def await_group(self, group_id: str, timeout: float = 600.0) -> list[SubagentTask]:
        """
        Wait for all agents in a parallel group to complete.

        Args:
            group_id: The group ID to wait for
            timeout: Maximum wait time in seconds (default: 600)

        Returns:
            List of completed SubagentTask objects

        Raises:
            ValueError: If group_id not found
            asyncio.TimeoutError: If timeout is exceeded
        """
        if group_id not in self._parallel_groups:
            raise ValueError(f"Group '{group_id}' not found")

        task_ids = self._parallel_groups[group_id]

        try:
            # Wait for all tasks in the group
            await asyncio.wait_for(
                asyncio.gather(*[
                    self._running_tasks[tid] for tid in task_ids
                    if tid in self._running_tasks
                ], return_exceptions=True),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            # Cancel remaining tasks
            for tid in task_ids:
                await self.cancel(tid)
            raise asyncio.TimeoutError(f"Group '{group_id}' timed out after {timeout}s")

        # Return all completed tasks
        return [
            self._task_states[tid] for tid in task_ids
            if tid in self._task_states
        ]

    async def wait_all(
        self,
        task_ids: list[str],
        mode: str = "all",
        timeout: float = 600.0
    ) -> dict[str, SubagentTask]:
        """
        Wait for multiple agents with flexible conditions.

        Args:
            task_ids: List of task IDs to wait for
            mode: "all" (wait for everyone) or "any" (wait for first completion)
            timeout: Maximum wait time in seconds

        Returns:
            Dictionary mapping task_id to SubagentTask

        Raises:
            ValueError: If mode is invalid
            asyncio.TimeoutError: If timeout is exceeded
        """
        if mode not in ("all", "any"):
            raise ValueError(f"Invalid mode: {mode}. Use 'all' or 'any'")

        if not task_ids:
            return {}

        valid_tasks = [
            self._running_tasks[tid] for tid in task_ids
            if tid in self._running_tasks
        ]

        if not valid_tasks:
            return {
                tid: self._task_states[tid]
                for tid in task_ids
                if tid in self._task_states
            }

        if mode == "all":
            await asyncio.wait_for(
                asyncio.gather(*valid_tasks, return_exceptions=True),
                timeout=timeout
            )
        else:  # mode == "any"
            await asyncio.wait_for(
                asyncio.wait(valid_tasks, return_when=asyncio.FIRST_COMPLETED),
                timeout=timeout
            )

        return {
            tid: self._task_states[tid]
            for tid in task_ids
            if tid in self._task_states
        }
