"""Agent loop: the core processing engine."""

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider
from nanobot.agent.context import ContextBuilder
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool, EditFileTool, ListDirTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebSearchTool, WebFetchTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.subagent import SubagentManager
from nanobot.session.manager import SessionManager

# --- Context window safety constants ---
MAX_TOOL_RESULT_CHARS = 3000     # Truncate any single tool result beyond this
MAX_CONTEXT_MESSAGES = 30        # Sliding window cap per LLM call
EMPTY_RESPONSE_RETRIES = 1      # Retry count when LLM returns empty


class AgentLoop:
    """
    The agent loop is the core processing engine.
    
    It:
    1. Receives messages from the bus
    2. Builds context with history, memory, skills
    3. Calls the LLM
    4. Executes tool calls
    5. Sends responses back
    """
    
    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 20,
        brave_api_key: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        cron_service: "CronService | None" = None,
        restrict_to_workspace: bool = False,
    ):
        from nanobot.config.schema import ExecToolConfig
        from nanobot.cron.service import CronService
        self.bus = bus
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        self.restrict_to_workspace = restrict_to_workspace
        
        self.context = ContextBuilder(workspace)
        self.sessions = SessionManager(workspace)
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            brave_api_key=brave_api_key,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
        )
        
        self._running = False
        self._chat_locks: dict[str, asyncio.Lock] = {}
        self._register_default_tools()

    # ----- Context window helpers -----

    @staticmethod
    def _truncate_tool_result(result: str) -> str:
        """Truncate a single tool result to keep context lean.

        Strips ANSI escape codes, then caps total length.  Leaves a clear
        note so the LLM knows data was trimmed (and doesn't retry the same
        tool to "see the rest").
        """
        # Strip ANSI escape sequences
        clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', result)

        if len(clean) <= MAX_TOOL_RESULT_CHARS:
            return clean

        half = MAX_TOOL_RESULT_CHARS // 2
        return (
            clean[:half]
            + f"\n\n... [truncated {len(clean) - MAX_TOOL_RESULT_CHARS} chars — "
            + "data omitted to save context, do NOT re-run this tool to see more] ...\n\n"
            + clean[-half:]
        )

    @staticmethod
    def _compact_context(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Sliding-window prune that never orphans tool-call / tool-result pairs.

        Keeps:
          • messages[0]  — system prompt  (always)
          • messages[1]  — first user msg (the goal)
          • tail slice   — most recent messages, but never splits an
                           assistant(tool_calls) from its tool results.
        """
        if len(messages) <= MAX_CONTEXT_MESSAGES:
            return messages

        # Always keep system prompt + first user message (the goal)
        protected = messages[:2]
        remaining = messages[2:]

        budget = MAX_CONTEXT_MESSAGES - len(protected)
        if budget <= 0:
            return protected

        # Take from the end, but if we'd start mid-way through a
        # tool-result block, walk backwards to include the assistant msg
        # that triggered it.
        tail = remaining[-budget:]

        # If first message in tail is a tool result, it's orphaned —
        # drop orphaned tool results from the front of the tail.
        while tail and tail[0].get("role") == "tool":
            tail = tail[1:]

        result = protected + tail
        logger.debug(f"Context compacted: {len(messages)} → {len(result)} messages")
        return result

    def _get_chat_lock(self, key: str) -> asyncio.Lock:
        """Per-chat lock to prevent concurrent message corruption."""
        if key not in self._chat_locks:
            self._chat_locks[key] = asyncio.Lock()
        return self._chat_locks[key]
    
    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        # File tools (restrict to workspace if configured)
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        self.tools.register(ReadFileTool(allowed_dir=allowed_dir))
        self.tools.register(WriteFileTool(allowed_dir=allowed_dir))
        self.tools.register(EditFileTool(allowed_dir=allowed_dir))
        self.tools.register(ListDirTool(allowed_dir=allowed_dir))
        
        # Shell tool
        self.tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            restrict_to_workspace=self.restrict_to_workspace,
        ))
        
        # Web tools
        self.tools.register(WebSearchTool(api_key=self.brave_api_key))
        self.tools.register(WebFetchTool())
        
        # Message tool
        message_tool = MessageTool(send_callback=self.bus.publish_outbound)
        self.tools.register(message_tool)
        
        # Spawn tool (for subagents)
        spawn_tool = SpawnTool(manager=self.subagents)
        self.tools.register(spawn_tool)
        
        # Cron tool (for scheduling)
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))
    
    async def run(self) -> None:
        """Run the agent loop, processing messages from the bus."""
        self._running = True
        logger.info("Agent loop started")
        
        while self._running:
            try:
                # Wait for next message
                msg = await asyncio.wait_for(
                    self.bus.consume_inbound(),
                    timeout=1.0
                )
                
                # Process it
                try:
                    response = await self._process_message(msg)
                    if response:
                        await self.bus.publish_outbound(response)
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    # Send error response
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=f"Sorry, I encountered an error: {str(e)}"
                    ))
            except asyncio.TimeoutError:
                continue
    
    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        logger.info("Agent loop stopping")
    
    async def _process_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """
        Process a single inbound message.
        
        Args:
            msg: The inbound message to process.
        
        Returns:
            The response message, or None if no response needed.
        """
        # Handle system messages (subagent announces)
        if msg.channel == "system":
            return await self._process_system_message(msg)
        
        logger.info(f"Processing message from {msg.channel}:{msg.sender_id}")
        
        # Per-chat lock prevents concurrent corruption on same session
        async with self._get_chat_lock(msg.session_key):
            # Get or create session
            session = self.sessions.get_or_create(msg.session_key)
            
            # Update tool contexts
            message_tool = self.tools.get("message")
            if isinstance(message_tool, MessageTool):
                message_tool.set_context(msg.channel, msg.chat_id)
            
            spawn_tool = self.tools.get("spawn")
            if isinstance(spawn_tool, SpawnTool):
                spawn_tool.set_context(msg.channel, msg.chat_id)
            
            cron_tool = self.tools.get("cron")
            if isinstance(cron_tool, CronTool):
                cron_tool.set_context(msg.channel, msg.chat_id)
            
            # Build initial messages
            messages = self.context.build_messages(
                history=session.get_history(),
                current_message=msg.content,
                media=msg.media if msg.media else None,
                channel=msg.channel,
                chat_id=msg.chat_id,
            )
            
            # Agent loop
            iteration = 0
            final_content = None
            
            while iteration < self.max_iterations:
                iteration += 1
                
                # Compact context BEFORE each LLM call (prevents explosion)
                messages = self._compact_context(messages)
                
                # Call LLM
                response = await self.provider.chat(
                    messages=messages,
                    tools=self.tools.get_definitions(),
                    model=self.model
                )
                
                # Handle tool calls
                if response.has_tool_calls:
                    tool_call_dicts = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments)
                            }
                        }
                        for tc in response.tool_calls
                    ]
                    messages = self.context.add_assistant_message(
                        messages, response.content, tool_call_dicts
                    )
                    
                    # Execute tools — truncate results at source
                    for tool_call in response.tool_calls:
                        args_str = json.dumps(tool_call.arguments)
                        logger.debug(f"Executing tool: {tool_call.name} with arguments: {args_str}")
                        raw_result = await self.tools.execute(tool_call.name, tool_call.arguments)
                        result = self._truncate_tool_result(raw_result)
                        messages = self.context.add_tool_result(
                            messages, tool_call.id, tool_call.name, result
                        )
                else:
                    # Got a response — but guard against empty/None
                    if response.content:
                        final_content = response.content
                        break
                    
                    # LLM returned empty: retry once before giving up
                    if iteration <= self.max_iterations - EMPTY_RESPONSE_RETRIES:
                        logger.warning(f"LLM returned empty on iteration {iteration}, retrying")
                        continue
                    
                    final_content = None
                    break
            
            if final_content is None:
                final_content = "I've completed processing but have no response to give."
            
            # Save to session (safe — disk errors don't crash the agent)
            try:
                session.add_message("user", msg.content)
                session.add_message("assistant", final_content)
                self.sessions.save(session)
            except Exception as e:
                logger.error(f"Failed to save session {msg.session_key}: {e}")
            
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=final_content
            )
    
    async def _process_system_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """
        Process a system message (e.g., subagent announce).
        
        The chat_id field contains "original_channel:original_chat_id" to route
        the response back to the correct destination.
        """
        logger.info(f"Processing system message from {msg.sender_id}")
        
        # Parse origin from chat_id (format: "channel:chat_id")
        if ":" in msg.chat_id:
            parts = msg.chat_id.split(":", 1)
            origin_channel = parts[0]
            origin_chat_id = parts[1]
        else:
            # Fallback
            origin_channel = "cli"
            origin_chat_id = msg.chat_id
        
        # Use the origin session for context
        session_key = f"{origin_channel}:{origin_chat_id}"
        session = self.sessions.get_or_create(session_key)
        
        # Update tool contexts
        message_tool = self.tools.get("message")
        if isinstance(message_tool, MessageTool):
            message_tool.set_context(origin_channel, origin_chat_id)
        
        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(origin_channel, origin_chat_id)
        
        cron_tool = self.tools.get("cron")
        if isinstance(cron_tool, CronTool):
            cron_tool.set_context(origin_channel, origin_chat_id)
        
        # Build messages with the announce content
        messages = self.context.build_messages(
            history=session.get_history(),
            current_message=msg.content,
            channel=origin_channel,
            chat_id=origin_chat_id,
        )
        
        # Agent loop (limited for announce handling)
        iteration = 0
        final_content = None
        
        while iteration < self.max_iterations:
            iteration += 1

            # Compact context before each LLM call
            messages = self._compact_context(messages)
            
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model
            )
            
            if response.has_tool_calls:
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments)
                        }
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts
                )
                
                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments)
                    logger.debug(f"Executing tool: {tool_call.name} with arguments: {args_str}")
                    raw_result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    result = self._truncate_tool_result(raw_result)
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                if response.content:
                    final_content = response.content
                    break

                if iteration <= self.max_iterations - EMPTY_RESPONSE_RETRIES:
                    logger.warning(f"LLM returned empty on iteration {iteration} (system), retrying")
                    continue

                final_content = None
                break
        
        if final_content is None:
            final_content = "Background task completed."
        
        # Save to session (safe — disk errors don't crash the agent)
        try:
            session.add_message("user", f"[System: {msg.sender_id}] {msg.content}")
            session.add_message("assistant", final_content)
            self.sessions.save(session)
        except Exception as e:
            logger.error(f"Failed to save session {session_key}: {e}")
        
        return OutboundMessage(
            channel=origin_channel,
            chat_id=origin_chat_id,
            content=final_content
        )
    
    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
    ) -> str:
        """
        Process a message directly (for CLI or cron usage).
        
        Args:
            content: The message content.
            session_key: Session identifier.
            channel: Source channel (for context).
            chat_id: Source chat ID (for context).
        
        Returns:
            The agent's response.
        """
        msg = InboundMessage(
            channel=channel,
            sender_id="user",
            chat_id=chat_id,
            content=content
        )
        
        response = await self._process_message(msg)
        return response.content if response else ""
