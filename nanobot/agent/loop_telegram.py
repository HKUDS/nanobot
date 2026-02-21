"""Telegram-enhanced AgentLoop with parallel processing, job tracking, and QOL features."""

from __future__ import annotations

import asyncio
import json
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

import json_repair
from loguru import logger

from nanobot.agent.loop import AgentLoop
from nanobot.agent.memory import MemoryStore
from nanobot.agent.job_tracker import job_manager, ToolCallStatus
from nanobot.system.hooks import hook_manager
from nanobot.agent.qol import QOLManager
from nanobot.agent.tools.gateway import RestartGatewayTool
from nanobot.agent.tools.ipython import IPythonTool
from nanobot.agent.tools.models import ChangeModelTool, ListModelsTool, TestModelTool, AddModelTool
from nanobot.agent.tools.context import ClearContextTool, CompactContextTool
from nanobot.agent.tools.thread import CreateThreadTool, ListThreadsTool
from nanobot.agent.tools.topics import CreateTopicTool, SwitchTopicTool, ListTopicsTool, DeleteTopicTool, CurrentTopicTool, _load_topics
from nanobot.bus.events import InboundMessage, OutboundMessage

if TYPE_CHECKING:
    from nanobot.bus.queue import MessageBus
    from nanobot.providers.base import LLMProvider


