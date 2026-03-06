"""Subagent manager for background task execution."""

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ExecToolConfig
from nanobot.providers.base import LLMProvider


@dataclass
class ToolCallRecord:
    """Record of a tool call for convergence detection."""
    name: str
    arguments: dict[str, Any]
    result: str
    timestamp: float = field(default_factory=lambda: datetime.now(UTC).timestamp())


@dataclass
class PendingSubagentTask:
    """Persistent record of a running subagent task."""
    task_id: str
    task: str
    label: str
    origin: dict[str, str]
    started_at: float
    status: str = "running"  # running, completed, failed
    result: str | None = None
    completed_at: float | None = None


class SubagentManager:
    """Manages background subagent execution."""

    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        bus: MessageBus,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        reasoning_effort: str | None = None,
        brave_api_key: str | None = None,
        web_proxy: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        restrict_to_workspace: bool = False,
    ):
        from nanobot.config.schema import ExecToolConfig
        self.provider = provider
        self.workspace = workspace
        self.bus = bus
        self.model = model or provider.get_default_model()
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.brave_api_key = brave_api_key
        self.web_proxy = web_proxy
        self.exec_config = exec_config or ExecToolConfig()
        self.restrict_to_workspace = restrict_to_workspace
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        
        # Persistent task tracking
        self._pending_tasks_file = workspace / ".nanobot" / "pending_subagent_tasks.json"
        self._pending_tasks_file.parent.mkdir(parents=True, exist_ok=True)
        self._pending_tasks: dict[str, PendingSubagentTask] = self._load_pending_tasks()
        self._session_tasks: dict[str, set[str]] = {}  # session_key -> {task_id, ...}

    async def spawn(
        self,
        task: str,
        label: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
        session_key: str | None = None,
    ) -> str:
        """Spawn a subagent to execute a task in the background."""
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")
        origin = {"channel": origin_channel, "chat_id": origin_chat_id}

        bg_task = asyncio.create_task(
            self._run_subagent(task_id, task, display_label, origin)
        )
        self._running_tasks[task_id] = bg_task
        if session_key:
            self._session_tasks.setdefault(session_key, set()).add(task_id)

        def _cleanup(_: asyncio.Task) -> None:
            self._running_tasks.pop(task_id, None)
            if session_key and (ids := self._session_tasks.get(session_key)):
                ids.discard(task_id)
                if not ids:
                    del self._session_tasks[session_key]

        bg_task.add_done_callback(_cleanup)

        logger.info("Spawned subagent [{}]: {}", task_id, display_label)
        return f"Subagent [{display_label}] started (id: {task_id}). I'll notify you when it completes."

    async def _run_subagent(
        self,
        task_id: str,
        task: str,
        label: str,
        origin: dict[str, str],
    ) -> None:
        """Execute the subagent task with self-correction limits and announce the result."""
        logger.info("Subagent [{}] starting task: {}", task_id, label)

        # Create pending task record for persistence
        pending_task = PendingSubagentTask(
            task_id=task_id,
            task=task,
            label=label,
            origin=origin,
            started_at=datetime.now(UTC).timestamp(),
        )
        self._pending_tasks[task_id] = pending_task
        self._save_pending_tasks()

        try:
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
                path_append=self.exec_config.path_append,
            ))
            tools.register(WebSearchTool(api_key=self.brave_api_key, proxy=self.web_proxy))
            tools.register(WebFetchTool(proxy=self.web_proxy))
            
            system_prompt = self._build_subagent_prompt()
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ]

            # Run agent loop with convergence detection
            max_iterations = 15
            convergence_threshold = 5  # More lenient to avoid false positives
            iteration = 0
            final_result: str | None = None
            tool_call_history: list[ToolCallRecord] = []

            while iteration < max_iterations:
                iteration += 1

                response = await self.provider.chat(
                    messages=messages,
                    tools=tools.get_definitions(),
                    model=self.model,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    reasoning_effort=self.reasoning_effort,
                )

                if response.has_tool_calls:
                    # Check for convergence issues before executing tools
                    convergence_error = self._check_convergence(
                        response.tool_calls, tool_call_history, convergence_threshold
                    )
                    if convergence_error:
                        final_result = convergence_error
                        logger.warning("Subagent [{}] stopped due to convergence: {}", task_id, convergence_error)
                        break

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

                    # Execute tools and record for convergence detection
                    for tool_call in response.tool_calls:
                        args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                        logger.debug("Subagent [{}] executing: {} with arguments: {}", task_id, tool_call.name, args_str)
                        
                        result = await tools.execute(tool_call.name, tool_call.arguments)
                        
                        # Record tool call for convergence detection
                        tool_record = ToolCallRecord(
                            name=tool_call.name,
                            arguments=tool_call.arguments,
                            result=result
                        )
                        tool_call_history.append(tool_record)
                        
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
            self._complete_pending_task(task_id, "completed", final_result)

        except Exception as e:
            error_msg = f"Error: {str(e)}"
            logger.error("Subagent [{}] failed: {}", task_id, e)
            await self._announce_result(task_id, label, task, error_msg, origin, "error")
            self._complete_pending_task(task_id, "failed", error_msg)
        finally:
            # Clean up running task reference
            self._running_tasks.pop(task_id, None)

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

        # Inject as system message to trigger main agent
        msg = InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id=f"{origin['channel']}:{origin['chat_id']}",
            content=announce_content,
        )

        await self.bus.publish_inbound(msg)
        logger.debug("Subagent [{}] announced result to {}:{}", task_id, origin['channel'], origin['chat_id'])
    
    def _build_subagent_prompt(self) -> str:
        """Build a focused system prompt for the subagent."""
        from nanobot.agent.context import ContextBuilder
        from nanobot.agent.skills import SkillsLoader

        time_ctx = ContextBuilder._build_runtime_context(None, None)
        parts = [f"""# Subagent

{time_ctx}

You are a subagent spawned by the main agent to complete a specific task.
Stay focused on the assigned task. Your final response will be reported back to the main agent.

## Workspace
{self.workspace}"""]

        skills_summary = SkillsLoader(self.workspace).build_skills_summary()
        if skills_summary:
            parts.append(f"## Skills\n\nRead SKILL.md with read_file to use a skill.\n\n{skills_summary}")

        return "\n\n".join(parts)
    
    def _check_convergence(
        self, 
        current_tool_calls, 
        history: list[ToolCallRecord], 
        threshold: int
    ) -> str | None:
        """Check if the subagent is stuck in a convergence loop.
        
        Returns error message if convergence detected, None otherwise.
        """
        if len(history) < threshold:
            return None
            
        # Check each current tool call against recent history
        for tool_call in current_tool_calls:
            recent_identical = 0
            
            # Count recent identical calls (same name + arguments)
            for record in reversed(history[-10:]):  # Check last 10 calls
                if (record.name == tool_call.name and 
                    record.arguments == tool_call.arguments):
                    recent_identical += 1
                    
                    # If we've seen this exact call multiple times recently
                    if recent_identical >= threshold - 1:  # -1 because we're about to execute it again
                        return (
                            f"Convergence detected: Tool '{tool_call.name}' called {threshold} times "
                            f"with identical arguments. This suggests the subagent is stuck in a loop. "
                            f"Task terminated to prevent unnecessary token usage."
                        )
        
        return None

    def _complete_pending_task(self, task_id: str, status: str, result: str | None) -> None:
        """Mark a pending task as completed and persist the result."""
        if hasattr(self, '_pending_tasks') and task_id in self._pending_tasks:
            task = self._pending_tasks[task_id]
            task.status = status
            task.result = result
            task.completed_at = datetime.now(UTC).timestamp()
            
            # Persist to file for recovery after restart
            self._save_pending_tasks()
            logger.debug("Subagent task [{}] marked as {}: {}", task_id, status, result)

    def _load_pending_tasks(self) -> dict[str, PendingSubagentTask]:
        """Load pending tasks from persistent storage."""
        if not self._pending_tasks_file.exists():
            return {}
        
        try:
            with open(self._pending_tasks_file) as f:
                data = json.load(f)
            
            tasks = {}
            for task_id, task_data in data.items():
                tasks[task_id] = PendingSubagentTask(
                    task_id=task_data["task_id"],
                    task=task_data["task"],
                    label=task_data["label"],
                    origin=task_data["origin"],
                    started_at=task_data["started_at"],
                    status=task_data["status"],
                    result=task_data.get("result"),
                    completed_at=task_data.get("completed_at"),
                )
            
            logger.debug("Loaded {} pending subagent tasks from file", len(tasks))
            return tasks
        except Exception as e:
            logger.warning("Failed to load pending tasks: {}", e)
            return {}

    def _save_pending_tasks(self) -> None:
        """Save pending tasks to persistent storage."""
        try:
            data = {}
            for task_id, task in self._pending_tasks.items():
                data[task_id] = {
                    "task_id": task.task_id,
                    "task": task.task,
                    "label": task.label,
                    "origin": task.origin,
                    "started_at": task.started_at,
                    "status": task.status,
                    "result": task.result,
                    "completed_at": task.completed_at,
                }
            
            with open(self._pending_tasks_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning("Failed to save pending tasks: {}", e)
    
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
