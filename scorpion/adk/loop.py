"""ADK-based agent loop: replaces the custom AgentLoop with Google ADK runtime."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import weakref
from contextlib import AsyncExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

# Suppress Google ADK "default value not supported" warnings from function declaration schemas
logging.getLogger(
    "google_adk.google.adk.tools._function_parameter_parse_util"
).setLevel(logging.ERROR)

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from loguru import logger

from scorpion.adk.callbacks import (
    clear_turn_tools,
    get_turn_tools,
    make_after_model_callback,
    make_after_tool_callback,
    make_before_agent_callback,
    make_before_tool_callback,
)
from scorpion.adk.pending import PendingResults
from scorpion.adk.tools import ALL_TOOLS, set_runtime_refs
from scorpion.agent.context import ContextBuilder
from scorpion.agent.memory import MemoryStore
from scorpion.agent.subagent import SubagentManager
from scorpion.bus.events import InboundMessage, OutboundMessage
from scorpion.bus.queue import MessageBus
from scorpion.session.manager import Session, SessionManager
from scorpion.config.schema import FLASH_MODEL

if TYPE_CHECKING:
    from scorpion.config.schema import ChannelsConfig, ExecToolConfig
    from scorpion.cron.service import CronService


class AdkAgentLoop:
    """ADK-based agent loop — same external interface as AgentLoop.

    Uses Google ADK's LlmAgent + Runner instead of custom LLM iteration.
    """

    _TOOL_RESULT_MAX_CHARS = 500

    def __init__(
        self,
        bus: MessageBus,
        provider,  # kept for memory consolidation / heartbeat
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 40,
        temperature: float = 0.1,
        max_tokens: int = 8192,
        memory_window: int = 100,
        reasoning_effort: str | None = None,
        brave_api_key: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        cron_service: "CronService | None" = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
        channels_config: "ChannelsConfig | None" = None,
        gemini_api_key: str | None = None,
    ):
        from scorpion.config.schema import ExecToolConfig

        self.bus = bus
        self.channels_config = channels_config
        self.provider = provider  # for memory consolidation
        self.workspace = workspace
        self.model = model or FLASH_MODEL
        self.max_iterations = max_iterations
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.memory_window = memory_window
        self.reasoning_effort = reasoning_effort
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
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            reasoning_effort=reasoning_effort,
            brave_api_key=brave_api_key,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
        )

        self._running = False
        self._mcp_servers = mcp_servers or {}
        self._mcp_stack: AsyncExitStack | None = None
        self._mcp_connected = False
        self._mcp_connecting = False
        self._mcp_tools: list = []  # ADK FunctionTool wrappers from MCP
        self._consolidating: set[str] = set()
        self._consolidation_tasks: set[asyncio.Task] = set()
        self._consolidation_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )
        self._active_tasks: dict[str, list[asyncio.Task]] = {}
        self._processing_lock = asyncio.Lock()
        self._pending_results = PendingResults()

        # Wire module-level tool references
        set_runtime_refs(
            bus_publish=self.bus.publish_outbound,
            subagent_manager=self.subagents,
            cron_service=self.cron_service,
            pending_results=self._pending_results,
            gemini_api_key=gemini_api_key,
        )

        # ADK session service (in-memory — scorpion JSONL is the persistence layer)
        self._session_service = InMemorySessionService()

    # ── State helpers ────────────────────────────────────────────────────────

    def _build_state(
        self, channel: str = "", chat_id: str = "", message_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the ADK session state dict with runtime context."""
        allowed_dir = str(self.workspace) if self.restrict_to_workspace else ""
        state: dict[str, Any] = {
            "app:workspace": str(self.workspace),
            "app:brave_api_key": self.brave_api_key or "",
            "app:exec_timeout": str(self.exec_config.timeout),
            "app:exec_deny": json.dumps(self.exec_config.deny_patterns) if self.exec_config.deny_patterns else "",
            "app:exec_allow": json.dumps(self.exec_config.allow_patterns) if self.exec_config.allow_patterns else "",
            "app:exec_restrict": "true" if self.restrict_to_workspace else "",
            "app:exec_path": self.exec_config.path_append or "",
            "app:allowed_dir": allowed_dir,
            "app:max_iterations": str(self.max_iterations),
            "temp:channel": channel,
            "temp:chat_id": chat_id,
            "temp:message_id": message_id,
            "temp:sent_in_turn": "false",
            "temp:iteration_count": "0",
            "temp:tools_used": "",
            "temp:voice_reply": "true" if (metadata or {}).get("voice_reply") else "",
            # Flag for tools to know the bus loop is active and subagents
            # can safely deliver via send_message.  False in process_direct.
            "app:bus_active": "true" if self._running else "",
        }
        return state

    # ── MCP ──────────────────────────────────────────────────────────────────

    async def _connect_mcp(self) -> None:
        """Connect to configured MCP servers (one-time, lazy)."""
        if self._mcp_connected or self._mcp_connecting or not self._mcp_servers:
            return
        self._mcp_connecting = True
        try:
            from scorpion.adk.mcp_bridge import connect_mcp_servers_adk

            self._mcp_stack = AsyncExitStack()
            await self._mcp_stack.__aenter__()
            self._mcp_tools = await connect_mcp_servers_adk(
                self._mcp_servers, self._mcp_stack
            )
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

    async def close_mcp(self) -> None:
        """Close MCP connections."""
        if self._mcp_stack:
            try:
                await self._mcp_stack.aclose()
            except (RuntimeError, BaseExceptionGroup):
                pass
            self._mcp_stack = None

    # ── Agent construction ───────────────────────────────────────────────────

    def _make_agent(self, on_progress=None) -> LlmAgent:
        """Create the ADK LlmAgent with all tools and callbacks."""
        tools = list(ALL_TOOLS) + self._mcp_tools

        # Dynamic instruction function — reads bootstrap files + memory fresh each call
        ctx_builder = self.context

        def instruction_fn(_ctx) -> str:
            return ctx_builder.build_system_prompt()

        return LlmAgent(
            name="scorpion",
            model=self.model,
            instruction=instruction_fn,
            tools=tools,
            generate_content_config=types.GenerateContentConfig(
                temperature=self.temperature,
                max_output_tokens=self.max_tokens,
            ),
            before_agent_callback=make_before_agent_callback(),
            after_model_callback=make_after_model_callback(on_progress),
            before_tool_callback=make_before_tool_callback(on_progress),
            after_tool_callback=make_after_tool_callback(),
        )

    # ── Core agent run ───────────────────────────────────────────────────────

    async def _run_agent_adk(
        self,
        history: list[dict],
        current_message: str,
        channel: str,
        chat_id: str,
        message_id: str = "",
        media: list[str] | None = None,
        on_progress: Callable[..., Awaitable[None]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[str | None, list[str]]:
        """Run the ADK agent. Returns (final_content, tools_used)."""
        agent = self._make_agent(on_progress)
        runner = Runner(
            app_name="scorpion",
            agent=agent,
            session_service=self._session_service,
        )

        # Create a fresh ADK session with pre-populated state
        state = self._build_state(channel, chat_id, message_id, metadata=metadata)
        session = await self._session_service.create_session(
            app_name="scorpion",
            user_id=f"{channel}:{chat_id}",
            state=state,
        )

        # Prepopulate ADK session with conversation history
        # History messages are already in OpenAI format {role, content, ...}
        # We need to convert them to Gemini Content objects for ADK
        for msg in history:
            role = msg.get("role", "user")
            content_val = msg.get("content", "")
            if role == "system":
                continue  # system prompt is handled by instruction
            adk_role = "model" if role == "assistant" else "user"
            if role == "tool":
                continue  # tool results are part of the model flow
            if not content_val:
                continue
            text = content_val if isinstance(content_val, str) else json.dumps(content_val)
            history_content = types.Content(
                role=adk_role,
                parts=[types.Part(text=text)],
            )
            # Append directly to session history
            session.events = getattr(session, 'events', [])

        # Build the user message with optional runtime context + pending generation status
        runtime_ctx = ContextBuilder._build_runtime_context(channel, chat_id)
        session_key = f"{channel}:{chat_id}"
        pending_ctx = self._pending_results.build_context_block(session_key)
        context_parts = [p for p in (runtime_ctx, pending_ctx) if p]
        prefix = "\n\n".join(context_parts)
        user_text = f"{prefix}\n\n{current_message}" if prefix else current_message

        # Handle media (images and audio) by uploading to Gemini and referencing
        parts: list[types.Part] = []
        if media:
            import mimetypes
            from google import genai as google_genai
            
            # Create Gemini client for file upload
            api_key = getattr(self.provider, "api_key", "") or ""
            if not api_key:
                logger.error("Gemini API key not configured for media upload")
            else:
                media_client = google_genai.Client(api_key=api_key)
                
                for path in media:
                    p = Path(path)
                    mime, _ = mimetypes.guess_type(path)
                    if p.is_file() and mime:
                        try:
                            if mime.startswith("image/") or mime.startswith("audio/"):
                                logger.debug("Uploading media: {} ({})", path, mime)
                                # Upload file to Gemini
                                uploaded_file = media_client.files.upload(file=str(p))
                                # Wait for processing
                                while uploaded_file.state.name == "PROCESSING":
                                    await asyncio.sleep(2)
                                    uploaded_file = media_client.files.get(name=uploaded_file.name)
                                if uploaded_file.state.name == "FAILED":
                                    logger.error("File upload failed: {}", uploaded_file.state.name)
                                    continue
                                # Add as file data to the message
                                parts.append(types.Part.from_uri(
                                    file_uri=uploaded_file.uri,
                                    mime_type=mime
                                ))
                                logger.debug("Uploaded media: {} -> {}", path, uploaded_file.uri)
                        except Exception as upload_err:
                            logger.error("Failed to upload media {}: {}", path, upload_err)

        parts.append(types.Part(text=user_text))

        user_content = types.Content(role="user", parts=parts)

        # Run the agent
        clear_turn_tools()
        final_content = None
        try:
            async for event in runner.run_async(
                user_id=session.user_id,
                session_id=session.id,
                new_message=user_content,
            ):
                # Collect final text from model events
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.text:
                            text = self._strip_think(part.text)
                            if text:
                                final_content = text

                # Check for errors
                if event.error_message:
                    logger.error("ADK error: {}", event.error_message)
                    final_content = final_content or "Sorry, I encountered an error."

        except Exception as e:
            logger.exception("ADK agent run failed: {}", e)
            final_content = "Sorry, I encountered an error calling the AI model."

        # Get tools used from reliable module-level tracker
        tools_used = get_turn_tools()

        return final_content, tools_used

    # ── Bus-driven run loop ──────────────────────────────────────────────────

    async def run(self) -> None:
        """Run the agent loop, dispatching messages as tasks to stay responsive to /stop."""
        self._running = True
        await self._connect_mcp()
        logger.info("ADK agent loop started")

        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            if msg.content.strip().lower() == "/stop":
                await self._handle_stop(msg)
            else:
                task = asyncio.create_task(self._dispatch(msg))
                self._active_tasks.setdefault(msg.session_key, []).append(task)
                task.add_done_callback(
                    lambda t, k=msg.session_key: (
                        self._active_tasks.get(k, [])
                        and self._active_tasks[k].remove(t)
                        if t in self._active_tasks.get(k, [])
                        else None
                    )
                )

    async def _handle_stop(self, msg: InboundMessage) -> None:
        """Cancel all active tasks, subagents, and pending workers for the session."""
        tasks = self._active_tasks.pop(msg.session_key, [])
        cancelled = sum(1 for t in tasks if not t.done() and t.cancel())
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        sub_cancelled = await self.subagents.cancel_by_session(msg.session_key)
        worker_cancelled = await self._pending_results.cancel_by_session(msg.session_key)
        total = cancelled + sub_cancelled + worker_cancelled
        content = f"\u23f9 Stopped {total} task(s)." if total else "No active task to stop."
        await self.bus.publish_outbound(OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=content,
        ))

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

    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        logger.info("ADK agent loop stopping")

    # ── Message processing ───────────────────────────────────────────────────

    async def _process_message(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> OutboundMessage | None:
        """Process a single inbound message and return the response."""
        # System messages: parse origin from chat_id ("channel:chat_id")
        if msg.channel == "system":
            channel, chat_id = (
                msg.chat_id.split(":", 1)
                if ":" in msg.chat_id
                else ("cli", msg.chat_id)
            )
            logger.info("Processing system message from {}", msg.sender_id)
            key = f"{channel}:{chat_id}"
            session = self.sessions.get_or_create(key)
            history = session.get_history(max_messages=self.memory_window)
            final_content, tools_used = await self._run_agent_adk(
                history=history,
                current_message=msg.content,
                channel=channel,
                chat_id=chat_id,
                on_progress=on_progress,
            )
            self._save_turn_simple(session, msg.content, final_content, tools_used)
            self.sessions.save(session)
            return OutboundMessage(
                channel=channel,
                chat_id=chat_id,
                content=final_content or "Background task completed.",
            )

        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info("Processing message from {}:{}: {}", msg.channel, msg.sender_id, preview)

        key = session_key or msg.session_key
        session = self.sessions.get_or_create(key)

        # Slash commands
        cmd = msg.content.strip().lower()
        if cmd == "/new":
            return await self._handle_new_session(msg, session)
        if cmd == "/help":
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="\U0001f408 scorpion commands:\n/new \u2014 Start a new conversation\n/stop \u2014 Stop the current task\n/help \u2014 Show available commands",
            )

        # Memory consolidation check
        unconsolidated = len(session.messages) - session.last_consolidated
        if unconsolidated >= self.memory_window and session.key not in self._consolidating:
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

        # Build progress callback
        async def _bus_progress(content: str, *, tool_hint: bool = False) -> None:
            meta = dict(msg.metadata or {})
            meta["_progress"] = True
            meta["_tool_hint"] = tool_hint
            await self.bus.publish_outbound(OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id, content=content, metadata=meta,
            ))

        history = session.get_history(max_messages=self.memory_window)
        final_content, tools_used = await self._run_agent_adk(
            history=history,
            current_message=msg.content,
            channel=msg.channel,
            chat_id=msg.chat_id,
            message_id=msg.metadata.get("message_id", "") if msg.metadata else "",
            media=msg.media if msg.media else None,
            on_progress=on_progress or _bus_progress,
            metadata=msg.metadata,
        )

        if final_content is None:
            final_content = "I've completed processing but have no response to give."

        self._save_turn_simple(session, msg.content, final_content, tools_used)
        self.sessions.save(session)

        # Check if message tool already sent to the same channel
        # We check by looking at the most recent ADK session state
        # Since send_message sets temp:sent_in_turn in tool_context.state,
        # we need to check it. But since state is per-ADK-session and ephemeral,
        # we track it differently.
        # The send_message tool sets temp:sent_in_turn in tool_context.state.
        # After the run, we can check the session state.
        # For now, check if "send_message" was in tools_used for same channel
        if "send_message" in tools_used:
            # Message tool was used — check if it sent to the originating channel
            # The tool sets temp:sent_in_turn in state. We need to read it back.
            # Since the ADK session is ephemeral, just return None if message was sent
            return None

        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info("Response to {}:{}: {}", msg.channel, msg.sender_id, preview)
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content,
            metadata=msg.metadata or {},
        )

    async def _handle_new_session(self, msg: InboundMessage, session: Session) -> OutboundMessage:
        """Handle the /new command with memory archival."""
        # Cancel any pending generation workers for this session
        await self._pending_results.cancel_by_session(msg.session_key)
        lock = self._consolidation_locks.setdefault(session.key, asyncio.Lock())
        self._consolidating.add(session.key)
        try:
            async with lock:
                snapshot = session.messages[session.last_consolidated:]
                if snapshot:
                    temp = Session(key=session.key)
                    temp.messages = list(snapshot)
                    if not await self._consolidate_memory(temp, archive_all=True):
                        return OutboundMessage(
                            channel=msg.channel,
                            chat_id=msg.chat_id,
                            content="Memory archival failed, session not cleared. Please try again.",
                        )
        except Exception:
            logger.exception("/new archival failed for {}", session.key)
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="Memory archival failed, session not cleared. Please try again.",
            )
        finally:
            self._consolidating.discard(session.key)

        session.clear()
        self.sessions.save(session)
        self.sessions.invalidate(session.key)
        return OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content="New session started."
        )

    # ── Session persistence ──────────────────────────────────────────────────

    def _save_turn_simple(
        self,
        session: Session,
        user_message: str,
        assistant_response: str | None,
        tools_used: list[str],
    ) -> None:
        """Save a turn into the scorpion JSONL session."""
        from datetime import datetime

        now = datetime.now().isoformat()

        # Save user message
        session.messages.append({
            "role": "user",
            "content": user_message,
            "timestamp": now,
        })

        # Save assistant response
        if assistant_response:
            entry: dict[str, Any] = {
                "role": "assistant",
                "content": assistant_response,
                "timestamp": now,
            }
            if tools_used:
                entry["tools_used"] = tools_used
            session.messages.append(entry)

        session.updated_at = datetime.now()

    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        """Remove <think>...</think> blocks."""
        if not text:
            return None
        return re.sub(r"<think>[\s\S]*?</think>", "", text).strip() or None

    async def _consolidate_memory(self, session, archive_all: bool = False) -> bool:
        """Delegate to MemoryStore.consolidate()."""
        return await MemoryStore(self.workspace).consolidate(
            session,
            self.provider,
            self.model,
            archive_all=archive_all,
            memory_window=self.memory_window,
        )

    # ── Direct processing (CLI / cron) ───────────────────────────────────────

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """Process a message directly (for CLI or cron usage).

        In direct mode, generation tools run blocking (bus_active is false).
        After the main response, we also await any running workers and drain
        their results so the CLI gets file paths in a single response.
        """
        await self._connect_mcp()
        msg = InboundMessage(
            channel=channel, sender_id="user", chat_id=chat_id, content=content
        )
        response = await self._process_message(
            msg, session_key=session_key, on_progress=on_progress
        )
        result_text = response.content if response else ""

        # In CLI mode workers shouldn't be spawned (bus_active is false),
        # but if any were (e.g. tests), wait for them and append results.
        await self._pending_results.wait_running(session_key, timeout=300)
        finished = self._pending_results.drain(session_key)
        if finished:
            extras = []
            for r in finished:
                if r.status == "completed":
                    extras.extend(r.file_paths)
                else:
                    extras.append(f"[{r.kind} failed: {r.error}]")
            if extras:
                result_text = result_text + "\n" + "\n".join(extras) if result_text else "\n".join(extras)

        return result_text
