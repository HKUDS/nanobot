"""Agent loop: the core processing engine."""

from __future__ import annotations

import asyncio
import json
import re
from contextlib import AsyncExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

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
    from nanobot.config.schema import ChannelsConfig, ExecToolConfig, HonchoConfig
    from nanobot.cron.service import CronService
    from nanobot.honcho.session import HonchoSessionManager


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
        max_iterations: int = 40,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        memory_window: int = 100,
        brave_api_key: str | None = None,
        exec_config: ExecToolConfig | None = None,
        cron_service: CronService | None = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        honcho_config: HonchoConfig | None = None,
        mcp_servers: dict | None = None,
        channels_config: ChannelsConfig | None = None,
    ):
        from nanobot.config.schema import ExecToolConfig
        self.honcho_config = honcho_config
        self.bus = bus
        self.channels_config = channels_config
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
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            brave_api_key=brave_api_key,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
        )

        self._running = False
        self._honcho: HonchoSessionManager | None = None
        self._honcho_migrated: set[str] = set()
        self._mcp_servers = mcp_servers or {}
        self._mcp_stack: AsyncExitStack | None = None
        self._mcp_connected = False
        self._mcp_connecting = False
        self._consolidating: set[str] = set()
        self._consolidation_tasks: set[asyncio.Task] = set()
        self._consolidation_locks: dict[str, asyncio.Lock] = {}
        self._register_default_tools()

    # ── Honcho integration ──────────────────────────────────────────

    @property
    def honcho_active(self) -> bool:
        """True when Honcho is initialized and ready."""
        return self._honcho is not None

    def _honcho_set_context(self, session_key: str) -> None:
        """Set session context on Honcho tools and ensure the Honcho session exists."""
        if not self.honcho_active:
            return
        for tool_name in ("query_user_context",):
            tool = self.tools.get(tool_name)
            if tool and hasattr(tool, "set_context"):
                tool.set_context(session_key)
        self._honcho.get_or_create(session_key)
        if session_key not in self._honcho_migrated:
            self._honcho_migrated.add(session_key)
            self._maybe_migrate_local_session(session_key)

    def _maybe_migrate_local_session(self, session_key: str) -> None:
        """Auto-migrate local data to Honcho on first activation per session key."""
        honcho_session = self._honcho.get_or_create(session_key)
        if honcho_session.messages:
            return

        migrated_anything = False

        # 1. Migrate JSONL session messages
        local_session = self.sessions.get_or_create(session_key)
        real_messages = [m for m in local_session.messages if m.get("role") in ("user", "assistant")]
        if real_messages:
            logger.info(f"Migrating {len(real_messages)} local messages to Honcho for {session_key}")
            ok = self._honcho.migrate_local_history(session_key, real_messages)
            if ok:
                sessions_dir = Path.home() / ".nanobot" / "sessions"
                from nanobot.utils.helpers import safe_filename
                safe_key = safe_filename(session_key.replace(":", "_"))
                src = sessions_dir / f"{safe_key}.jsonl"
                if src.exists():
                    archive_dir = sessions_dir / "migrated"
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    src.rename(archive_dir / src.name)
                    logger.info(f"Archived {src.name} to sessions/migrated/")
                migrated_anything = True
            else:
                logger.warning(f"Session migration failed for {session_key}, will retry next time")

        # 2. Migrate MEMORY.md + HISTORY.md (if they exist)
        memory_dir = self.workspace / "memory"
        if memory_dir.exists() and any(memory_dir.iterdir()):
            if self._honcho.migrate_memory_files(session_key, self.workspace):
                archive_dir = memory_dir / "migrated"
                archive_dir.mkdir(parents=True, exist_ok=True)
                for f in ("MEMORY.md", "HISTORY.md"):
                    src = memory_dir / f
                    if src.exists():
                        src.rename(archive_dir / src.name)
                        logger.info(f"Archived {f} to memory/migrated/")
                migrated_anything = True

        if migrated_anything:
            logger.info(f"Local data migration to Honcho complete for {session_key}")

    def _honcho_prefetch(self, session_key: str, user_message: str) -> str:
        """Fetch user context from Honcho for system prompt injection."""
        if not self.honcho_active or not self.honcho_config or not self.honcho_config.prefetch:
            return ""
        try:
            ctx = self._honcho.get_prefetch_context(session_key, user_message=user_message)
            parts = []
            if ctx.get("representation"):
                parts.append(f"User profile: {ctx['representation']}")
            if ctx.get("card"):
                parts.append(f"User context: {ctx['card']}")
            return "\n\n# Honcho User Context\n\n" + "\n\n".join(parts) if parts else ""
        except Exception as e:
            logger.warning(f"Honcho prefetch failed: {e}")
            return ""

    def _honcho_sync(self, session_key: str, user_content: str, assistant_content: str) -> None:
        """Sync a message pair to Honcho storage."""
        if not self.honcho_active:
            return
        try:
            honcho_session = self._honcho.get_or_create(session_key)
            honcho_session.add_message("user", user_content)
            honcho_session.add_message("assistant", assistant_content)
            self._honcho.save(honcho_session)
        except Exception as e:
            logger.warning(f"Honcho sync failed: {e}")

    # ── Tool & MCP ──────────────────────────────────────────────────

    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        for cls in (ReadFileTool, WriteFileTool, EditFileTool, ListDirTool):
            self.tools.register(cls(workspace=self.workspace, allowed_dir=allowed_dir))
        self.tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            restrict_to_workspace=self.restrict_to_workspace,
        ))
        self.tools.register(WebSearchTool(api_key=self.brave_api_key))
        self.tools.register(WebFetchTool())
        self.tools.register(MessageTool(send_callback=self.bus.publish_outbound))
        self.tools.register(SpawnTool(manager=self.subagents))
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))

        # Honcho tools (opt-in: requires honcho.enabled + HONCHO_API_KEY)
        if self.honcho_config and self.honcho_config.enabled:
            import os
            if os.environ.get("HONCHO_API_KEY"):
                try:
                    from nanobot.honcho.client import get_honcho_client, HonchoClientConfig
                    from nanobot.honcho.session import HonchoSessionManager
                    from nanobot.agent.tools.honcho import HonchoTool

                    client_config = HonchoClientConfig(
                        workspace_id=self.honcho_config.workspace_id,
                        api_key=os.environ["HONCHO_API_KEY"],
                        environment=self.honcho_config.environment,
                    )
                    get_honcho_client(client_config)
                    self._honcho = HonchoSessionManager(
                        context_tokens=self.honcho_config.context_tokens,
                    )
                    self.tools.register(HonchoTool(session_manager=self._honcho))
                    logger.info("Honcho tools registered (query_user_context)")
                except ImportError:
                    logger.warning("Honcho enabled but honcho-ai not installed. Run: nanobot honcho enable")
                except Exception as e:
                    logger.warning(f"Failed to initialize Honcho: {e}")

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
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.set_context(channel, chat_id, message_id)

        if spawn_tool := self.tools.get("spawn"):
            if isinstance(spawn_tool, SpawnTool):
                spawn_tool.set_context(channel, chat_id)

        if cron_tool := self.tools.get("cron"):
            if isinstance(cron_tool, CronTool):
                cron_tool.set_context(channel, chat_id)

    # ── Agent iteration loop ────────────────────────────────────────

    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        """Remove <think>...</think> blocks that some models embed in content."""
        if not text:
            return None
        return re.sub(r"<think>[\s\S]*?</think>", "", text).strip() or None

    @staticmethod
    def _tool_hint(tool_calls: list) -> str:
        """Format tool calls as concise hint, e.g. 'web_search("query")'."""
        def _fmt(tc):
            val = next(iter(tc.arguments.values()), None) if tc.arguments else None
            if not isinstance(val, str):
                return tc.name
            return f'{tc.name}("{val[:40]}...")' if len(val) > 40 else f'{tc.name}("{val}")'
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

            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            if response.has_tool_calls:
                if on_progress:
                    clean = self._strip_think(response.content)
                    if clean:
                        await on_progress(clean)
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
                final_content = self._strip_think(response.content)
                break

        if final_content is None and iteration >= self.max_iterations:
            logger.warning("Max iterations ({}) reached", self.max_iterations)
            final_content = (
                f"I reached the maximum number of tool call iterations ({self.max_iterations}) "
                "without completing the task. You can try breaking the task into smaller steps."
            )

        return final_content, tools_used, messages

    # ── Main loop ───────────────────────────────────────────────────

    async def run(self) -> None:
        """Run the agent loop, processing messages from the bus."""
        self._running = True
        await self._connect_mcp()
        logger.info("Agent loop started")

        while self._running:
            try:
                msg = await asyncio.wait_for(
                    self.bus.consume_inbound(),
                    timeout=1.0
                )

                try:
                    response = await self._process_message(msg)
                    if response is not None:
                        await self.bus.publish_outbound(response)
                    elif msg.channel == "cli":
                        await self.bus.publish_outbound(OutboundMessage(
                            channel=msg.channel, chat_id=msg.chat_id, content="", metadata=msg.metadata or {},
                        ))
                except Exception as e:
                    logger.error("Error processing message: {}", e)
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=f"Sorry, I encountered an error: {str(e)}"
                    ))
            except asyncio.TimeoutError:
                continue

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

    def _get_consolidation_lock(self, session_key: str) -> asyncio.Lock:
        lock = self._consolidation_locks.get(session_key)
        if lock is None:
            lock = asyncio.Lock()
            self._consolidation_locks[session_key] = lock
        return lock

    def _prune_consolidation_lock(self, session_key: str, lock: asyncio.Lock) -> None:
        """Drop lock entry if no longer in use."""
        if not lock.locked():
            self._consolidation_locks.pop(session_key, None)

    # ── Message processing ──────────────────────────────────────────

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
            self._honcho_set_context(key)
            history = session.get_history(max_messages=self.memory_window)
            messages = self.context.build_messages(
                history=history,
                current_message=msg.content, channel=channel, chat_id=chat_id,
            )
            final_content, _, all_msgs = await self._run_agent_loop(messages)
            self._save_turn(session, all_msgs, 1 + len(history))
            if self.honcho_active:
                self._honcho_sync(key, msg.content, final_content or "")
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
            lock = self._get_consolidation_lock(session.key)
            self._consolidating.add(session.key)
            try:
                async with lock:
                    snapshot = session.messages[session.last_consolidated:]
                    if snapshot:
                        temp = Session(key=session.key)
                        temp.messages = list(snapshot)
                        if not await self._consolidate_memory(temp, archive_all=True):
                            return OutboundMessage(
                                channel=msg.channel, chat_id=msg.chat_id,
                                content="Memory archival failed, session not cleared. Please try again.",
                            )
            except Exception:
                logger.exception("/new archival failed for {}", session.key)
                return OutboundMessage(
                    channel=msg.channel, chat_id=msg.chat_id,
                    content="Memory archival failed, session not cleared. Please try again.",
                )
            finally:
                self._consolidating.discard(session.key)
                self._prune_consolidation_lock(session.key, lock)

            session.clear()
            self.sessions.save(session)
            self.sessions.invalidate(session.key)
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content="New session started.")
        if cmd == "/help":
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content="nanobot commands:\n/new — Start a new conversation\n/help — Show available commands")

        # Memory consolidation
        if self.honcho_active and len(session.messages) > self.memory_window:
            # Honcho handles persistence; just trim locally
            keep_count = min(10, max(2, self.memory_window // 2))
            session.messages = session.messages[-keep_count:]
            self.sessions.save(session)
        else:
            unconsolidated = len(session.messages) - session.last_consolidated
            if (unconsolidated >= self.memory_window and session.key not in self._consolidating):
                self._consolidating.add(session.key)
                lock = self._get_consolidation_lock(session.key)

                async def _consolidate_and_unlock():
                    try:
                        async with lock:
                            await self._consolidate_memory(session)
                    finally:
                        self._consolidating.discard(session.key)
                        self._prune_consolidation_lock(session.key, lock)
                        _task = asyncio.current_task()
                        if _task is not None:
                            self._consolidation_tasks.discard(_task)

                _task = asyncio.create_task(_consolidate_and_unlock())
                self._consolidation_tasks.add(_task)

        self._set_tool_context(msg.channel, msg.chat_id, msg.metadata.get("message_id"))
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.start_turn()

        # Honcho: set tool contexts + prefetch user context
        self._honcho_set_context(msg.session_key)
        honcho_context = self._honcho_prefetch(msg.session_key, msg.content)

        history = session.get_history(max_messages=self.memory_window)
        initial_messages = self.context.build_messages(
            history=history,
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel, chat_id=msg.chat_id,
        )

        # Inject Honcho context into system prompt
        if honcho_context and initial_messages and initial_messages[0].get("role") == "system":
            initial_messages[0]["content"] += honcho_context

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

        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info("Response to {}:{}: {}", msg.channel, msg.sender_id, preview)

        self._save_turn(session, all_msgs, 1 + len(history))

        if self.honcho_active:
            self._honcho_sync(msg.session_key, msg.content, final_content)
        self.sessions.save(session)

        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool) and message_tool._sent_in_turn:
                return None

        return OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=final_content,
            metadata=msg.metadata or {},
        )

    _TOOL_RESULT_MAX_CHARS = 500

    def _save_turn(self, session: Session, messages: list[dict], skip: int) -> None:
        """Save new-turn messages into session, truncating large tool results."""
        from datetime import datetime
        for m in messages[skip:]:
            entry = {k: v for k, v in m.items() if k != "reasoning_content"}
            if entry.get("role") == "tool" and isinstance(entry.get("content"), str):
                content = entry["content"]
                if len(content) > self._TOOL_RESULT_MAX_CHARS:
                    entry["content"] = content[:self._TOOL_RESULT_MAX_CHARS] + "\n... (truncated)"
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