class TelegramAgentLoop(AgentLoop):
    """
    AgentLoop with Telegram-specific enhancements.
    
    Adds:
    - Parallel session processing with queue
    - Job tracking with abort support
    - Thread/topic awareness for Telegram
    - Hook integration for timeline updates
    - Model override for cron jobs
    - Extended tool set (IPython, model management, threads, topics)
    """
    
    # Context limits for different models
    MODEL_CONTEXT_LIMITS = {
        "gpt-4o": 128000,
        "gpt-4o-mini": 128000,
        "gpt-4-turbo": 128000,
        "gpt-4": 8192,
        "gpt-3.5-turbo": 16385,
        "claude-3-5-sonnet": 200000,
        "claude-3-opus": 200000,
        "claude-3-sonnet": 200000,
        "claude-3-haiku": 200000,
        "gemini-1.5-pro": 2000000,
        "gemini-1.5-flash": 1000000,
        "default": 128000,
    }
    CONTEXT_THRESHOLD = 0.9
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # QOL manager for queue/processing state
        self.qol = QOLManager(self)
        
        # Reference to Telegram channel for thread creation (set by gateway)
        self._telegram_channel = None
        
        # Track active session tasks for parallel processing
        self._session_tasks: dict[str, asyncio.Task] = {}
        
        # Context limits
        self._model_context_limits = self.MODEL_CONTEXT_LIMITS.copy()
        self._context_threshold = self.CONTEXT_THRESHOLD
        
        # Register extended tools
        self._register_extended_tools()
    
    def _register_extended_tools(self) -> None:
        """Register additional tools for Telegram mode."""
        # Gateway restart tool
        self.tools.register(RestartGatewayTool())

        # IPython tool
        self.tools.register(IPythonTool(
            working_dir=str(self.workspace),
            timeout=60,
            restrict_to_workspace=self.restrict_to_workspace,
            message_callback=self.bus.publish_outbound,
            mode="subprocess",
            tool_registry=self.tools,
        ))

        # Model management tools
        self.tools.register(ChangeModelTool(self))
        self.tools.register(ListModelsTool(agent=self))
        self.tools.register(TestModelTool(self))
        self.tools.register(AddModelTool())

        # Context management tools
        self.tools.register(ClearContextTool(self))
        self.tools.register(CompactContextTool(self))
        
        # Thread management tools
        self.tools.register(CreateThreadTool())
        self.tools.register(ListThreadsTool())
        
        # Topic management tools
        self.tools.register(CreateTopicTool())
        self.tools.register(SwitchTopicTool())
        self.tools.register(ListTopicsTool())
        self.tools.register(DeleteTopicTool())
        self.tools.register(CurrentTopicTool())
    
    def _get_model_context_limit(self) -> int:
        """Get context limit for current model in tokens."""
        model_lower = self.model.lower()
        for model_prefix, limit in self._model_context_limits.items():
            if model_prefix in model_lower:
                return limit
        return self._model_context_limits["default"]
    
    def _get_threads_list_callback(self):
        """Get a callback for listing threads from the Telegram channel."""
        async def list_threads(chat_id: int) -> dict:
            if not self._telegram_channel:
                return {"threads": {}}
            return {"threads": self._telegram_channel._thread_info}
        return list_threads
    
    def _get_topic_aware_session_key(self, base_session_key: str) -> str:
        """Get session key with current topic suffix if a topic is active."""
        try:
            data = _load_topics(base_session_key)
            current_topic = data.get("current_topic")
            if current_topic:
                parts = base_session_key.split(":")
                if len(parts) >= 2:
                    base = f"{parts[0]}:{parts[1]}"
                else:
                    base = base_session_key
                return f"{base}:{current_topic}"
        except Exception as e:
            logger.debug(f"Error loading topics: {e}")
        return base_session_key
    
    def _queue_message(self, session_key: str, message: str) -> None:
        """Queue a message for a session that's currently being processed."""
        self.qol.queue_message(session_key, message)
    
    def _get_and_clear_pending_messages(self, session_key: str) -> list[str]:
        """Get and clear pending messages for a session."""
        return self.qol.get_and_clear_pending_messages(session_key)
    
    def _is_processing(self, session_key: str) -> bool:
        """Check if a session is currently being processed."""
        return self.qol.is_processing(session_key)
    
    async def _process_message(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> OutboundMessage | None:
        """Process a single inbound message with Telegram enhancements."""
        from nanobot.agent.tools.message import MessageTool
        from nanobot.agent.tools.spawn import SpawnTool
        from nanobot.agent.tools.cron import CronTool
        
        # System messages
        if msg.channel == "system":
            channel, chat_id = (msg.chat_id.split(":", 1) if ":" in msg.chat_id
                                else ("cli", msg.chat_id))
            logger.info("Processing system message from {}", msg.sender_id)
            key = f"{channel}:{chat_id}"
            session = self.sessions.get_or_create(key)
            self._set_tool_context(channel, chat_id, msg.metadata.get("message_id"))
            messages = self.context.build_messages(
                history=session.get_history(max_messages=self.memory_window),
                current_message=msg.content, channel=channel, chat_id=chat_id,
            )
            final_content, _ = await self._run_agent_loop(messages)
            session.add_message("user", f"[System: {msg.sender_id}] {msg.content}")
            session.add_message("assistant", final_content or "Background task completed.")
            self.sessions.save(session)
            return OutboundMessage(channel=channel, chat_id=chat_id,
                                  content=final_content or "Background task completed.")

        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info("Processing message from {}:{}: {}", msg.channel, msg.sender_id, preview)

        # Get job_id from metadata if available
        job_id = msg.metadata.get("job_id") if msg.metadata else None
        
        # Get or create session (with topic awareness)
        base_key = session_key or msg.session_key
        key = self._get_topic_aware_session_key(base_key)
        session = self.sessions.get_or_create(key)
        
        # Helper to preserve thread_id from inbound message
        thread_id = msg.metadata.get("thread_id") if msg.metadata else None
        logger.info(f"[THREAD_DEBUG] Extracted thread_id: {thread_id} from metadata: {msg.metadata}")
        def make_metadata(extra: dict | None = None) -> dict:
            m = extra or {}
            if thread_id:
                m["thread_id"] = thread_id
            return m

        # Handle slash commands
        cmd = msg.content.strip().lower()
        if cmd == "/new":
            await self._consolidate_memory(session, archive_all=True)
            session.clear()
            self.sessions.save(session)
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content="🐈 New session started. Memory consolidated.",
                                  metadata=make_metadata())
        if cmd == "/help":
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content="🐈 nanobot commands:\n/new — Start a new conversation\n/help — Show available commands\n\n📁 Topic commands:\n/topic create <name> — Create a new topic\n/topic switch <name> — Switch to a topic\n/topic list — List all topics\n/topic current — Show current topic\n/topic delete <name> — Delete a topic",
                                  metadata=make_metadata())
        
        # Handle topic commands
        if cmd.startswith("/topic"):
            return await self._handle_topic_command(msg, cmd, thread_id)
        
        # Consolidate memory before processing if approaching context limit
        context_limit = self._get_model_context_limit()
        if session.total_tokens > context_limit * self._context_threshold:
            logger.info(f"Session approaching context limit: {session.total_tokens}/{context_limit} tokens")
            await self._consolidate_memory(session, job_id=job_id)
        
        # Update tool contexts with thread_id
        self._set_tool_context(msg.channel, msg.chat_id, msg.metadata.get("message_id"), thread_id=thread_id)
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.start_turn()

        # Build initial messages
        messages = self.context.build_messages(
            history=session.get_history(),
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel, chat_id=msg.chat_id,
        )
        
        # Agent loop with job tracking
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
                        metadata=make_metadata({"job_id": job_id, "aborted": True})
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
                                job_id=job_id,
                                thread_id=thread_id
                            )
                            await hook_manager.emit("agent.timeline.update", job_id=job_id, channel=msg.channel, chat_id=msg.chat_id, thread_id=thread_id)
                    else:
                        llm_call_record.arguments["iteration"] = iteration
                        llm_call_record.arguments["retry"] = True
            
            # Call LLM
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model,
                temperature=self.temperature
            )

            # Capture thinking content if available
            if response.thinking:
                logger.info(f"LLM thinking captured ({len(response.thinking)} chars)")
                await hook_manager.emit("agent.thinking",
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=response.thinking,
                    job_id=job_id
                )

            # Mark llm_call as SUCCESS
            if job_id and llm_call_record:
                await job_manager.job_update_tool_call(job_id, llm_call_record.id, ToolCallStatus.SUCCESS)
                await hook_manager.emit("agent.tool.execute",
                        tool_name="llm_call",
                        tool_args=llm_call_record.arguments,
                        tool_id=llm_call_record.id,
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        status="end",
                        agent=self,
                        job_id=job_id,
                        thread_id=thread_id
                    )
            
            # Handle tool calls
            if response.has_tool_calls:
                # Send intermediate content
                if response.content and response.content.strip():
                    logger.info(f"LLM provided intermediate message: {response.content[:100]}...")
                    intermediate_msg = OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=response.content,
                        metadata=make_metadata({"job_id": job_id, "intermediate": True}),
                    )
                    try:
                        await hook_manager.emit("agent.response.text",
                            channel=msg.channel,
                            chat_id=msg.chat_id,
                            content=response.content,
                            is_final=False,
                            job_id=job_id
                        )
                        await self.bus.publish_outbound(intermediate_msg)
                        session.add_message("assistant", response.content, intermediate=True)
                        self.sessions.save(session)
                    except Exception as e:
                        logger.error(f"Failed to send intermediate message: {e}")

                # Add assistant message with tool calls
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(messages, response.content, tool_call_dicts)
                
                # Execute tools
                for idx, tool_call in enumerate(response.tool_calls):
                    tools_used.append(tool_call.name)
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    logger.info(f"Tool call: {tool_call.name}({args_str[:200]})")
                    
                    await hook_manager.emit("agent.tool.execute",
                        tool_name=tool_call.name,
                        tool_args=tool_call.arguments,
                        tool_id=tool_call.id,
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        status="start",
                        agent=self,
                        job_id=job_id,
                        thread_id=thread_id
                    )

                    result = await self.tools.execute(
                        tool_call.name, tool_call.arguments,
                        channel=msg.channel, chat_id=msg.chat_id, job_id=job_id,
                        bus=self.bus, session_manager=self.sessions,
                        session_key=key,
                    )

                    await hook_manager.emit("agent.tool.execute",
                        tool_name=tool_call.name,
                        tool_args=tool_call.arguments,
                        tool_id=tool_call.id,
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        status="end",
                        result=result,
                        agent=self,
                        job_id=job_id,
                        thread_id=thread_id
                    )
                    messages = self.context.add_tool_result(messages, tool_call.id, tool_call.name, result)
                    
                    # Send result for certain tools
                    if tool_call.name in ["restart_gateway"]:
                        await self.bus.publish_outbound(OutboundMessage(
                            channel=msg.channel,
                            chat_id=msg.chat_id,
                            content=result,
                            metadata=make_metadata({"job_id": job_id} if job_id else {})
                        ))
                    
                    # Check for queued messages
                    new_messages = self._get_and_clear_pending_messages(msg.session_key)
                    if new_messages:
                        logger.info(f"Injecting {len(new_messages)} new user message(s) mid-operation")
                        for new_msg_content in new_messages:
                            messages.append({"role": "user", "content": new_msg_content})
                            session.add_message("user", new_msg_content)
                        break
            else:
                final_content = response.content
                break
        
        if final_content is None:
            if iteration >= self.max_iterations:
                final_content = f"Reached {self.max_iterations} iterations without completion."
            else:
                final_content = "I've completed processing but have no response to give."
        
        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info("Response to {}:{}: {}", msg.channel, msg.sender_id, preview)
        
        session.add_message("user", msg.content)
        session.add_message("assistant", final_content, tools_used=tools_used if tools_used else None)
        self.sessions.save(session)

        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool) and message_tool._sent_in_turn:
                return None
        
        if job_id:
            await job_manager.complete_job(job_id, final_content)

        await hook_manager.emit("agent.response.text",
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content,
            is_final=True
        )
        
        merged_metadata = dict(msg.metadata) if msg.metadata else {}
        merged_metadata.update({"job_id": job_id, "is_final": True})
        if "thread_id" not in merged_metadata and msg.metadata and "thread_id" in msg.metadata:
            merged_metadata["thread_id"] = msg.metadata["thread_id"]

        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content,
            metadata=merged_metadata,
        )
    
    async def _handle_topic_command(self, msg: InboundMessage, cmd: str, thread_id: int | None = None) -> OutboundMessage:
        """Handle /topic slash commands."""
        from nanobot.agent.tools.topics import _load_topics, _save_topics
        
        def make_metadata(extra: dict | None = None) -> dict:
            m = extra or {}
            if thread_id:
                m["thread_id"] = thread_id
            return m
        
        parts = cmd.split(maxsplit=2)
        base_key = f"{msg.channel}:{msg.chat_id}"
        
        if len(parts) == 1 or parts[1] == "list":
            data = _load_topics(base_key)
            topics = []
            for name, info in data.get("topics", {}).items():
                marker = "📌 " if name == data.get("current_topic") else "   "
                topics.append(f"{marker}{name}")
            
            if not topics:
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                      content="📁 No topics created yet.\nUse /topic create <name> to create one.",
                                      metadata=make_metadata())
            
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content=f"📁 Topics:\n" + "\n".join(topics),
                                  metadata=make_metadata())
        
        if parts[1] == "current":
            data = _load_topics(base_key)
            current = data.get("current_topic")
            if current:
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                      content=f"📌 Current topic: {current}",
                                      metadata=make_metadata())
            else:
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                      content="📁 No topic active (using default context)",
                                      metadata=make_metadata())
        
        if parts[1] == "create" and len(parts) >= 3:
            name = parts[2].strip()
            if not name or len(name) > 64 or not all(c.isalnum() or c in "_-" for c in name):
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                      content="❌ Invalid topic name. Use 1-64 alphanumeric chars, underscores, or hyphens.",
                                      metadata=make_metadata())
            
            data = _load_topics(base_key)
            if name in data.get("topics", {}):
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                      content=f"❌ Topic '{name}' already exists.",
                                      metadata=make_metadata())
            
            from datetime import datetime
            data.setdefault("topics", {})[name] = {"created": datetime.now().isoformat()}
            data["current_topic"] = name
            _save_topics(base_key, data)
            
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content=f"✅ Created and switched to topic: {name}",
                                  metadata=make_metadata())
        
        if parts[1] == "switch" and len(parts) >= 3:
            name = parts[2].strip()
            data = _load_topics(base_key)
            if name not in data.get("topics", {}):
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                      content=f"❌ Topic '{name}' doesn't exist.",
                                      metadata=make_metadata())
            
            data["current_topic"] = name
            _save_topics(base_key, data)
            
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content=f"📌 Switched to topic: {name}",
                                  metadata=make_metadata())
        
        if parts[1] == "delete" and len(parts) >= 3:
            name = parts[2].strip()
            data = _load_topics(base_key)
            if name not in data.get("topics", {}):
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                      content=f"❌ Topic '{name}' doesn't exist.",
                                      metadata=make_metadata())
            
            del data["topics"][name]
            if data.get("current_topic") == name:
                data["current_topic"] = None
            _save_topics(base_key, data)
            
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content=f"🗑️ Deleted topic: {name}",
                                  metadata=make_metadata())
        
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                              content="📁 Usage: /topic [list|current|create|switch|delete] [name]",
                              metadata=make_metadata())
    
    async def run(self) -> None:
        """Run the agent loop with parallel session processing."""
        self._running = True
        await self._connect_mcp()
        logger.info("Agent loop started (parallel session mode)")
        
        self._session_tasks: dict[str, asyncio.Task] = {}
        
        while self._running:
            try:
                msg = await asyncio.wait_for(
                    self.bus.consume_inbound(),
                    timeout=1.0
                )
                
                session_key = msg.session_key
                logger.info(f"[QUEUE_DEBUG] Message session_key: {session_key}")
                
                if self._is_processing(session_key):
                    self._queue_message(session_key, msg.content)
                    logger.info(f"[QUEUE_DEBUG] Session {session_key} is busy, queued message")
                    continue
                
                task = asyncio.create_task(
                    self._process_session_message(msg, session_key),
                    name=f"session-{session_key}"
                )
                self._session_tasks[session_key] = task
                logger.info(f"[PARALLEL] Spawned task for session {session_key}")
                
            except asyncio.TimeoutError:
                logger.debug("Agent loop timeout - no messages waiting")
                continue
            except Exception as e:
                logger.error(f"Unexpected error in agent loop: {e}")
                logger.error(traceback.format_exc())
                await asyncio.sleep(1)
    
    async def _process_session_message(self, msg: InboundMessage, session_key: str) -> None:
        """Process a message for a session (runs in separate task for parallelism)."""
        try:
            self.qol.start_processing(session_key)
            response = await self._process_message(msg)
            if response:
                await self.bus.publish_outbound(response)
        except Exception as e:
            logger.error(f"Error processing message for session {session_key}: {e}")
            logger.error(traceback.format_exc())
            
            job_id = msg.metadata.get("job_id") if msg.metadata else None
            if job_id:
                try:
                    await job_manager.fail_job(job_id, str(e))
                except Exception as fail_error:
                    logger.warning(f"Failed to mark job {job_id} as failed: {fail_error}")
            
            thread_id = msg.metadata.get("thread_id") if msg.metadata else None
            error_metadata = {"thread_id": thread_id} if thread_id else {}
            await self.bus.publish_outbound(OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=f"Sorry, I encountered an error: {str(e)}",
                metadata=error_metadata
            ))
        finally:
            self.qol.finish_processing(session_key)
            if session_key in self._session_tasks:
                del self._session_tasks[session_key]
            logger.info(f"[PARALLEL] Finished task for session {session_key}")
    
    def _set_tool_context(self, channel: str, chat_id: str, message_id: str | None = None, thread_id: int | None = None) -> None:
        """Update context for all tools that need routing info."""
        super()._set_tool_context(channel, chat_id, message_id)
        
        if message_tool := self.tools.get("message"):
            from nanobot.agent.tools.message import MessageTool
            if isinstance(message_tool, MessageTool):
                message_tool.set_context(channel, chat_id, message_id=message_id, thread_id=thread_id)
        
        if ipython_tool := self.tools.get("ipython"):
            if isinstance(ipython_tool, IPythonTool):
                ipython_tool.set_context(channel, chat_id)
        
        if create_thread_tool := self.tools.get("create_thread"):
            if isinstance(create_thread_tool, CreateThreadTool):
                create_thread_tool.set_context(channel, chat_id)
                if not create_thread_tool.create_callback and self._telegram_channel:
                    create_thread_tool.set_callback(self._telegram_channel.create_forum_topic)
        
        if list_threads_tool := self.tools.get("list_threads"):
            if isinstance(list_threads_tool, ListThreadsTool):
                list_threads_tool.set_context(channel, chat_id)
                if not list_threads_tool.list_callback and self._telegram_channel:
                    list_threads_tool.list_callback = self._get_threads_list_callback()
    
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
        
        session_parts = session.key.split(":", 1)
        session_channel = session_parts[0] if len(session_parts) > 0 else "unknown"
        session_chat_id = session_parts[1] if len(session_parts) > 1 else "unknown"
        
        await hook_manager.emit("agent.tool.execute",
            tool_name="memory_consolidation",
            tool_args={"messages": len(session.messages), "archiving": len(old_messages), "keeping": keep_count},
            channel=session_channel,
            chat_id=session_chat_id,
            status="start",
            agent=self,
            job_id=job_id,
            thread_id=None
        )

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
            session.total_tokens = sum(
                session.estimate_tokens(m.get("content", ""))
                for m in session.messages
            )
            self.sessions.save(session)
            logger.info(f"Memory consolidation done, session trimmed to {len(session.messages)} messages ({session.total_tokens} tokens)")
            
            await hook_manager.emit("agent.tool.execute",
                tool_name="memory_consolidation",
                tool_args={"messages": len(session.messages), "archiving": len(old_messages), "keeping": keep_count},
                channel=session_channel,
                chat_id=session_chat_id,
                status="end",
                agent=self,
                job_id=job_id,
                thread_id=None
            )
        except Exception as e:
            logger.error(f"Memory consolidation failed: {e}")
            await hook_manager.emit("agent.tool.execute",
                tool_name="memory_consolidation",
                tool_args={"error": str(e)},
                channel=session_channel,
                chat_id=session_chat_id,
                status="end",
                agent=self,
                job_id=job_id,
                thread_id=None
            )
    
    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
        model: str | None = None,
    ) -> str:
        """Process a message directly with optional model override."""
        await self._connect_mcp()
        
        original_model = self.model
        if model:
            self.model = model
            logger.info(f"Cron job using model: {model}")
        
        try:
            msg = InboundMessage(
                channel=channel,
                sender_id="user",
                chat_id=chat_id,
                content=content
            )
            response = await self._process_message(msg, session_key=session_key, on_progress=on_progress)
            return response.content if response else ""
        finally:
            if model:
                self.model = original_model

    async def execute_tool_directly(self, tool_name: str, arguments: dict[str, Any], channel: str, chat_id: str, job_id: str | None = None) -> str:
        """Execute a tool directly and return the result formatted for the user."""
        return await self.qol.execute_tool_directly(tool_name, arguments, channel, chat_id, job_id)
