"""Agent loop: the core processing engine."""

from __future__ import annotations

import asyncio
import json
import re
import signal
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

from loguru import logger

from nanobot.agent.context import ContextBuilder
from nanobot.agent.memory import MemoryStore
from nanobot.agent.subagent import SubagentManager
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider
from nanobot.session.manager import Session, SessionManager

if TYPE_CHECKING:
    from nanobot.config.schema import ChannelsConfig, ExecToolConfig
    from nanobot.cron.service import CronService


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

    _TOOL_RESULT_MAX_CHARS = 500

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 40,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        memory_window: int = 100,
        context_limit: int = 0,  # 0 = no limit, positive value = max messages before trimming
        reasoning_effort: str | None = None,
        brave_api_key: str | None = None,
        web_proxy: str | None = None,
        exec_config: ExecToolConfig | None = None,
        cron_service: CronService | None = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
        channels_config: ChannelsConfig | None = None,
    ):
        from nanobot.config.schema import ExecToolConfig
        self.bus = bus
        self.channels_config = channels_config
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.memory_window = memory_window
        self.context_limit = context_limit  # Context window management
        self.reasoning_effort = reasoning_effort
        self.brave_api_key = brave_api_key
        self.web_proxy = web_proxy
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
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            reasoning_effort=reasoning_effort,
            brave_api_key=brave_api_key,
            web_proxy=web_proxy,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
        )

        self._running = False
        self._mcp_servers = mcp_servers or {}
        self._mcp_stack: AsyncExitStack | None = None
        self._mcp_connected = False
        self._mcp_connecting = False
        self._consolidating: set[str] = set()  # Session keys with consolidation in progress
        self._consolidation_tasks: set[asyncio.Task] = set()  # Strong refs to in-flight tasks
        self._consolidation_locks: dict[str, asyncio.Lock] = {}  # Strong refs to locks
        self._active_tasks: dict[str, list[asyncio.Task]] = {}  # session_key -> tasks
        self._task_cleanup_lock = asyncio.Lock()  # Prevents race conditions in task cleanup
        self._processing_lock = asyncio.Lock()
        
        # Graceful shutdown support
        self._shutdown_event = asyncio.Event()
        self._graceful_shutdown = False
        
        self._register_default_tools()
        self._setup_signal_handlers()

    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        for cls in (ReadFileTool, WriteFileTool, EditFileTool, ListDirTool):
            self.tools.register(cls(workspace=self.workspace, allowed_dir=allowed_dir))
        self.tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            restrict_to_workspace=self.restrict_to_workspace,
            path_append=self.exec_config.path_append,
        ))
        self.tools.register(WebSearchTool(api_key=self.brave_api_key, proxy=self.web_proxy))
        self.tools.register(WebFetchTool(proxy=self.web_proxy))
        self.tools.register(MessageTool(send_callback=self.bus.publish_outbound))
        self.tools.register(SpawnTool(manager=self.subagents))
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))

    def _setup_signal_handlers(self) -> None:
        """
        Setup signal handlers for graceful shutdown.
        
        Handles SIGTERM and SIGINT to ensure clean shutdown of:
        - Active message processing tasks
        - Subagents and their resources  
        - Memory consolidation
        - MCP server connections
        """
        if sys.platform != "win32":
            # Unix-like systems support signal handling
            def signal_handler(signum: int) -> None:
                signal_name = signal.Signals(signum).name
                logger.info("Received signal {}, initiating graceful shutdown...", signal_name)
                self._graceful_shutdown = True
                self._shutdown_event.set()
            
            # Register signal handlers in event loop
            try:
                loop = asyncio.get_event_loop()
                for sig in (signal.SIGTERM, signal.SIGINT):
                    loop.add_signal_handler(sig, lambda s=sig: signal_handler(s))
                logger.debug("Signal handlers registered for SIGTERM and SIGINT")
            except (RuntimeError, NotImplementedError) as e:
                logger.warning("Could not register signal handlers: {}", e)
        else:
            logger.debug("Signal handling not available on Windows")

    async def _connect_mcp(self) -> None:
        """Connect to configured MCP servers (one-time, lazy)."""
        if self._mcp_connected or self._mcp_connecting or not self._mcp_servers:
            return
        self._mcp_connecting = True
        from nanobot.agent.tools.mcp import connect_mcp_servers
        try:
            self._mcp_stack = AsyncExitStack()
            await self._mcp_stack.__aenter__()
            await connect_mcp_servers(self._mcp_servers, self.tools, self._mcp_stack)
            self._mcp_connected = True
        except Exception as e:
            logger.error("Failed to connect MCP servers (will retry next message): {}", e)
            if self._mcp_stack:
                try:
                    await self._mcp_stack.aclose()
                except Exception:
                    pass
                self._mcp_stack = None
        finally:
            self._mcp_connecting = False

    def _set_tool_context(self, channel: str, chat_id: str, message_id: str | None = None) -> None:
        """Update context for all tools that need routing info."""
        for name in ("message", "spawn", "cron"):
            if tool := self.tools.get(name):
                if hasattr(tool, "set_context"):
                    tool.set_context(channel, chat_id, *([message_id] if name == "message" else []))

    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        """Remove <think>…</think> blocks that some models embed in content."""
        if not text:
            return None
        return re.sub(r"<think>[\s\S]*?</think>", "", text).strip() or None

    @staticmethod
    def _tool_hint(tool_calls: list) -> str:
        """Format tool calls as concise hint, e.g. 'web_search("query")'."""
        def _fmt(tc):
            args = (tc.arguments[0] if isinstance(tc.arguments, list) else tc.arguments) or {}
            val = next(iter(args.values()), None) if isinstance(args, dict) else None
            if not isinstance(val, str):
                return tc.name
            return f'{tc.name}("{val[:40]}…")' if len(val) > 40 else f'{tc.name}("{val}")'
        return ", ".join(_fmt(tc) for tc in tool_calls)

    async def _run_agent_loop(
        self,
        initial_messages: list[dict],
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> tuple[str | None, list[str], list[dict]]:
        """Run the agent iteration loop. Returns (final_content, tools_used, messages)."""
        messages = initial_messages
        iteration = 0
        final_content = None
        tools_used: list[str] = []

        while iteration < self.max_iterations:
            iteration += 1
            
            # Implement sliding-window context trimming before API call
            if hasattr(self, 'context_limit') and self.context_limit and self.context_limit > 0:
                trimmed_messages = self._trim_context_window(messages, self.context_limit)
                if len(trimmed_messages) < len(messages):
                    logger.info(
                        "Context window trimmed: {} -> {} messages (limit: {})",
                        len(messages), len(trimmed_messages), self.context_limit
                    )
                messages = trimmed_messages

            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                reasoning_effort=self.reasoning_effort,
            )

            if response.has_tool_calls:
                if on_progress:
                    thoughts = [
                        self._strip_think(response.content),
                        response.reasoning_content,
                        *(
                            f"Thinking [{b.get('signature', '...')}]:\n{b.get('thought', '...')}"
                            for b in (response.thinking_blocks or [])
                            if isinstance(b, dict) and "signature" in b
                        ),
                    ]
                    combined_thoughts = "\n\n".join(filter(None, thoughts))
                    if combined_thoughts:
                        await on_progress(combined_thoughts)
                    await on_progress(self._tool_hint(response.tool_calls), tool_hint=True)

                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False)
                        }
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts,
                    reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                )

                for tool_call in response.tool_calls:
                    tools_used.append(tool_call.name)
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    logger.info("Tool call: {}({})", tool_call.name, args_str[:200])
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                clean = self._strip_think(response.content)
                # Don't persist error responses to session history — they can
                # poison the context and cause permanent 400 loops (#1303).
                if response.finish_reason == "error":
                    logger.error("LLM returned error: {}", (clean or "")[:200])
                    final_content = clean or "Sorry, I encountered an error calling the AI model."
                    break
                messages = self.context.add_assistant_message(
                    messages, clean, reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                )
                final_content = clean
                break

        if final_content is None and iteration >= self.max_iterations:
            logger.warning("Max iterations ({}) reached", self.max_iterations)
            final_content = (
                f"I reached the maximum number of tool call iterations ({self.max_iterations}) "
                "without completing the task. You can try breaking the task into smaller steps."
            )

        return final_content, tools_used, messages
    
    def _trim_context_window(self, messages: list[dict], context_limit: int) -> list[dict]:
        """
        Implement sliding-window trimming to keep messages within context limits.
        
        Preserves system message and recent conversation while removing older messages
        to stay within the specified token/message limit.
        
        Args:
            messages: Current message history
            context_limit: Maximum number of messages to retain
            
        Returns:
            Trimmed message list within context limit
        """
        if len(messages) <= context_limit:
            return messages
            
        # Always preserve system message (typically first message)
        system_messages = [msg for msg in messages if msg.get('role') == 'system']
        non_system_messages = [msg for msg in messages if msg.get('role') != 'system']
        
        # Reserve space for system messages
        available_space = context_limit - len(system_messages)
        
        if available_space <= 0:
            # If system messages exceed limit, just return first system message
            return system_messages[:1] if system_messages else messages[:context_limit]
        
        # Keep the most recent N non-system messages
        recent_messages = non_system_messages[-available_space:] if available_space < len(non_system_messages) else non_system_messages
        
        # Reconstruct: system messages + recent conversation
        trimmed = system_messages + recent_messages
        
        logger.debug(
            "Context trimming: kept {} system + {} recent messages (total: {})",
            len(system_messages), len(recent_messages), len(trimmed)
        )
        
        return trimmed

    async def run(self) -> None:
        """Run the agent loop with signal handling for graceful shutdown."""
        self._running = True
        self._shutdown_event.clear()
        await self._connect_mcp()
        logger.info("Agent loop started")

        try:
            # Main processing loop with signal handling
            while self._running and not self._graceful_shutdown:
                try:
                    # Check for shutdown signal
                    shutdown_task = asyncio.create_task(self._shutdown_event.wait())
                    consume_task = asyncio.create_task(self.bus.consume_inbound())
                    
                    # Wait for either message or shutdown signal
                    done, pending = await asyncio.wait(
                        [shutdown_task, consume_task],
                        timeout=1.0,
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    
                    # Cancel pending tasks
                    for task in pending:
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                    
                    # Handle shutdown signal
                    if shutdown_task in done:
                        logger.info("Shutdown signal received, stopping gracefully...")
                        break
                        
                    # Handle message if available
                    if consume_task in done:
                        msg = await consume_task
                        
                        if msg.content.strip().lower() == "/stop":
                            await self._handle_stop(msg)
                        else:
                            task = asyncio.create_task(self._dispatch(msg))
                            self._active_tasks.setdefault(msg.session_key, []).append(task)
                            task.add_done_callback(
                                lambda t, key=msg.session_key: asyncio.create_task(
                                    self._cleanup_task(t, key)
                                )
                            )
                        
                except asyncio.TimeoutError:
                    # Timeout is expected, continue loop
                    continue
                    
        except Exception as e:
            logger.exception("Unexpected error in agent loop: {}", e)
        finally:
            await self._shutdown_gracefully()
            
    async def _shutdown_gracefully(self) -> None:
        """
        Perform graceful shutdown of all agent components.
        
        This ensures:
        - All active tasks are cancelled and awaited
        - Memory is consolidated and saved
        - Subagents are properly closed
        - MCP connections are terminated cleanly
        """
        logger.info("Beginning graceful shutdown...")
        self._running = False
        
        # Cancel and wait for all active tasks
        all_tasks = []
        for session_tasks in self._active_tasks.values():
            all_tasks.extend(session_tasks)
            
        if all_tasks:
            logger.info("Cancelling {} active tasks...", len(all_tasks))
            for task in all_tasks:
                if not task.done():
                    task.cancel()
                    
            # Wait for all tasks to complete with timeout
            try:
                await asyncio.wait_for(
                    asyncio.gather(*all_tasks, return_exceptions=True),
                    timeout=10.0
                )
                logger.info("All active tasks cancelled successfully")
            except asyncio.TimeoutError:
                logger.warning("Some tasks did not shutdown within timeout")
        
        # Close subagents and their resources
        try:
            await self.subagents.close_all()
            logger.debug("Subagents closed successfully")
        except Exception as e:
            logger.warning("Error closing subagents: {}", e)
            
        # Consolidate and save memory
        try:
            if hasattr(self, 'memory') and self.memory:
                await self.memory.consolidate_and_save()
                logger.debug("Memory consolidated and saved")
        except Exception as e:
            logger.warning("Error saving memory: {}", e)
            
        # Close MCP connections
        try:
            await self.close_mcp()
            logger.debug("MCP connections closed")
        except Exception as e:
            logger.warning("Error closing MCP connections: {}", e)
            
        logger.info("Graceful shutdown completed")
        
    def stop(self) -> None:
        """
        Signal the agent loop to stop gracefully.
        
        This is a synchronous method that can be called from signal handlers
        or other contexts to initiate shutdown.
        """
        logger.info("Stop requested")
        self._graceful_shutdown = True
        self._shutdown_event.set()
        
    def stop(self) -> None:
        """
        Signal the agent loop to stop gracefully.
        
        This is a synchronous method that can be called from signal handlers
        or other contexts to initiate shutdown.
        """
        logger.info("Stop requested")
        self._graceful_shutdown = True
        self._shutdown_event.set()

    async def _handle_stop(self, msg: InboundMessage) -> None:
        """Cancel all active tasks and subagents for the session."""
        tasks = self._active_tasks.pop(msg.session_key, [])
        cancelled = sum(1 for t in tasks if not t.done() and t.cancel())
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        sub_cancelled = await self.subagents.cancel_by_session(msg.session_key)
        total = cancelled + sub_cancelled
        content = f"⏹ Stopped {total} task(s)." if total else "No active task to stop."
        await self.bus.publish_outbound(OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=content,
        ))
    async def _cleanup_task(self, task: asyncio.Task[None], session_key: str) -> None:
        """Thread-safe cleanup of completed tasks.
        
        Args:
            task: The completed asyncio task to clean up.
            session_key: The session key associated with the task.
        
        Note:
            This method ensures thread-safe removal of completed tasks
            from the active tasks dictionary and cleans up empty lists.
        """
        async with self._task_cleanup_lock:
            if session_key in self._active_tasks:
                try:
                    self._active_tasks[session_key].remove(task)
                    # Clean up empty lists
                    if not self._active_tasks[session_key]:
                        del self._active_tasks[session_key]
                except ValueError:
                    # Task was already removed, ignore
                    pass
    async def _dispatch(self, msg: InboundMessage) -> None:
        """Process a message under the global lock."""
        async with self._processing_lock:
            try:
                response = await self._process_message(msg)
                if response is not None:
                    await self.bus.publish_outbound(response)
                elif msg.channel == "cli":
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel, chat_id=msg.chat_id,
                        content="", metadata=msg.metadata or {},
                    ))
            except asyncio.CancelledError:
                logger.info("Task cancelled for session {}", msg.session_key)
                raise
            except Exception:
                logger.exception("Error processing message for session {}", msg.session_key)
                await self.bus.publish_outbound(OutboundMessage(
                    channel=msg.channel, chat_id=msg.chat_id,
                    content="Sorry, I encountered an error.",
                ))

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

    async def _process_message(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> OutboundMessage | None:
        """Process a single inbound message and return the response."""
        # System messages: parse origin from chat_id ("channel:chat_id")
        if msg.channel == "system":
            channel, chat_id = (msg.chat_id.split(":", 1) if ":" in msg.chat_id
                                else ("cli", msg.chat_id))
            logger.info("Processing system message from {}", msg.sender_id)
            key = f"{channel}:{chat_id}"
            session = self.sessions.get_or_create(key)
            self._set_tool_context(channel, chat_id, msg.metadata.get("message_id"))
            history = session.get_history(max_messages=self.memory_window)
            messages = self.context.build_messages(
                history=history,
                current_message=msg.content, channel=channel, chat_id=chat_id,
            )
            final_content, _, all_msgs = await self._run_agent_loop(messages)
            self._save_turn(session, all_msgs, 1 + len(history))
            self.sessions.save(session)
            return OutboundMessage(channel=channel, chat_id=chat_id,
                                  content=final_content or "Background task completed.")

        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info("Processing message from {}:{}: {}", msg.channel, msg.sender_id, preview)

        key = session_key or msg.session_key
        session = self.sessions.get_or_create(key)

        # Slash commands
        cmd = msg.content.strip().lower()
        if cmd == "/new":
            lock = self._consolidation_locks.setdefault(session.key, asyncio.Lock())
            self._consolidating.add(session.key)
            
            # Create atomic transaction for session clearing
            session_backup = None
            try:
                async with lock:
                    # Create backup before modification for rollback capability
                    session_backup = {
                        'messages': session.messages[:],
                        'last_consolidated': session.last_consolidated
                    }
                    
                    snapshot = session.messages[session.last_consolidated:]
                    if snapshot:
                        temp = Session(key=session.key)
                        temp.messages = list(snapshot)
                        
                        # Archive memory with rollback on failure
                        if not await self._consolidate_memory(temp, archive_all=True):
                            return OutboundMessage(
                                channel=msg.channel, chat_id=msg.chat_id,
                                content="Memory archival failed, session not cleared. Please try again.",
                            )
                    
                    # Atomic session state update - only clear if archival succeeded
                    session.clear()
                    self.sessions.save(session)
                    self.sessions.invalidate(session.key)
                    
            except Exception as e:
                # Rollback session state if backup exists
                if session_backup:
                    session.messages[:] = session_backup['messages']
                    session.last_consolidated = session_backup['last_consolidated']
                    
                logger.exception("/new archival failed for {}", session.key)
                return OutboundMessage(
                    channel=msg.channel, chat_id=msg.chat_id,
                    content="Memory archival failed, session not cleared. Please try again.",
                )
            finally:
                self._consolidating.discard(session.key)

            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content="New session started.")
        if cmd == "/help":
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content="🐈 nanobot commands:\n/new — Start a new conversation\n/stop — Stop the current task\n/help — Show available commands")

        unconsolidated = len(session.messages) - session.last_consolidated
        if (unconsolidated >= self.memory_window and session.key not in self._consolidating):
            self._consolidating.add(session.key)
            lock = self._consolidation_locks.setdefault(session.key, asyncio.Lock())

            async def _consolidate_and_unlock():
                try:
                    async with lock:
                        await self._consolidate_memory(session)
                finally:
                    self._consolidating.discard(session.key)
                    _task = asyncio.current_task()
                    if _task is not None:
                        self._consolidation_tasks.discard(_task)

            _task = asyncio.create_task(_consolidate_and_unlock())
            self._consolidation_tasks.add(_task)

        self._set_tool_context(msg.channel, msg.chat_id, msg.metadata.get("message_id"))
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.start_turn()

        history = session.get_history(max_messages=self.memory_window)
        initial_messages = self.context.build_messages(
            history=history,
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel, chat_id=msg.chat_id,
        )

        async def _bus_progress(content: str, *, tool_hint: bool = False) -> None:
            meta = dict(msg.metadata or {})
            meta["_progress"] = True
            meta["_tool_hint"] = tool_hint
            await self.bus.publish_outbound(OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id, content=content, metadata=meta,
            ))

        final_content, _, all_msgs = await self._run_agent_loop(
            initial_messages, on_progress=on_progress or _bus_progress,
        )

        if final_content is None:
            final_content = "I've completed processing but have no response to give."

        self._save_turn(session, all_msgs, 1 + len(history))
        self.sessions.save(session)

        if (mt := self.tools.get("message")) and isinstance(mt, MessageTool) and mt._sent_in_turn:
            return None

        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info("Response to {}:{}: {}", msg.channel, msg.sender_id, preview)
        return OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=final_content,
            metadata=msg.metadata or {},
        )

    def _save_turn(self, session: Session, messages: list[dict], skip: int) -> None:
        """Save new-turn messages into session, truncating large tool results."""
        from datetime import datetime
        for m in messages[skip:]:
            entry = dict(m)
            role, content = entry.get("role"), entry.get("content")
            if role == "assistant" and not content and not entry.get("tool_calls"):
                continue  # skip empty assistant messages — they poison session context
            if role == "tool" and isinstance(content, str) and len(content) > self._TOOL_RESULT_MAX_CHARS:
                entry["content"] = content[:self._TOOL_RESULT_MAX_CHARS] + "\n... (truncated)"
            elif role == "user":
                if isinstance(content, str) and content.startswith(ContextBuilder._RUNTIME_CONTEXT_TAG):
                    # Strip the runtime-context prefix, keep only the user text.
                    parts = content.split("\n\n", 1)
                    if len(parts) > 1 and parts[1].strip():
                        entry["content"] = parts[1]
                    else:
                        continue
                if isinstance(content, list):
                    filtered = []
                    for c in content:
                        if c.get("type") == "text" and isinstance(c.get("text"), str) and c["text"].startswith(ContextBuilder._RUNTIME_CONTEXT_TAG):
                            continue  # Strip runtime context from multimodal messages
                        if (c.get("type") == "image_url"
                                and c.get("image_url", {}).get("url", "").startswith("data:image/")):
                            filtered.append({"type": "text", "text": "[image]"})
                        else:
                            filtered.append(c)
                    if not filtered:
                        continue
                    entry["content"] = filtered
            entry.setdefault("timestamp", datetime.now().isoformat())
            session.messages.append(entry)
        session.updated_at = datetime.now()

    async def _consolidate_memory(self, session, archive_all: bool = False) -> bool:
        """Delegate to MemoryStore.consolidate(). Returns True on success."""
        return await MemoryStore(self.workspace).consolidate(
            session, self.provider, self.model,
            archive_all=archive_all, memory_window=self.memory_window,
        )

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """Process a message directly (for CLI or cron usage)."""
        await self._connect_mcp()
        msg = InboundMessage(channel=channel, sender_id="user", chat_id=chat_id, content=content)
        response = await self._process_message(msg, session_key=session_key, on_progress=on_progress)
        return response.content if response else ""
