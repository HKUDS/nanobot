"""Agent loop: the core processing engine."""

import asyncio
import json
import random
import re
from collections import OrderedDict
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
EMPTY_RESPONSE_RETRIES = 1       # Retry count when LLM returns empty
MAX_CHAT_LOCKS = 256             # LRU cap on per-chat locks to prevent memory leak


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
        session_manager: SessionManager | None = None,
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
        self.sessions = session_manager or SessionManager(workspace)
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
        self._chat_locks: OrderedDict[str, asyncio.Lock] = OrderedDict()

    # ----- Context window helpers -----

    @staticmethod
    def _truncate_tool_result(result: str) -> str:
        """Truncate a single tool result to keep context lean.

        Strips ANSI escape codes, then applies content-type-aware truncation:
        - JSON strings are pretty-printed and prefix-truncated so the result
          is always valid JSON wrapped in a note, never a broken splice.
        - Plain text uses head truncation with a clear sentinel.

        The LLM always receives syntactically valid output.
        """
        # Strip ANSI escape sequences
        clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', result)

        if len(clean) <= MAX_TOOL_RESULT_CHARS:
            return clean

        # Detect JSON content and handle it specially
        stripped = clean.lstrip()
        if stripped and stripped[0] in ('{', '['):
            try:
                parsed = json.loads(clean)
                pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
                if len(pretty) <= MAX_TOOL_RESULT_CHARS:
                    return pretty
                # Prefix-truncate: keep the beginning of the pretty-printed
                # JSON and wrap in an explicit note so the LLM knows it's
                # incomplete but the visible portion is valid syntax.
                budget = MAX_TOOL_RESULT_CHARS - 120  # room for sentinel
                return (
                    pretty[:budget]
                    + f"\n\n... [JSON truncated — showed {budget} of {len(pretty)} chars. "
                    + "Content continues but was omitted to save context. "
                    + "Do NOT re-run this tool to see more.]"
                )
            except (json.JSONDecodeError, ValueError):
                pass  # Not valid JSON — fall through to plain-text path

        # Plain text: keep a generous head prefix with clear sentinel
        budget = MAX_TOOL_RESULT_CHARS - 100
        return (
            clean[:budget]
            + f"\n\n... [truncated — showed {budget} of {len(clean)} chars. "
            + "Do NOT re-run this tool to see more.]"
        )

    @staticmethod
    def _compact_context(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Sliding-window prune that never orphans tool-call / tool-result pairs.

        Groups messages into atomic blocks:
          • An assistant message with tool_calls + its subsequent tool results = 1 block
          • Any other single message = 1 block

        Keeps:
          • messages[0]  — system prompt  (always)
          • messages[1]  — first user msg / goal (always)
          • Most recent blocks that fit within MAX_CONTEXT_MESSAGES
        """
        if len(messages) <= MAX_CONTEXT_MESSAGES:
            return messages

        # Always keep system prompt + first user message (the goal)
        protected = messages[:2]
        remaining = messages[2:]

        # Group remaining into atomic blocks so we never split a
        # tool-call assistant message from its tool-result messages.
        blocks: list[list[dict[str, Any]]] = []
        i = 0
        while i < len(remaining):
            msg = remaining[i]
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                # Collect this assistant + all following tool results
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

        # Take blocks from the end until we exhaust the budget
        budget = MAX_CONTEXT_MESSAGES - len(protected)
        kept_blocks: list[list[dict[str, Any]]] = []
        total = 0
        for block in reversed(blocks):
            if total + len(block) > budget:
                break
            kept_blocks.append(block)
            total += len(block)

        kept_blocks.reverse()
        tail = [m for block in kept_blocks for m in block]
        result = protected + tail
        logger.debug(f"Context compacted: {len(messages)} → {len(result)} messages")
        return result

    def _get_chat_lock(self, key: str) -> asyncio.Lock:
        """Per-chat lock with LRU eviction to prevent unbounded memory."""
        if key in self._chat_locks:
            # Move to end (most-recently-used)
            self._chat_locks.move_to_end(key)
            return self._chat_locks[key]

        # Evict oldest entries that are not currently held
        while len(self._chat_locks) >= MAX_CHAT_LOCKS:
            oldest_key, oldest_lock = next(iter(self._chat_locks.items()))
            if oldest_lock.locked():
                # Don't evict an actively held lock — move to end and try next
                self._chat_locks.move_to_end(oldest_key)
                # Safety: if ALL locks are held, allow growing past cap
                if all(lk.locked() for lk in self._chat_locks.values()):
                    break
                continue
            del self._chat_locks[oldest_key]

        lock = asyncio.Lock()
        self._chat_locks[key] = lock
        return lock
    
    def _make_session_tools(self, channel: str, chat_id: str) -> ToolRegistry:
        """Create an isolated ToolRegistry for one session/request.

        Each call returns fresh tool instances whose mutable context
        (channel / chat_id) is bound at creation time.  This eliminates
        the race where concurrent sessions overwrite each other's
        context on shared tool singletons.
        """
        tools = ToolRegistry()

        # File tools (restrict to workspace if configured)
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        tools.register(ReadFileTool(allowed_dir=allowed_dir))
        tools.register(WriteFileTool(allowed_dir=allowed_dir))
        tools.register(EditFileTool(allowed_dir=allowed_dir))
        tools.register(ListDirTool(allowed_dir=allowed_dir))

        # Shell tool
        tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            restrict_to_workspace=self.restrict_to_workspace,
        ))

        # Web tools
        tools.register(WebSearchTool(api_key=self.brave_api_key))
        tools.register(WebFetchTool())

        # Message tool — bound to this session's channel/chat_id
        message_tool = MessageTool(
            send_callback=self.bus.publish_outbound,
            default_channel=channel,
            default_chat_id=chat_id,
        )
        tools.register(message_tool)

        # Spawn tool — bound to this session's channel/chat_id
        spawn_tool = SpawnTool(manager=self.subagents)
        spawn_tool.set_context(channel, chat_id)
        tools.register(spawn_tool)

        # Cron tool — bound to this session's channel/chat_id
        if self.cron_service:
            cron_tool = CronTool(self.cron_service)
            cron_tool.set_context(channel, chat_id)
            tools.register(cron_tool)

        return tools
    
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
        
        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info(f"Processing message from {msg.channel}:{msg.sender_id}: {preview}")
        
        # Per-chat lock prevents concurrent corruption on same session
        async with self._get_chat_lock(msg.session_key):
            # Get or create session
            session = self.sessions.get_or_create(msg.session_key)

            # Create isolated tool instances for this session so
            # concurrent sessions never overwrite each other's context.
            tools = self._make_session_tools(msg.channel, msg.chat_id)
            
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
            empty_retries_left = EMPTY_RESPONSE_RETRIES
            final_content = None
            
            while iteration < self.max_iterations:
                iteration += 1
                
                # Compact context BEFORE each LLM call (prevents explosion)
                messages = self._compact_context(messages)
                
                # Call LLM
                response = await self.provider.chat(
                    messages=messages,
                    tools=tools.get_definitions(),
                    model=self.model
                )
                
                # Detect LLM errors returned as content
                if (response.finish_reason == "error"
                        or (response.content and response.content.startswith("Error calling LLM:"))):
                    logger.error(f"LLM error on iteration {iteration}: {response.content}")
                    final_content = "Sorry, I encountered a temporary issue. Please try again."
                    break
                
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
                        raw_result = await tools.execute(tool_call.name, tool_call.arguments)
                        result = self._truncate_tool_result(raw_result)
                        messages = self.context.add_tool_result(
                            messages, tool_call.id, tool_call.name, result
                        )
                else:
                    # Got a response — but guard against empty/None
                    if response.content:
                        final_content = response.content
                        break
                    
                    # LLM returned empty: retry with exponential backoff + jitter
                    if empty_retries_left > 0:
                        empty_retries_left -= 1
                        retry_num = EMPTY_RESPONSE_RETRIES - empty_retries_left
                        delay = min(2 ** retry_num + random.uniform(0, 1), 10.0)
                        logger.warning(
                            f"LLM returned empty on iteration {iteration}, "
                            f"retries left: {empty_retries_left}, backing off {delay:.1f}s"
                        )
                        await asyncio.sleep(delay)
                        continue
                    
                    logger.warning(f"LLM returned empty, no retries left — giving up")
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
        
        # Use the origin session for context — must be under the same lock
        # as regular messages to prevent session corruption.
        session_key = f"{origin_channel}:{origin_chat_id}"

        async with self._get_chat_lock(session_key):
            session = self.sessions.get_or_create(session_key)

            # Create isolated tool instances for this session
            tools = self._make_session_tools(origin_channel, origin_chat_id)
            
            # Build messages with the announce content
            messages = self.context.build_messages(
                history=session.get_history(),
                current_message=msg.content,
                channel=origin_channel,
                chat_id=origin_chat_id,
            )
            
            # Agent loop (limited for announce handling)
            iteration = 0
            empty_retries_left = EMPTY_RESPONSE_RETRIES
            final_content = None
            
            while iteration < self.max_iterations:
                iteration += 1

                # Compact context before each LLM call
                messages = self._compact_context(messages)
                
                response = await self.provider.chat(
                    messages=messages,
                    tools=tools.get_definitions(),
                    model=self.model
                )
                
                # Detect LLM errors
                if (response.finish_reason == "error"
                        or (response.content and response.content.startswith("Error calling LLM:"))):
                    logger.error(f"LLM error on iteration {iteration} (system): {response.content}")
                    final_content = "Background task completed."
                    break
                
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
                        raw_result = await tools.execute(tool_call.name, tool_call.arguments)
                        result = self._truncate_tool_result(raw_result)
                        messages = self.context.add_tool_result(
                            messages, tool_call.id, tool_call.name, result
                        )
                else:
                    if response.content:
                        final_content = response.content
                        break

                    # Exponential backoff + jitter on empty response
                    if empty_retries_left > 0:
                        empty_retries_left -= 1
                        retry_num = EMPTY_RESPONSE_RETRIES - empty_retries_left
                        delay = min(2 ** retry_num + random.uniform(0, 1), 10.0)
                        logger.warning(
                            f"LLM returned empty on iteration {iteration} (system), "
                            f"retries left: {empty_retries_left}, backing off {delay:.1f}s"
                        )
                        await asyncio.sleep(delay)
                        continue

                    logger.warning("LLM returned empty (system), no retries left — giving up")
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
