"""Agent loop: the core processing engine."""

import asyncio
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

import json_repair
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


class AgentLoop:
    """The core processing engine that handles message->tool->response flow."""

    _LOG_PREVIEW_LIMIT = 320
    _OUTBOUND_ACK_TIMEOUT_S = 15.0
    _CONSOLIDATION_COOLDOWN_S = 15 * 60
    _CONSOLIDATION_HARD_LIMIT = 30
    _SILENT_TRAILING_RE = re.compile(r"\[SILENT\][\s\.,!?;:，。！？；：、…~]*$")

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 50,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        memory_window: int = 50,
        compression_window_size: int = 12,
        brave_api_key: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        cron_service: "CronService | None" = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
        thinking: str | None = None,
        thinking_budget: int = 10000,
        effort: str | None = None,
        memory_daily_subdir: str = "",
        channels_config: "ChannelsConfig | None" = None,
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
        self.compression_window_size = max(1, compression_window_size)
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        self.restrict_to_workspace = restrict_to_workspace
        self.thinking = thinking
        self.thinking_budget = thinking_budget
        self.effort = effort

        self.context = ContextBuilder(workspace, memory_daily_subdir=memory_daily_subdir)
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
            mcp_servers=mcp_servers,
        )

        self._running = False
        self._consolidation_running_keys: set[str] = set()
        self._consolidation_pending_keys: set[str] = set()
        self._mcp_manager = None
        self._mcp_started = False
        if mcp_servers:
            from nanobot.agent.tools.mcp import MCPManager

            self._mcp_manager = MCPManager(mcp_servers)
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        self.tools.register(ReadFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
        self.tools.register(WriteFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
        self.tools.register(EditFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
        self.tools.register(ListDirTool(workspace=self.workspace, allowed_dir=allowed_dir))

        self.tools.register(
            ExecTool(
                working_dir=str(self.workspace),
                timeout=self.exec_config.timeout,
                restrict_to_workspace=self.restrict_to_workspace,
            )
        )

        self.tools.register(WebSearchTool(api_key=self.brave_api_key))
        self.tools.register(WebFetchTool())

        self.tools.register(MessageTool(send_callback=self._publish_outbound_with_ack))
        self.tools.register(SpawnTool(manager=self.subagents))

        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))

    async def _publish_outbound_with_ack(self, msg: OutboundMessage) -> None:
        """Publish outbound message and wait for channel delivery acknowledgement."""
        request_id = msg.request_id or f"out_{uuid.uuid4().hex[:12]}"
        msg.request_id = request_id
        waiter = self.bus.create_outbound_waiter(request_id)
        await self.bus.publish_outbound(msg)
        try:
            success, error = await asyncio.wait_for(waiter, timeout=self._OUTBOUND_ACK_TIMEOUT_S)
        except asyncio.TimeoutError as exc:
            self.bus.discard_outbound_waiter(request_id)
            raise RuntimeError(
                f"Message delivery acknowledgement timeout after {self._OUTBOUND_ACK_TIMEOUT_S:.0f}s"
            ) from exc
        if not success:
            raise RuntimeError(error or "Message delivery failed")

    async def run(self) -> None:
        """Run the agent loop, processing messages from the bus."""
        self._running = True
        logger.info("Agent loop started")

        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
                try:
                    response = await self._process_message(msg)
                    if response:
                        await self.bus.publish_outbound(response)
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    await self.bus.publish_outbound(
                        OutboundMessage(
                            channel=msg.channel,
                            chat_id=msg.chat_id,
                            content=f"Sorry, I encountered an error: {str(e)}",
                            metadata=msg.metadata,
                        )
                    )
                finally:
                    try:
                        await self.bus.complete_inbound_turn(msg)
                    except Exception as e:
                        logger.error(f"Error completing inbound turn: {e}")
            except asyncio.TimeoutError:
                continue

    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        logger.info("Agent loop stopping")

    async def start_mcp(self) -> None:
        """Connect MCP servers and register their tools."""
        if not self._mcp_manager or self._mcp_started:
            return
        tools = await self._mcp_manager.start()
        for tool in tools:
            self.tools.register(tool)
        self._mcp_started = True
        logger.info(
            "MCP: registered {} tools from {} servers",
            len(tools),
            len(self._mcp_manager.server_names),
        )

    async def stop_mcp(self) -> None:
        """Unregister MCP tools and disconnect servers."""
        if not self._mcp_manager or not self._mcp_started:
            return
        for name in list(self.tools._tools.keys()):
            if name.startswith("mcp__"):
                self.tools.unregister(name)
        await self._mcp_manager.stop()
        self._mcp_started = False

    async def close_mcp(self) -> None:
        """Backward-compatible alias for MCP shutdown."""
        await self.stop_mcp()

    def _set_tool_context(
        self,
        channel: str,
        chat_id: str,
        context: dict[str, Any] | str | int | None = None,
    ) -> None:
        """Update context for tools that need routing info."""
        message_tool = self.tools.get("message")
        if isinstance(message_tool, MessageTool):
            message_tool.set_context(channel, chat_id, context)

        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(channel, chat_id)

        cron_tool = self.tools.get("cron")
        if isinstance(cron_tool, CronTool):
            cron_tool.set_context(channel, chat_id)

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
            val = next(iter(tc.arguments.values()), None) if tc.arguments else None
            if not isinstance(val, str):
                return tc.name
            return f'{tc.name}("{val[:40]}…")' if len(val) > 40 else f'{tc.name}("{val}")'
        return ", ".join(_fmt(tc) for tc in tool_calls)

    @staticmethod
    def _normalize_timestamp(timestamp: datetime | str | None) -> str | None:
        """Convert message timestamp to JSON-serializable ISO text."""
        if timestamp is None:
            return None
        if isinstance(timestamp, datetime):
            return timestamp.isoformat()
        return str(timestamp)

    @staticmethod
    def _save_session_with_tools(
        session,
        user_content: str,
        final_content: str,
        tool_use_log: list[tuple[str, str, str]],
        user_timestamp: datetime | str | None = None,
    ) -> None:
        """Save user + assistant messages, with tool_use_log as a virtual tool call."""
        user_ts = AgentLoop._normalize_timestamp(user_timestamp)
        user_kwargs = {"timestamp": user_ts} if user_ts else {}
        session.add_message("user", user_content, **user_kwargs)

        if tool_use_log:
            lines = []
            tools_used = []
            for i, (name, args, result) in enumerate(tool_use_log, 1):
                lines.append(f"{i}. {name}({args}) -> {result}")
                tools_used.append(name)
            summary_text = "\n".join(lines)
            logger.info(f"Tool use summary:\n{summary_text}")
            call_id = f"toolsum_{uuid.uuid4().hex[:12]}"
            session.add_message(
                "assistant",
                final_content,
                tool_calls=[
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": "_tool_use_summary", "arguments": "{}"},
                    }
                ],
                tools_used=tools_used,
            )
            session.add_message("tool", summary_text, tool_call_id=call_id, name="_tool_use_summary")
        else:
            session.add_message("assistant", final_content)

    @staticmethod
    def _contains_silent_marker(content: str | None) -> bool:
        """Return True if model output requests no outbound reply."""
        return bool(content) and bool(AgentLoop._SILENT_TRAILING_RE.search(content))

    @staticmethod
    def _strip_silent_marker(content: str | None) -> str | None:
        """Remove trailing SILENT marker(s) from user-visible text."""
        if content is None:
            return None
        if not AgentLoop._SILENT_TRAILING_RE.search(content):
            return content
        cleaned = content
        while AgentLoop._SILENT_TRAILING_RE.search(cleaned):
            cleaned = AgentLoop._SILENT_TRAILING_RE.sub("", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        return cleaned

    @staticmethod
    def _log_token_usage(usage: dict[str, int] | None) -> None:
        """Log token/caching usage consistently across loops."""
        if not usage:
            return
        cache_create = usage.get("cache_creation_input_tokens", 0)
        cache_read = usage.get("cache_read_input_tokens", 0)
        prompt = usage.get("prompt_tokens", 0)
        completion = usage.get("completion_tokens", 0)
        total = usage.get("total_tokens", 0)
        if cache_create + cache_read > 0:
            hit_rate = cache_read / (cache_create + cache_read) * 100
            logger.info(
                "Token usage: prompt={}, completion={}, total={} | cache: create={}, read={}, hit_rate={:.1f}%",
                prompt,
                completion,
                total,
                cache_create,
                cache_read,
                hit_rate,
            )
        else:
            logger.info(
                "Token usage: prompt={}, completion={}, total={} | cache: n/a",
                prompt,
                completion,
                total,
            )

    def _compression_keep_count(self) -> int:
        """How many recent messages are always kept out of consolidation."""
        return max(1, self.memory_window // 2)

    @staticmethod
    def _parse_iso_datetime(value: str | None) -> datetime | None:
        """Parse an ISO datetime string safely."""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def _should_schedule_consolidation(self, session: Session) -> bool:
        """Return True when consolidation should run for this session."""
        # TODO: consolidation disabled — LLM-based compression to be redesigned
        return False
        keep_count = self._compression_keep_count()
        total_messages = len(session.messages)
        if total_messages <= keep_count:
            return False

        compress_end = total_messages - keep_count
        delta = compress_end - session.last_consolidated
        if delta <= 0:
            return False

        if delta >= self._CONSOLIDATION_HARD_LIMIT:
            return True
        if delta >= self.compression_window_size:
            return True

        last_at = self._parse_iso_datetime(session.last_consolidated_at)
        if not last_at:
            return False
        return (datetime.now() - last_at).total_seconds() >= self._CONSOLIDATION_COOLDOWN_S

    def _schedule_consolidation(self, session: Session, reason: str) -> None:
        """Schedule consolidation with per-session de-duplication."""
        key = session.key
        if key in self._consolidation_running_keys:
            self._consolidation_pending_keys.add(key)
            logger.debug("Memory consolidation already running for {} (reason={})", key, reason)
            return

        self._consolidation_running_keys.add(key)
        logger.debug("Memory consolidation scheduled for {} (reason={})", key, reason)

        async def _run_for_session() -> None:
            try:
                await self._consolidate_memory(session)
            finally:
                self._consolidation_running_keys.discard(key)
                if key in self._consolidation_pending_keys:
                    self._consolidation_pending_keys.discard(key)
                    if self._should_schedule_consolidation(session):
                        self._schedule_consolidation(session, reason="pending")

        asyncio.create_task(_run_for_session())

    async def _run_agent_loop(
        self, initial_messages: list[dict],
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> tuple[str, str, list[tuple[str, str, str]]]:
        """Run the agent iteration loop and return final content + metadata."""
        messages = initial_messages
        iteration = 0
        final_content: str | None = None
        last_finish_reason = "unknown"
        tool_use_log: list[tuple[str, str, str]] = []
        stashed_content: str | None = None

        while iteration < self.max_iterations:
            iteration += 1
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                thinking=self.thinking,
                thinking_budget=self.thinking_budget,
                effort=self.effort,
            )
            last_finish_reason = response.finish_reason or "unknown"
            self._log_token_usage(response.usage)

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
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages,
                    response.content,
                    tool_call_dicts,
                    reasoning_content=response.reasoning_content,
                )

                if response.content and response.content.strip():
                    stashed_content = response.content
                    logger.info("Stashed content from tool_call response: {}", response.content[:100])

                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    logger.info("Tool call: {}({})", tool_call.name, args_str[:200])
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    messages = self.context.add_tool_result(messages, tool_call.id, tool_call.name, result)
                    tool_use_log.append(
                        (
                            tool_call.name,
                            args_str[:100] + ("..." if len(args_str) > 100 else ""),
                            (result[:200] + "...(truncated)") if len(result) > 200 else result,
                        )
                    )
                continue

            if response.content is None or response.content.strip() == "":
                sent_message = any(name == "message" for name, _, _ in tool_use_log)
                if sent_message:
                    logger.info(
                        "Model returned empty content after message tool call; normal completion "
                        "(finish_reason={}, iteration={}/{})",
                        last_finish_reason,
                        iteration,
                        self.max_iterations,
                    )
                    final_content = ""
                elif stashed_content:
                    logger.info(
                        "Model returned empty content; using stashed content from tool_call response: {}",
                        stashed_content[:100],
                    )
                    final_content = stashed_content
                else:
                    logger.warning(
                        "Model returned empty/blank content without tool calls "
                        "(finish_reason={}, iteration={}/{})",
                        last_finish_reason,
                        iteration,
                        self.max_iterations,
                    )
                    final_content = (
                        "I could not produce a final response because the model returned empty/blank content "
                        f"(finish_reason={last_finish_reason}, iteration={iteration}/{self.max_iterations}). "
                        "Please retry."
                    )
            else:
                final_content = self._strip_think(response.content)
                break

        if final_content is None:
            logger.warning(
                "Agent loop hit max iterations without final response "
                "(max_iterations={}, last_finish_reason={})",
                self.max_iterations,
                last_finish_reason,
            )
            final_content = (
                "I stopped before a final response because the tool-call loop hit the iteration limit "
                f"({self.max_iterations}). Last finish_reason={last_finish_reason}. "
                "Please retry with a narrower request or increase agents.defaults.max_tool_iterations."
            )

        return final_content, last_finish_reason, tool_use_log

    async def _process_message(
        self, msg: InboundMessage, session_key: str | None = None,
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> OutboundMessage | None:
        """Process a single inbound message."""
        if msg.channel == "system":
            return await self._process_system_message(msg)

        preview = msg.content[: self._LOG_PREVIEW_LIMIT]
        if len(msg.content) > self._LOG_PREVIEW_LIMIT:
            preview += "...(truncated)"
        logger.info("Processing message from {}:{}: {}", msg.channel, msg.sender_id, preview)

        key = session_key or msg.session_key
        session = self.sessions.get_or_create(key)

        cmd = msg.content.strip().lower()
        if cmd == "/new":
            messages_to_archive = session.messages.copy()
            session.clear()
            self.sessions.save(session)
            self.sessions.invalidate(session.key)

            async def _consolidate_and_cleanup() -> None:
                temp_session = Session(key=session.key)
                temp_session.messages = messages_to_archive
                await self._consolidate_memory(
                    temp_session,
                    archive_all=True,
                    persist_session=False,
                )
            asyncio.create_task(_consolidate_and_cleanup())
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="New session started. Memory consolidation in progress.",
            )

        if cmd == "/help":
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="🐈 nanobot commands:\n/new — Start a new conversation\n/help — Show available commands",
            )

        self._set_tool_context(msg.channel, msg.chat_id, msg.metadata)
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.start_turn()
        messages = self.context.build_messages(
            history=session.get_history(max_messages=self.memory_window),
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel,
            chat_id=msg.chat_id,
            current_timestamp=msg.timestamp,
            current_metadata=msg.metadata if msg.metadata else None,
        )

        async def _bus_progress(content: str, *, tool_hint: bool = False) -> None:
            progress_metadata = dict(msg.metadata or {})
            progress_metadata["_progress"] = True
            progress_metadata["_tool_hint"] = tool_hint
            progress_metadata["message_type"] = "progress"
            progress_metadata["progress_notice"] = True
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=content,
                    metadata=progress_metadata,
                )
            )

        final_content, _, tool_use_log = await self._run_agent_loop(
            messages, on_progress=on_progress or _bus_progress,
        )

        silent_requested = self._contains_silent_marker(final_content)
        final_content = self._strip_silent_marker(final_content)

        if final_content is None:
            final_content = "I've completed processing but have no response to give."

        self._save_session_with_tools(
            session,
            msg.content,
            final_content,
            tool_use_log,
            user_timestamp=msg.timestamp,
        )
        self.sessions.save(session)
        if self._should_schedule_consolidation(session):
            self._schedule_consolidation(session, reason="post_message")

        if silent_requested:
            logger.info(
                "Suppress outbound message for {}:{} due to [SILENT] marker",
                msg.channel,
                msg.sender_id,
            )
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="",
                silent=True,
            )

        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool) and message_tool._sent_in_turn:
                logger.info(
                    "No outbound message needed for {}:{} (already sent via tool)",
                    msg.channel,
                    msg.sender_id,
                )
                return None

        if not final_content:
            logger.info(
                "No outbound message needed for {}:{} (already sent via tool)",
                msg.channel,
                msg.sender_id,
            )
            return None

        preview = final_content[: self._LOG_PREVIEW_LIMIT]
        if len(final_content) > self._LOG_PREVIEW_LIMIT:
            preview += "...(truncated)"
        logger.info("Response to {}:{}: {}", msg.channel, msg.sender_id, preview)

        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content,
            metadata=msg.metadata or {},
        )

    async def _process_system_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """Process a system message (e.g., subagent announce)."""
        logger.info("Processing system message from {}", msg.sender_id)

        if ":" in msg.chat_id:
            origin_channel, origin_chat_id = msg.chat_id.split(":", 1)
        else:
            origin_channel = "cli"
            origin_chat_id = msg.chat_id

        session_key = f"{origin_channel}:{origin_chat_id}"
        session = self.sessions.get_or_create(session_key)

        self._set_tool_context(origin_channel, origin_chat_id)
        messages = self.context.build_messages(
            history=session.get_history(max_messages=self.memory_window),
            current_message=msg.content,
            channel=origin_channel,
            chat_id=origin_chat_id,
            current_timestamp=msg.timestamp,
            current_metadata=msg.metadata if msg.metadata else None,
        )

        final_content, last_finish_reason, tool_use_log = await self._run_agent_loop(messages)

        if final_content is None:
            logger.warning(
                "System-message loop ended without summary "
                "(max_iterations={}, last_finish_reason={})",
                self.max_iterations,
                last_finish_reason,
            )
            final_content = (
                "Background task completed, but summary generation returned no text "
                f"(last_finish_reason={last_finish_reason})."
            )

        silent_requested = self._contains_silent_marker(final_content)
        final_content = self._strip_silent_marker(final_content)
        if final_content is None:
            final_content = "Background task completed."

        self._save_session_with_tools(
            session,
            f"[System: {msg.sender_id}] {msg.content}",
            final_content,
            tool_use_log,
            user_timestamp=msg.timestamp,
        )
        self.sessions.save(session)
        if self._should_schedule_consolidation(session):
            self._schedule_consolidation(session, reason="post_system_message")

        if silent_requested:
            logger.info("Suppress outbound system message for {} due to [SILENT] marker", msg.sender_id)
            return OutboundMessage(
                channel=origin_channel,
                chat_id=origin_chat_id,
                content="",
                silent=True,
            )

        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool) and message_tool._sent_in_turn:
                logger.info(
                    "No outbound message needed for system message from {} (already sent via tool)",
                    msg.sender_id,
                )
                return None

        if not final_content:
            logger.info(
                "No outbound message needed for system message from {} (already sent via tool)",
                msg.sender_id,
            )
            return None

        return OutboundMessage(channel=origin_channel, chat_id=origin_chat_id, content=final_content)

    async def _consolidate_memory(
        self,
        session: Session,
        archive_all: bool = False,
        persist_session: bool = True,
    ) -> None:
        """Consolidate old messages into MEMORY.md + HISTORY.md."""
        memory = MemoryStore(self.workspace)
        total_messages = len(session.messages)

        if archive_all:
            old_messages = session.messages
            keep_count = 0
            next_last_consolidated = 0
            logger.info(
                "Memory consolidation (archive_all): {} total messages archived",
                total_messages,
            )
        else:
            keep_count = self._compression_keep_count()
            if total_messages <= keep_count:
                logger.debug(
                    "Session {}: No consolidation needed (messages={}, keep={})",
                    session.key,
                    total_messages,
                    keep_count,
                )
                return

            compress_end = total_messages - keep_count
            delta = compress_end - session.last_consolidated
            if delta <= 0:
                logger.debug(
                    "Session {}: No new messages to consolidate (last_consolidated={}, total={})",
                    session.key,
                    session.last_consolidated,
                    total_messages,
                )
                return

            old_messages = session.messages[session.last_consolidated:compress_end]
            if not old_messages:
                return
            next_last_consolidated = compress_end
            logger.info(
                "Memory consolidation started: {} total, {} new to consolidate, {} keep, threshold={}",
                total_messages,
                len(old_messages),
                keep_count,
                self.compression_window_size,
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
                    {
                        "role": "system",
                        "content": "You are a memory consolidation agent. Respond only with valid JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            text = (response.content or "").strip()
            if not text:
                logger.warning("Memory consolidation: LLM returned empty response, skipping")
                return
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            result = json_repair.loads(text)
            if not isinstance(result, dict):
                logger.warning(
                    "Memory consolidation: unexpected response type, skipping. Response: {}",
                    text[:200],
                )
                return

            if entry := result.get("history_entry"):
                memory.append_history(entry)
            if update := result.get("memory_update"):
                if update != current_memory:
                    memory.write_long_term(update)

            session.last_consolidated = next_last_consolidated
            session.last_consolidated_at = datetime.now().isoformat()
            if persist_session and not archive_all:
                self.sessions.save(session)
            logger.info(
                "Memory consolidation done: {} messages, last_consolidated={}, last_consolidated_at={}",
                total_messages,
                session.last_consolidated,
                session.last_consolidated_at,
            )
        except Exception as e:
            logger.error(f"Memory consolidation failed: {e}")

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> str:
        """Process a message directly (for CLI or cron usage)."""
        await self.start_mcp()
        msg = InboundMessage(channel=channel, sender_id="user", chat_id=chat_id, content=content)
        response = await self._process_message(msg, session_key=session_key, on_progress=on_progress)
        return response.content if response else ""
