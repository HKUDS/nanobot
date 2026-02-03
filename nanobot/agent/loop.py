"""Agent loop: the core processing engine."""

import asyncio
import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

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
from nanobot.agent.subagent import SubagentManager
from nanobot.agent.compaction import ContextCompactor, estimate_messages_tokens
from nanobot.session.manager import SessionManager
from nanobot.agent.soul import SoulLoader
from nanobot.agent.mem0_memory import Mem0MemoryStore, Mem0Config

if TYPE_CHECKING:
    from nanobot.config.schema import SoulConfig


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
        max_context_tokens: int = 128000,
        enable_compaction: bool = True,
        hindsight_url: str | None = None,
        soul_config: "SoulConfig | None" = None,
        mem0_config: "Mem0Config | None" = None,
    ):
        self.bus = bus
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.brave_api_key = brave_api_key
        self.max_context_tokens = max_context_tokens
        self.enable_compaction = enable_compaction
        
        # Soul loader for personality/memory
        self._soul_loader: SoulLoader | None = None
        if soul_config and soul_config.enabled:
            self._soul_loader = SoulLoader(soul_config)
            logger.info(f"Soul loader enabled: {soul_config.path}")
        
        # mem0 semantic memory
        self._mem0: Mem0MemoryStore | None = None
        if mem0_config and mem0_config.enabled:
            self._mem0 = Mem0MemoryStore(
                config=mem0_config,
                workspace=workspace,
                user_id="default",
            )
            if self._mem0.available:
                logger.info("mem0 semantic memory enabled")
        
        self.context = ContextBuilder(workspace)
        self.sessions = SessionManager(workspace)
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            brave_api_key=brave_api_key,
        )
        
        # Context compactor for long conversations
        self._compactors: dict[str, ContextCompactor] = {}
        
        # Hindsight memory (optional)
        self._memory = None
        if hindsight_url:
            try:
                from nanobot.agent.hindsight_memory import HindsightMemoryStore
                self._memory = HindsightMemoryStore(
                    workspace=workspace,
                    base_url=hindsight_url,
                )
                logger.info(f"Hindsight memory enabled: {hindsight_url}")
            except Exception as e:
                logger.warning(f"Failed to initialize Hindsight: {e}")
        
        self._running = False
        self._register_default_tools()
    
    def _get_compactor(self, session_key: str) -> ContextCompactor:
        """Get or create a context compactor for a session."""
        if session_key not in self._compactors:
            self._compactors[session_key] = ContextCompactor(
                provider=self.provider,
                max_context_tokens=self.max_context_tokens,
                model=self.model,
            )
        return self._compactors[session_key]
    
    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        # File tools
        self.tools.register(ReadFileTool())
        self.tools.register(WriteFileTool())
        self.tools.register(EditFileTool())
        self.tools.register(ListDirTool())
        
        # Shell tool
        self.tools.register(ExecTool(working_dir=str(self.workspace)))
        
        # Web tools
        self.tools.register(WebSearchTool(api_key=self.brave_api_key))
        self.tools.register(WebFetchTool())
        
        # Message tool
        message_tool = MessageTool(send_callback=self.bus.publish_outbound)
        self.tools.register(message_tool)
        
        # Spawn tool (for subagents)
        spawn_tool = SpawnTool(manager=self.subagents)
        self.tools.register(spawn_tool)
    
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
        # The chat_id contains the original "channel:chat_id" to route back to
        if msg.channel == "system":
            return await self._process_system_message(msg)
        
        logger.info(f"Processing message from {msg.channel}:{msg.sender_id}")
        
        # Get or create session
        session = self.sessions.get_or_create(msg.session_key)
        
        # Update tool contexts
        message_tool = self.tools.get("message")
        if isinstance(message_tool, MessageTool):
            message_tool.set_context(msg.channel, msg.chat_id)
        
        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(msg.channel, msg.chat_id)
        
        # Load soul content if enabled
        if self._soul_loader:
            soul_content = self._soul_loader.load(
                channel=msg.channel,
                model=self.model,
                session_key=msg.session_key,
            )
            self.context.set_soul_content(soul_content)
        
        # Build initial messages (use get_history for LLM-formatted messages)
        messages = self.context.build_messages(
            history=session.get_history(),
            current_message=msg.content,
            media=msg.media if msg.media else None,
        )
        
        # Apply compaction if enabled
        if self.enable_compaction:
            compactor = self._get_compactor(msg.session_key)
            
            # Check if we need to compact
            current_tokens = estimate_messages_tokens(messages)
            budget = int(self.max_context_tokens * 0.7)  # Leave room for response
            
            if current_tokens > budget:
                logger.info(f"Compacting context: {current_tokens} tokens > {budget} budget")
                messages = await compactor.maybe_compact(messages)
                
                # Inject summary into system prompt if available
                summary_prompt = compactor.get_summary_prompt()
                if summary_prompt and messages and messages[0].get("role") == "system":
                    messages[0]["content"] += summary_prompt
        
        # Recall relevant memories from Hindsight (if available)
        if self._memory:
            try:
                memory_context = await self._memory.recall_for_context(msg.content)
                if memory_context and messages and messages[0].get("role") == "system":
                    messages[0]["content"] += f"\n\n{memory_context}"
            except Exception as e:
                logger.debug(f"Memory recall failed: {e}")
        
        # Recall relevant memories from mem0 (if available)
        if self._mem0 and self._mem0.available:
            try:
                mem0_context = await self._mem0.recall_for_context(msg.content, user_id=msg.sender_id)
                if mem0_context and messages and messages[0].get("role") == "system":
                    messages[0]["content"] += f"\n\n{mem0_context}"
                    logger.debug(f"mem0 recalled memories for context")
            except Exception as e:
                logger.debug(f"mem0 recall failed: {e}")
        
        # Agent loop
        iteration = 0
        final_content = None
        
        while iteration < self.max_iterations:
            iteration += 1
            
            # Call LLM
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model
            )
            
            # Handle tool calls
            if response.has_tool_calls:
                # Add assistant message with tool calls
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments)  # Must be JSON string
                        }
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts
                )
                
                # Execute tools
                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments)
                    logger.debug(f"Executing tool: {tool_call.name} with arguments: {args_str}")
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                # No tool calls, we're done
                final_content = response.content
                break
        
        if final_content is None:
            final_content = "I've completed processing but have no response to give."
        
        # Save to session
        session.add_message("user", msg.content)
        session.add_message("assistant", final_content)
        self.sessions.save(session)
        
        # Store important memories (async, don't wait)
        if self._memory:
            asyncio.create_task(self._memory.process_message({"role": "user", "content": msg.content}))
            asyncio.create_task(self._memory.process_message({"role": "assistant", "content": final_content}))
        
        # Store memories in mem0 (async, don't wait)
        if self._mem0 and self._mem0.available:
            conversation = [
                {"role": "user", "content": msg.content},
                {"role": "assistant", "content": final_content}
            ]
            asyncio.create_task(self._mem0.add_from_conversation(conversation, user_id=msg.sender_id))
        
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
        
        # Build messages with the announce content
        messages = self.context.build_messages(
            history=session.get_history(),
            current_message=msg.content
        )
        
        # Agent loop (limited for announce handling)
        iteration = 0
        final_content = None
        
        while iteration < self.max_iterations:
            iteration += 1
            
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
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                final_content = response.content
                break
        
        if final_content is None:
            final_content = "Background task completed."
        
        # Save to session (mark as system message in history)
        session.add_message("user", f"[System: {msg.sender_id}] {msg.content}")
        session.add_message("assistant", final_content)
        self.sessions.save(session)
        
        return OutboundMessage(
            channel=origin_channel,
            chat_id=origin_chat_id,
            content=final_content
        )
    
    async def process_direct(self, content: str, session_key: str = "cli:direct") -> str:
        """
        Process a message directly (for CLI usage).
        
        Args:
            content: The message content.
            session_key: Session identifier.
        
        Returns:
            The agent's response.
        """
        msg = InboundMessage(
            channel="cli",
            sender_id="user",
            chat_id="direct",
            content=content
        )
        
        response = await self._process_message(msg)
        return response.content if response else ""
