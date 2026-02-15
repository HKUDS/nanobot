"""Agent loop: the core processing engine."""

import asyncio
import json
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
from nanobot.agent.memory import MemoryStore
from nanobot.agent.tools.gateway import RestartGatewayTool
from nanobot.agent.tools.ipython import IPythonTool
from nanobot.agent.tools.models import ChangeModelTool, ListModelsTool, TestModelTool, AddModelTool
from nanobot.agent.tools.context import ClearContextTool, CompactContextTool
from nanobot.agent.job_tracker import job_manager, ToolCallStatus
from nanobot.agent.subagent import SubagentManager
from nanobot.session.manager import SessionManager
from nanobot.system.hooks import hook_manager
from nanobot.agent.qol import QOLManager
from nanobot.config.schema import ExecToolConfig
from nanobot.cron.service import CronService
from contextlib import AsyncExitStack
from nanobot.agent.tools.thread import CreateThreadTool, ListThreadsTool
from nanobot.agent.tools.topics import CreateTopicTool, SwitchTopicTool, ListTopicsTool, DeleteTopicTool, CurrentTopicTool, _load_topics
import json_repair



# Type imports for forward references
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
        temperature: float = 0.7,
        max_tokens: int = 4096,
        memory_window: int = 50,
        brave_api_key: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        cron_service: "CronService | None" = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
    ):
        from nanobot.config.schema import ExecToolConfig
        from nanobot.cron.service import CronService
        self.bus = bus
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.memory_window = memory_window
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        self.restrict_to_workspace = restrict_to_workspace
        
        self.context = ContextBuilder(workspace)
        self.sessions = session_manager or SessionManager(workspace)
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
        )
        
        self._running = False
        self._mcp_servers = mcp_servers or {}
        self._mcp_stack: AsyncExitStack | None = None
        self._mcp_connected = False
        # QOL manager for Telegram QOL features
        self.qol = QOLManager(self)
        # Reference to Telegram channel for thread creation (set by gateway)
        self._telegram_channel = None
        self._register_default_tools()
    
    def _get_threads_list_callback(self):
        """Get a callback for listing threads from the Telegram channel."""
        async def list_threads(chat_id: int) -> dict:
            if not self._telegram_channel:
                return {"threads": {}}
            # Return the tracked thread info
            return {"threads": self._telegram_channel._thread_info}
        return list_threads
    
    def _get_topic_aware_session_key(self, base_session_key: str) -> str:
        """
        Get session key with current topic suffix if a topic is active.
        
        Args:
            base_session_key: The base session key (e.g., "telegram:343792907")
        
        Returns:
            Session key with topic suffix if active (e.g., "telegram:343792907:work")
        """
        try:
            data = _load_topics(base_session_key)
            current_topic = data.get("current_topic")
            if current_topic:
                # Remove existing topic suffix first
                parts = base_session_key.split(":")
                if len(parts) >= 2:
                    base = f"{parts[0]}:{parts[1]}"
                else:
                    base = base_session_key
                return f"{base}:{current_topic}"
        except Exception as e:
            logger.debug(f"Error loading topics: {e}")
        return base_session_key
    
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
        self.tools.register(WebSearchTool())
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

        # Gateway restart tool
        self.tools.register(RestartGatewayTool())

        # IPython tool (stateful Python execution)
        # Using subprocess mode for true isolation to prevent async context corruption
        self.tools.register(IPythonTool(
            working_dir=str(self.workspace),
            timeout=60,
            restrict_to_workspace=self.restrict_to_workspace,
            message_callback=self.bus.publish_outbound,
            mode="subprocess",  # Subprocess mode prevents async context corruption
            tool_registry=self.tools,  # Pass tool registry so IPython can access all tools
        ))

        # Model management tools
        self.tools.register(ChangeModelTool(self))
        self.tools.register(ListModelsTool(agent=self))
        self.tools.register(TestModelTool(self))
        self.tools.register(AddModelTool())

        # Context management tools
        self.tools.register(ClearContextTool(self))
        self.tools.register(CompactContextTool(self))
        
        # Thread management tools (for Telegram forum topics)
        self.tools.register(CreateThreadTool())
        self.tools.register(ListThreadsTool())
        
        # Topic management tools (for context switching within a single chat)
        self.tools.register(CreateTopicTool())
        self.tools.register(SwitchTopicTool())
        self.tools.register(ListTopicsTool())
        self.tools.register(DeleteTopicTool())
        self.tools.register(CurrentTopicTool())
    
    def _queue_message(self, session_key: str, message: str) -> None:
        """Queue a message for a session that's currently being processed."""
        self.qol.queue_message(session_key, message)
    
    def _get_and_clear_pending_messages(self, session_key: str) -> list[str]:
        """Get and clear pending messages for a session."""
        return self.qol.get_and_clear_pending_messages(session_key)
    
    def _is_processing(self, session_key: str) -> bool:
        """Check if a session is currently being processed."""
        return self.qol.is_processing(session_key)
    
    async def _connect_mcp(self) -> None:
        """Connect to configured MCP servers (one-time, lazy)."""
        if self._mcp_connected or not self._mcp_servers:
            return
        self._mcp_connected = True
        from nanobot.agent.tools.mcp import connect_mcp_servers
        self._mcp_stack = AsyncExitStack()
        await self._mcp_stack.__aenter__()
        await connect_mcp_servers(self._mcp_servers, self.tools, self._mcp_stack)

    def _set_tool_context(self, channel: str, chat_id: str) -> None:
        """Update context for all tools that need routing info."""
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.set_context(channel, chat_id)

        if spawn_tool := self.tools.get("spawn"):
            if isinstance(spawn_tool, SpawnTool):
                spawn_tool.set_context(channel, chat_id)

        if cron_tool := self.tools.get("cron"):
            if isinstance(cron_tool, CronTool):
                cron_tool.set_context(channel, chat_id)

    async def _run_agent_loop(self, initial_messages: list[dict]) -> tuple[str | None, list[str]]:
        """
        Run the agent iteration loop.

        Args:
            initial_messages: Starting messages for the LLM conversation.

        Returns:
            Tuple of (final_content, list_of_tools_used).
        """
        messages = initial_messages
        iteration = 0
        final_content = None
        tools_used: list[str] = []

        while iteration < self.max_iterations:
            iteration += 1

            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
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
                    messages, response.content, tool_call_dicts,
                    reasoning_content=response.reasoning_content,
                )

                for tool_call in response.tool_calls:
                    tools_used.append(tool_call.name)
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    logger.info(f"Tool call: {tool_call.name}({args_str[:200]})")
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
                messages.append({"role": "user", "content": "Reflect on the results and decide next steps."})
            else:
                final_content = response.content
                break

        return final_content, tools_used

    async def run(self) -> None:
        """Run the agent loop, processing messages from the bus."""
        self._running = True
        await self._connect_mcp()
        logger.info("Agent loop started")
        
        while self._running:
            try:
                # Wait for next message
                msg = await asyncio.wait_for(
                    self.bus.consume_inbound(),
                    timeout=1.0
                )
                
                # Check if this session is already being processed
                session_key = msg.session_key
                if self._is_processing(session_key):
                    # Queue the message to be processed after current operation
                    self._queue_message(session_key, msg.content)
                    logger.info(f"Session {session_key} is busy, queued message")
                    continue
                
                # Process it
                try:
                    self.qol.start_processing(session_key)
                    response = await self._process_message(msg)
                    if response:
                        await self.bus.publish_outbound(response)
                except Exception as e:
                    import traceback
                    logger.error(f"Error processing message: {e}")
                    logger.error(traceback.format_exc())
                    
                    # Try to fail job if possible
                    job_id = msg.metadata.get("job_id")
                    if job_id:
                        try:
                            await job_manager.fail_job(job_id, str(e))
                        except Exception as fail_error:
                            logger.warning(f"Failed to mark job {job_id} as failed: {fail_error}")
                    
                    # Send error response
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=f"Sorry, I encountered an error: {str(e)}"
                    ))

                finally:
                    # Always remove from processing set when done
                    self.qol.finish_processing(session_key)
            except asyncio.TimeoutError:
                # Timeout is normal when no messages are waiting, but log periodically for debugging
                logger.debug("Agent loop timeout - no messages waiting")
                continue
            except Exception as e:
                # Catch-all for unexpected errors to prevent the loop from crashing
                import traceback
                logger.error(f"Unexpected error in agent loop: {e}")
                logger.error(traceback.format_exc())
                # Brief pause before continuing to avoid rapid error loops
                await asyncio.sleep(1)
    
    async def close_mcp(self) -> None:
        """Close MCP connections."""
        if self._mcp_stack:
            try:
                await self._mcp_stack.aclose()
            except (RuntimeError, BaseExceptionGroup):
                pass  # MCP SDK cancel scope cleanup is noisy but harmless
            self._mcp_stack = None

    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        logger.info("Agent loop stopping")
    
    async def _process_message(self, msg: InboundMessage, session_key: str | None = None) -> OutboundMessage | None:
        """
        Process a single inbound message.
        
        Args:
            msg: The inbound message to process.
            session_key: Override session key (used by process_direct).
        
        Returns:
            The response message, or None if no response needed.
        """
        # Handle system messages (subagent announces)
        # The chat_id contains the original "channel:chat_id" to route back to
        if msg.channel == "system":
            return await self._process_system_message(msg)
        
        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info(f"Processing message from {msg.channel}:{msg.sender_id}: {preview}")
        
        # Get job_id from metadata if available
        job_id = msg.metadata.get("job_id")
        
        # Get or create session (with topic awareness)
        # First check if there's a current topic for this session
        base_key = session_key or msg.session_key
        key = self._get_topic_aware_session_key(base_key)
        session = self.sessions.get_or_create(key)
        
        # Handle slash commands
        cmd = msg.content.strip().lower()
        if cmd == "/new":
            await self._consolidate_memory(session, archive_all=True)
            session.clear()
            self.sessions.save(session)
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content="🐈 New session started. Memory consolidated.")
        if cmd == "/help":
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content="🐈 nanobot commands:\n/new — Start a new conversation\n/help — Show available commands\n\n📁 Topic commands:\n/topic create <name> — Create a new topic\n/topic switch <name> — Switch to a topic\n/topic list — List all topics\n/topic current — Show current topic\n/topic delete <name> — Delete a topic")
        
        # Handle topic commands
        if cmd.startswith("/topic"):
            return await self._handle_topic_command(msg, cmd)
        
        # Consolidate memory before processing if session is too large
        if len(session.messages) > self.memory_window:
            await self._consolidate_memory(session, job_id=job_id)
        
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
        
        ipython_tool = self.tools.get("ipython")
        if isinstance(ipython_tool, IPythonTool):
            ipython_tool.set_context(msg.channel, msg.chat_id)
        
        # Thread tools need context for creating threads in the right chat
        # Also set the callback if we have access to the Telegram channel
        create_thread_tool = self.tools.get("create_thread")
        if isinstance(create_thread_tool, CreateThreadTool):
            create_thread_tool.set_context(msg.channel, msg.chat_id)
            # Set callback if not already set and we have channel access
            if not create_thread_tool.create_callback and hasattr(self, '_telegram_channel') and self._telegram_channel:
                create_thread_tool.set_callback(self._telegram_channel.create_forum_topic)
        
        list_threads_tool = self.tools.get("list_threads")
        if isinstance(list_threads_tool, ListThreadsTool):
            list_threads_tool.set_context(msg.channel, msg.chat_id)
            if not list_threads_tool.list_callback and hasattr(self, '_telegram_channel') and self._telegram_channel:
                list_threads_tool.list_callback = self._get_threads_list_callback()
        
        # Build initial messages (use get_history for LLM-formatted messages)
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
        tools_used: list[str] = []
        llm_call_record = None
        
        while iteration < self.max_iterations:
            iteration += 1
            
            # Check for abort
            if job_id:
                job = await job_manager.get_job(job_id)
                if job and job.is_aborted:
                    logger.info(f"Job {job_id} was aborted, stopping processing")
                    return OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content="🛑 Job aborted by user.",
                        metadata={"job_id": job_id, "aborted": True}
                    )
            
            # Track LLM call in job
            if job_id:
                job = await job_manager.get_job(job_id)
                if job:
                    if not llm_call_record:
                        llm_call_record = await job_manager.job_add_tool_call(
                            job_id, "llm_call", {"model": self.model, "iteration": iteration}
                        )
                        if llm_call_record:
                            await hook_manager.emit("agent.tool.execute",
                                tool_name="llm_call",
                                tool_args=llm_call_record.arguments,
                                tool_id=llm_call_record.id,
                                channel=msg.channel,
                                chat_id=msg.chat_id,
                                status="start",
                                agent=self,
                                job_id=job_id
                            )
                        # Update timeline immediately to show thinking/LLM call is running
                        if job_id:
                            await hook_manager.emit("agent.timeline.update", job_id=job_id, channel=msg.channel, chat_id=msg.chat_id)
                    else:
                        # Update existing record for retry
                        llm_call_record.arguments["iteration"] = iteration
                        llm_call_record.arguments["retry"] = True
            
            # Call LLM
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model,
                temperature=self.temperature
            )

            # Capture thinking/reasoning content if available
            if response.thinking:
                logger.info(f"LLM thinking captured ({len(response.thinking)} chars)")
                await hook_manager.emit("agent.thinking",
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=response.thinking,
                    job_id=job_id
                )

            # Mark llm_call as SUCCESS (🟩) once LLM returns
            if job_id and llm_call_record:
                await job_manager.job_update_tool_call(job_id, llm_call_record.id, ToolCallStatus.SUCCESS)
                
                # Emit hook to update timeline
                await hook_manager.emit("agent.tool.execute",
                        tool_name="llm_call",
                        tool_args=llm_call_record.arguments,
                        tool_id=llm_call_record.id,
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        status="end",
                        agent=self,
                        job_id=job_id
                    )
            
            # Handle tool calls
            if response.has_tool_calls:
                # If LLM provided content along with tool calls, send it to user immediately
                if response.content and response.content.strip():
                    logger.info(f"LLM provided intermediate message: {response.content[:100]}...")
                    # Send the intermediate message via the bus
                    intermediate_msg = OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=response.content,
                        metadata={
                            "job_id": job_id,
                            "intermediate": True,
                        },
                    )
                    try:
                        # Emit hook BEFORE sending so plugin can prepare
                        await hook_manager.emit("agent.response.text",
                            channel=msg.channel,
                            chat_id=msg.chat_id,
                            content=response.content,
                            is_final=False,
                            job_id=job_id
                        )
                        await self.bus.publish_outbound(intermediate_msg)
                        logger.info("Intermediate message sent successfully")
                        
                        # CRITICAL: Persist intermediate message to session immediately
                        # This ensures context is not lost if gateway restarts
                        session.add_message("assistant", response.content, intermediate=True)
                        self.sessions.save(session)
                        logger.debug(f"Persisted intermediate message to session {msg.session_key}")
                    except Exception as e:
                        logger.error(f"Failed to send intermediate message: {e}")

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
                
                # Execute tools with ability to inject user messages mid-operation
                for idx, tool_call in enumerate(response.tool_calls):
                    tools_used.append(tool_call.name)
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    logger.info(f"Tool call: {tool_call.name}({args_str[:200]})")
                    # NEW: Emit hook for tool execution
                    await hook_manager.emit("agent.tool.execute",
                        tool_name=tool_call.name,
                        tool_args=tool_call.arguments,
                        tool_id=tool_call.id,
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        status="start",
                        agent=self,
                        job_id=job_id
                    )

                    result = await self.tools.execute(
                        tool_call.name, tool_call.arguments,
                        channel=msg.channel, chat_id=msg.chat_id, job_id=job_id,
                        bus=self.bus, session_manager=self.sessions,
                        session_key=key,
                    )

                    # NEW: Emit hook for tool completion
                    await hook_manager.emit("agent.tool.execute",
                        tool_name=tool_call.name,
                        tool_args=tool_call.arguments,
                        tool_id=tool_call.id,
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        status="end",
                        result=result,
                        agent=self,
                        job_id=job_id
                    )
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
                    
                    # For certain tools, send result immediately to user
                    if tool_call.name in ["restart_gateway"]:
                        await self.bus.publish_outbound(OutboundMessage(
                            channel=msg.channel,
                            chat_id=msg.chat_id,
                            content=result,
                            metadata={"job_id": job_id} if job_id else {}
                        ))
                    
                    # Check for queued user messages after each tool execution
                    # This allows users to provide additional context mid-operation
                    # First, poll the bus for new messages from this session
                    queue_size = self.bus.inbound.qsize()
                    logger.debug(f"DEBUG: Checking bus queue after tool {tool_call.name}, size={queue_size}")
                    polled_count = 0
                    while queue_size > 0:
                        try:
                            pending_msg = await asyncio.wait_for(self.bus.inbound.get(), timeout=0.1)
                            polled_count += 1
                            logger.debug(f"DEBUG: Polled message from bus for session {pending_msg.session_key}, current session: {msg.session_key}")
                            if pending_msg.session_key == msg.session_key:
                                self._queue_message(pending_msg.session_key, pending_msg.content)
                                logger.info(f"DEBUG: Queued message for session {pending_msg.session_key}: {pending_msg.content[:50]}...")
                            else:
                                # Put it back for later processing
                                await self.bus.inbound.put(pending_msg)
                                logger.debug(f"DEBUG: Message for different session, put back in queue")
                                break
                            queue_size = self.bus.inbound.qsize()
                        except asyncio.TimeoutError:
                            logger.debug(f"DEBUG: Timeout polling bus queue")
                            break
                    
                    if polled_count > 0:
                        logger.info(f"DEBUG: Polled {polled_count} messages from bus")
                    
                    new_messages = self._get_and_clear_pending_messages(msg.session_key)
                    logger.debug(f"DEBUG: Pending messages for session {msg.session_key}: {len(new_messages)}")
                    if new_messages:
                        logger.info(f"DEBUG: Injecting {len(new_messages)} new user message(s) mid-operation")
                        for i, new_msg_content in enumerate(new_messages):
                            logger.info(f"DEBUG: Injecting message {i+1}/{len(new_messages)}: {new_msg_content[:100]}...")
                            messages.append({"role": "user", "content": new_msg_content})
                            session.add_message("user", new_msg_content)
                        # Break to let outer loop make a new LLM call with the new messages
                        # This allows the LLM to respond to user input mid-operation
                        logger.info(f"DEBUG: Breaking tool loop to re-call LLM with {len(new_messages)} injected messages")
                        break
            else:
                # No tool calls, we're done
                final_content = response.content
                break
        
        if final_content is None:
            if iteration >= self.max_iterations:
                final_content = f"Reached {self.max_iterations} iterations without completion."
            else:
                final_content = "I've completed processing but have no response to give."
        
        # Log response preview
        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info(f"Response to {msg.channel}:{msg.sender_id}: {preview}")
        
        # Save to session (include tool names so consolidation sees what happened)
        session.add_message("user", msg.content)
        session.add_message("assistant", final_content,
                            tools_used=tools_used if tools_used else None)
        self.sessions.save(session)
        
        # Update job completion
        if job_id:
            await job_manager.complete_job(job_id, final_content)

        # NEW: Emit hook for text response (replaces timeline)
        await hook_manager.emit("agent.response.text",
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content,
            is_final=True
        )
        
        # Merge metadata: pass through original (e.g. Slack thread_ts, Telegram thread_id) plus job info
        merged_metadata = dict(msg.metadata) if msg.metadata else {}
        merged_metadata.update({
            "job_id": job_id,
            "is_final": True
        })
        
        # Preserve thread_id for Telegram forum topics (routing responses to correct thread)
        if "thread_id" not in merged_metadata and msg.metadata and "thread_id" in msg.metadata:
            merged_metadata["thread_id"] = msg.metadata["thread_id"]

        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content,
            metadata=merged_metadata,
        )
    
    async def _handle_topic_command(self, msg: InboundMessage, cmd: str) -> OutboundMessage:
        """Handle /topic slash commands."""
        from nanobot.agent.tools.topics import _load_topics, _save_topics, _get_session_with_topic
        from datetime import datetime
        
        parts = cmd.split(maxsplit=2)
        base_key = f"{msg.channel}:{msg.chat_id}"
        
        if len(parts) == 1 or parts[1] == "list":
            # List topics
            data = _load_topics(base_key)
            topics = []
            for name, info in data.get("topics", {}).items():
                marker = "📌 " if name == data.get("current_topic") else "   "
                topics.append(f"{marker}{name}")
            
            if not topics:
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                      content="📁 No topics created yet.\nUse /topic create <name> to create one.")
            
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content=f"📁 Topics:\n" + "\n".join(topics))
        
        if parts[1] == "current":
            # Show current topic
            data = _load_topics(base_key)
            current = data.get("current_topic")
            if current:
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                      content=f"📌 Current topic: {current}")
            else:
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                      content="📁 No topic active (using default context)")
        
        if parts[1] == "create" and len(parts) >= 3:
            # Create topic
            name = parts[2].strip()
            if not name or len(name) > 64 or not all(c.isalnum() or c in "_-" for c in name):
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                      content="❌ Invalid topic name. Use 1-64 alphanumeric chars, underscores, or hyphens.")
            
            data = _load_topics(base_key)
            if name in data.get("topics", {}):
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                      content=f"❌ Topic '{name}' already exists")
            
            data.setdefault("topics", {})[name] = {
                "created_at": datetime.now().isoformat(),
                "last_used": datetime.now().isoformat(),
                "message_count": 0,
            }
            data["current_topic"] = name
            _save_topics(base_key, data)
            
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content=f"✅ Created and switched to topic '{name}'")
        
        if parts[1] == "switch" and len(parts) >= 3:
            # Switch topic
            name = parts[2].strip()
            data = _load_topics(base_key)
            
            if name not in data.get("topics", {}):
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                      content=f"❌ Topic '{name}' does not exist. Use /topic create {name} first.")
            
            data["topics"][name]["last_used"] = datetime.now().isoformat()
            data["current_topic"] = name
            _save_topics(base_key, data)
            
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content=f"📌 Switched to topic '{name}'")
        
        if parts[1] == "delete" and len(parts) >= 3:
            # Delete topic
            name = parts[2].strip()
            data = _load_topics(base_key)
            
            if name not in data.get("topics", {}):
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                      content=f"❌ Topic '{name}' does not exist")
            
            del data["topics"][name]
            if data.get("current_topic") == name:
                data["current_topic"] = None
            _save_topics(base_key, data)
            
            # Clear the session for this topic
            topic_session_key = _get_session_with_topic(base_key, name)
            session = self.sessions.get_or_create(topic_session_key)
            session.clear()
            self.sessions.save(session)
            
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content=f"🗑️ Deleted topic '{name}' and its history")
        
        # Unknown subcommand
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                              content="📁 Topic commands:\n/topic create <name>\n/topic switch <name>\n/topic list\n/topic current\n/topic delete <name>")
    
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
        
        ipython_tool = self.tools.get("ipython")
        if isinstance(ipython_tool, IPythonTool):
            ipython_tool.set_context(origin_channel, origin_chat_id)
        
        # Thread tools need context for creating threads in the right chat
        # Also set the callback if we have access to the Telegram channel
        create_thread_tool = self.tools.get("create_thread")
        if isinstance(create_thread_tool, CreateThreadTool):
            create_thread_tool.set_context(origin_channel, origin_chat_id)
            # Set callback if not already set and we have channel access
            if not create_thread_tool.create_callback and hasattr(self, '_telegram_channel') and self._telegram_channel:
                create_thread_tool.set_callback(self._telegram_channel.create_forum_topic)
        
        list_threads_tool = self.tools.get("list_threads")
        if isinstance(list_threads_tool, ListThreadsTool):
            list_threads_tool.set_context(origin_channel, origin_chat_id)
            if not list_threads_tool.list_callback and hasattr(self, '_telegram_channel') and self._telegram_channel:
                list_threads_tool.list_callback = self._get_threads_list_callback()
        
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
            
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model,
                temperature=self.temperature
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
                    messages, response.content, tool_call_dicts,
                    reasoning_content=response.reasoning_content,
                )
                
                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    logger.info(f"Tool call: {tool_call.name}({args_str[:200]})")
                    result = await self.tools.execute(
                        tool_call.name, tool_call.arguments,
                        channel=origin_channel, chat_id=origin_chat_id,
                        session_key=session_key,
                    )
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
                # Interleaved CoT: reflect before next action
                messages.append({"role": "user", "content": "Reflect on the results and decide next steps."})
            else:
                final_content = response.content
                break
        
        if final_content is None:
            final_content = "Background task completed."
        
        # Save to session (mark as system message in history)
        session.add_message("user", f"[System: {msg.sender_id}] {msg.content}")
        session.add_message("assistant", final_content)
        self.sessions.save(session)
        
        # NEW: Emit hook for text response (replaces timeline)
        await hook_manager.emit("agent.response.text",
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content,
            is_final=True
        )
        
        return OutboundMessage(
            channel=origin_channel,
            chat_id=origin_chat_id,
            content=final_content
        )
    
    async def _consolidate_memory(self, session, archive_all: bool = False, job_id: str | None = None) -> None:
        """Consolidate old messages into MEMORY.md + HISTORY.md, then trim session."""
        if not session.messages:
            return
        memory = MemoryStore(self.workspace)
        if archive_all:
            old_messages = session.messages
            keep_count = 0
        else:
            keep_count = min(10, max(2, self.memory_window // 2))
            old_messages = session.messages[:-keep_count]
        if not old_messages:
            return
        logger.info(f"Memory consolidation started: {len(session.messages)} messages, archiving {len(old_messages)}, keeping {keep_count}")
        
        # Extract channel and chat_id from session key
        session_parts = session.key.split(":", 1)
        session_channel = session_parts[0] if len(session_parts) > 0 else "unknown"
        session_chat_id = session_parts[1] if len(session_parts) > 1 else "unknown"
        
        # Emit hook so timeline shows memory consolidation
        await hook_manager.emit("agent.tool.execute",
            tool_name="memory_consolidation",
            tool_args={"messages": len(session.messages), "archiving": len(old_messages), "keeping": keep_count},
            channel=session_channel,
            chat_id=session_chat_id,
            status="start",
            agent=self,
            job_id=job_id
        )

        # Format messages for LLM (include tool names when available)
        lines = []
        for m in old_messages:
            if not m.get("content"):
                continue
            tools = f" [tools: {', '.join(m['tools_used'])}]" if m.get("tools_used") else ""
            lines.append(f"[{m.get('timestamp', '?')[:16]}] {m['role'].upper()}{tools}: {m['content']}")
        conversation = "\n".join(lines)
        current_memory = memory.read_long_term()

        prompt = f"""You are a memory consolidation agent. Process this conversation and return a JSON object with exactly two keys:

1. "history_entry": A paragraph (2-5 sentences) summarizing the key events/decisions/topics. Start with a timestamp like [YYYY-MM-DD HH:MM]. Include enough detail to be useful when found by grep search later.

2. "memory_update": The updated long-term memory content. Add any new facts: user location, preferences, personal info, habits, project context, technical decisions, tools/services used. If nothing new, return the existing content unchanged.

## Current Long-term Memory
{current_memory or "(empty)"}

## Conversation to Process
{conversation}

Respond with ONLY valid JSON, no markdown fences."""

        try:
            response = await self.provider.chat(
                messages=[
                    {"role": "system", "content": "You are a memory consolidation agent. Respond only with valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                model=self.model,
            )
            text = (response.content or "").strip()
            if not text:
                logger.warning("Memory consolidation: LLM returned empty response, skipping")
                return
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            result = json_repair.loads(text)
            if not isinstance(result, dict):
                logger.warning(f"Memory consolidation: unexpected response type, skipping. Response: {text[:200]}")
                return

            if entry := result.get("history_entry"):
                memory.append_history(entry)
            if update := result.get("memory_update"):
                if update != current_memory:
                    memory.write_long_term(update)

            session.messages = session.messages[-keep_count:] if keep_count else []
            self.sessions.save(session)
            logger.info(f"Memory consolidation done, session trimmed to {len(session.messages)} messages")
            
            # Emit end hook for memory consolidation
            await hook_manager.emit("agent.tool.execute",
                tool_name="memory_consolidation",
                tool_args={"messages": len(session.messages), "archiving": len(old_messages), "keeping": keep_count},
                channel=session_channel,
                chat_id=session_chat_id,
                status="end",
                agent=self,
                job_id=job_id
            )
        except Exception as e:
            logger.error(f"Memory consolidation failed: {e}")
            # Emit end hook even on failure
            await hook_manager.emit("agent.tool.execute",
                tool_name="memory_consolidation",
                tool_args={"error": str(e)},
                channel=session_channel,
                chat_id=session_chat_id,
                status="end",
                agent=self,
                job_id=job_id
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
            session_key: Session identifier (overrides channel:chat_id for session lookup).
            channel: Source channel (for tool context routing).
            chat_id: Source chat ID (for tool context routing).
        
        Returns:
            The agent's response.
        """
        await self._connect_mcp()
        msg = InboundMessage(
            channel=channel,
            sender_id="user",
            chat_id=chat_id,
            content=content
        )
        
        response = await self._process_message(msg, session_key=session_key)
        return response.content if response else ""

    async def execute_tool_directly(self, tool_name: str, arguments: dict[str, Any], channel: str, chat_id: str, job_id: str | None = None) -> str:
        """Execute a tool directly and return the result formatted for the user."""
        return await self.qol.execute_tool_directly(tool_name, arguments, channel, chat_id, job_id)
