"""Subagent manager for background task execution."""

import asyncio
import json
import random
import re
import uuid
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool, ListDirTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebSearchTool, WebFetchTool

# Subagent context limits (tighter than main agent)
_MAX_TOOL_RESULT_CHARS = 2000
_MAX_CONTEXT_MESSAGES = 25
_EMPTY_RESPONSE_RETRIES = 1       # Bounded retry when LLM returns empty
_MAX_ANNOUNCE_CHARS = 3000        # Cap result injected back into main agent


class SubagentManager:
    """
    Manages background subagent execution.
    
    Subagents are lightweight agent instances that run in the background
    to handle specific tasks. They share the same LLM provider but have
    isolated context and a focused system prompt.
    """
    
    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        bus: MessageBus,
        model: str | None = None,
        brave_api_key: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        restrict_to_workspace: bool = False,
    ):
        from nanobot.config.schema import ExecToolConfig
        self.provider = provider
        self.workspace = workspace
        self.bus = bus
        self.model = model or provider.get_default_model()
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.restrict_to_workspace = restrict_to_workspace
        self._running_tasks: dict[str, asyncio.Task[None]] = {}

    # ----- Context helpers (mirrors AgentLoop but tighter) -----

    @staticmethod
    def _truncate_result(result: str) -> str:
        """Truncate tool result for subagent context.

        Content-type-aware: JSON is prefix-truncated so the visible
        portion remains valid syntax; plain text uses head truncation.
        """
        clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', result)
        if len(clean) <= _MAX_TOOL_RESULT_CHARS:
            return clean

        # Detect JSON and handle it without breaking syntax
        stripped = clean.lstrip()
        if stripped and stripped[0] in ('{', '['):
            try:
                parsed = json.loads(clean)
                pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
                if len(pretty) <= _MAX_TOOL_RESULT_CHARS:
                    return pretty
                budget = _MAX_TOOL_RESULT_CHARS - 100  # room for sentinel
                return (
                    pretty[:budget]
                    + f"\n\n... [JSON truncated — showed {budget} of {len(pretty)} chars. "
                    + "Do NOT re-run this tool to see more.]"
                )
            except (json.JSONDecodeError, ValueError):
                pass

        # Plain text: head truncation with sentinel
        budget = _MAX_TOOL_RESULT_CHARS - 80
        return (
            clean[:budget]
            + f"\n\n... [truncated — showed {budget} of {len(clean)} chars. "
            + "Do NOT re-run this tool to see more.]"
        )

    @staticmethod
    def _compact(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Compact subagent messages using block-aware grouping.

        Groups an assistant message with tool_calls + its subsequent tool
        results as a single atomic block.  Never splits these pairs — doing
        so causes HTTP 400 from every major LLM API.
        """
        if len(messages) <= _MAX_CONTEXT_MESSAGES:
            return messages

        protected = messages[:2]  # system prompt + user goal
        remaining = messages[2:]

        # Build atomic blocks
        blocks: list[list[dict[str, Any]]] = []
        i = 0
        while i < len(remaining):
            msg = remaining[i]
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                block = [msg]
                j = i + 1
                while j < len(remaining) and remaining[j].get("role") == "tool":
                    block.append(remaining[j])
                    j += 1
                blocks.append(block)
                i = j
            else:
                blocks.append([msg])
                i += 1

        # Take blocks from the end within budget
        budget = _MAX_CONTEXT_MESSAGES - len(protected)
        kept: list[list[dict[str, Any]]] = []
        total = 0
        for block in reversed(blocks):
            if total + len(block) > budget:
                break
            kept.append(block)
            total += len(block)

        kept.reverse()
        tail = [m for block in kept for m in block]
        return protected + tail
    
    async def spawn(
        self,
        task: str,
        label: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
    ) -> str:
        """
        Spawn a subagent to execute a task in the background.
        
        Args:
            task: The task description for the subagent.
            label: Optional human-readable label for the task.
            origin_channel: The channel to announce results to.
            origin_chat_id: The chat ID to announce results to.
        
        Returns:
            Status message indicating the subagent was started.
        """
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")
        
        origin = {
            "channel": origin_channel,
            "chat_id": origin_chat_id,
        }
        
        # Create background task
        bg_task = asyncio.create_task(
            self._run_subagent(task_id, task, display_label, origin)
        )
        self._running_tasks[task_id] = bg_task
        
        # Cleanup when done — also log any unhandled exceptions
        def _on_done(t: asyncio.Task[None]) -> None:
            self._running_tasks.pop(task_id, None)
            if t.cancelled():
                logger.warning(f"Subagent [{task_id}] was cancelled")
            elif t.exception() is not None:
                logger.error(f"Subagent [{task_id}] raised unhandled exception: {t.exception()!r}")

        bg_task.add_done_callback(_on_done)
        
        logger.info(f"Spawned subagent [{task_id}]: {display_label}")
        return f"Subagent [{display_label}] started (id: {task_id}). I'll notify you when it completes."
    
    async def _run_subagent(
        self,
        task_id: str,
        task: str,
        label: str,
        origin: dict[str, str],
    ) -> None:
        """Execute the subagent task and announce the result."""
        logger.info(f"Subagent [{task_id}] starting task: {label}")
        
        try:
            # Build subagent tools (no message tool, no spawn tool)
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
            
            # Build messages with subagent-specific prompt
            system_prompt = self._build_subagent_prompt(task)
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ]
            
            # Run agent loop (limited iterations)
            max_iterations = 15
            iteration = 0
            empty_retries_left = _EMPTY_RESPONSE_RETRIES
            final_result: str | None = None
            
            while iteration < max_iterations:
                iteration += 1

                # Compact before each LLM call
                messages = self._compact(messages)
                
                response = await self.provider.chat(
                    messages=messages,
                    tools=tools.get_definitions(),
                    model=self.model,
                )
                
                # Detect LLM errors returned as content
                if (response.finish_reason == "error"
                        or (response.content and response.content.startswith("Error calling LLM:"))):
                    logger.error(f"Subagent [{task_id}] LLM error: {response.content}")
                    final_result = "Task failed due to an LLM error."
                    break
                
                if response.has_tool_calls:
                    # Add assistant message with tool calls
                    tool_call_dicts = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in response.tool_calls
                    ]
                    messages.append({
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": tool_call_dicts,
                    })
                    
                    # Execute tools — truncate results at source
                    for tool_call in response.tool_calls:
                        args_str = json.dumps(tool_call.arguments)
                        logger.debug(f"Subagent [{task_id}] executing: {tool_call.name} with arguments: {args_str}")
                        raw_result = await tools.execute(tool_call.name, tool_call.arguments)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                            "content": self._truncate_result(raw_result),
                        })
                else:
                    if response.content:
                        final_result = response.content
                        break
                    # Bounded retry with exponential backoff + jitter
                    if empty_retries_left > 0:
                        empty_retries_left -= 1
                        retry_num = _EMPTY_RESPONSE_RETRIES - empty_retries_left
                        delay = min(2 ** retry_num + random.uniform(0, 1), 10.0)
                        logger.warning(
                            f"Subagent [{task_id}] got empty response, "
                            f"retries left: {empty_retries_left}, backing off {delay:.1f}s"
                        )
                        await asyncio.sleep(delay)
                        continue
                    logger.warning(f"Subagent [{task_id}] empty response, no retries left — giving up")
                    break
            
            if final_result is None:
                final_result = "Task completed but no final response was generated."
            
            logger.info(f"Subagent [{task_id}] completed successfully")
            await self._announce_result(task_id, label, task, final_result, origin, "ok")
            
        except Exception as e:
            error_msg = f"Error: {str(e)}"
            logger.error(f"Subagent [{task_id}] failed: {e}")
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
        
        # Cap result size to prevent re-triggering context explosion
        # in the main agent when this gets injected as a message.
        if len(result) > _MAX_ANNOUNCE_CHARS:
            half = _MAX_ANNOUNCE_CHARS // 2
            result = (
                result[:half]
                + f"\n\n... [truncated {len(result) - _MAX_ANNOUNCE_CHARS} chars] ...\n\n"
                + result[-half:]
            )
        
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
        logger.debug(f"Subagent [{task_id}] announced result to {origin['channel']}:{origin['chat_id']}")
    
    def _build_subagent_prompt(self, task: str) -> str:
        """Build a focused system prompt for the subagent."""
        return f"""# Subagent

You are a subagent spawned by the main agent to complete a specific task.

## Your Task
{task}

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

When you have completed the task, provide a clear summary of your findings or actions."""
    
    def get_running_count(self) -> int:
        """Return the number of currently running subagents."""
        return len(self._running_tasks)
