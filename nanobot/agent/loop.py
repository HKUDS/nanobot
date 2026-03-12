"""Agent loop: the core processing engine."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import sys
import weakref
from contextlib import AsyncExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

from loguru import logger

from nanobot.agent.context import ContextBuilder
from nanobot.agent.context_editor import ContextEditor
from nanobot.agent.memory import MemoryConsolidator
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
    from nanobot.config.schema import ChannelsConfig, ContextEditingConfig, ExecToolConfig
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

    _TOOL_RESULT_MAX_CHARS = 16_000

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
        reasoning_effort: str | None = None,
        context_window_tokens: int = 65_536,
        brave_api_key: str | None = None,
        web_proxy: str | None = None,
        exec_config: ExecToolConfig | None = None,
        cron_service: CronService | None = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
        context_editing: ContextEditingConfig | None = None,
        channels_config: ChannelsConfig | None = None,
    ):
        from nanobot.config.schema import ContextEditingConfig, ExecToolConfig
        self.bus = bus
        self.channels_config = channels_config
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.memory_window = memory_window
        self.reasoning_effort = reasoning_effort
        self.context_window_tokens = context_window_tokens
        self.brave_api_key = brave_api_key
        self.web_proxy = web_proxy
        self.exec_config = exec_config or ExecToolConfig()
        self.context_editing = context_editing or ContextEditingConfig()
        self.cron_service = cron_service
        self.restrict_to_workspace = restrict_to_workspace

        self.context = ContextBuilder(workspace)
        self.context_editor = ContextEditor(self.context_editing)
        self.sessions = session_manager or SessionManager(workspace)
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            brave_api_key=brave_api_key,
            web_proxy=self.web_proxy,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
        )

        self._running = False
        self._mcp_servers = mcp_servers or {}
        self._mcp_stack: AsyncExitStack | None = None
        self._mcp_connected = False
        self._mcp_connecting = False
        self._session_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()
        self._active_tasks: dict[str, list[asyncio.Task]] = {}  # session_key -> tasks
        self.memory_consolidator = MemoryConsolidator(
            workspace=workspace,
            provider=provider,
            model=self.model,
            sessions=self.sessions,
            context_window_tokens=context_window_tokens,
            build_messages=self.context.build_messages,
            get_tool_definitions=self.tools.get_definitions,
        )
        self._register_default_tools()

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

    @staticmethod
    def _is_retryable_llm_error(content: str | None) -> bool:
        """Detect transient upstream/model gateway errors worth retrying."""
        if not content:
            return False
        text = content.lower()
        retryable_markers = (
            "error code: 502",
            "error code: 503",
            "bad gateway",
            "service unavailable",
            "timeout",
            "timed out",
            "connection reset",
            "temporarily unavailable",
        )
        return any(marker in text for marker in retryable_markers)

    async def _run_agent_loop(
        self,
        initial_messages: list[dict],
        on_progress: Callable[..., Awaitable[None]] | None = None,
        stream_text_progress: bool = False,
    ) -> tuple[str | None, list[str], list[dict]]:
        """Run the agent iteration loop. Returns (final_content, tools_used, messages)."""
        messages = initial_messages
        iteration = 0
        final_content = None
        tools_used: list[str] = []
        streamed_text = ""
        last_stream_preview = ""

        async def _on_text_delta(delta: str) -> None:
            nonlocal streamed_text, last_stream_preview
            if not on_progress or not stream_text_progress or not delta:
                return
            streamed_text += delta
            clean = self._strip_think(streamed_text)
            if not clean or clean == last_stream_preview:
                return
            last_stream_preview = clean
            await on_progress(clean, replace=True)

        while iteration < self.max_iterations:
            iteration += 1
            prepared_messages = self.context_editor.prepare(messages)
            streamed_text = ""
            last_stream_preview = ""

            request_kwargs = {
                "messages": prepared_messages,
                "tools": self.tools.get_definitions(),
                "model": self.model,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "reasoning_effort": self.reasoning_effort,
                "on_text_delta": _on_text_delta if stream_text_progress else None,
            }
            provider_chat_with_retry = getattr(self.provider, "chat_with_retry", None)
            if inspect.iscoroutinefunction(provider_chat_with_retry):
                response = await provider_chat_with_retry(**request_kwargs)
            else:
                response = await self.provider.chat(**request_kwargs)

            if response.has_tool_calls:
                if on_progress:
                    clean = self._strip_think(response.content)
                    if clean and not response.streamed_output:
                        await on_progress(clean)
                    await on_progress(self._tool_hint(response.tool_calls), tool_hint=True)

                tool_call_dicts = [tc.to_openai_tool_call() for tc in response.tool_calls]
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
                    final_content = (
                        "Upstream model is temporarily unavailable (502/timeout). Please retry in 10-30 seconds."
                        if self._is_retryable_llm_error(clean)
                        else (clean or "Sorry, I encountered an error calling the AI model.")
                    )
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

    async def run(self) -> None:
        """Run the agent loop, dispatching messages as tasks to stay responsive to /stop."""
        self._running = True
        await self._connect_mcp()
        logger.info("Agent loop started")

        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            cmd = msg.content.strip().lower()
            if cmd == "/stop":
                await self._handle_stop(msg)
            elif cmd == "/restart":
                await self._handle_restart(msg)
            else:
                task = asyncio.create_task(self._dispatch(msg))
                self._active_tasks.setdefault(msg.session_key, []).append(task)
                task.add_done_callback(lambda t, k=msg.session_key: self._active_tasks.get(k, []) and self._active_tasks[k].remove(t) if t in self._active_tasks.get(k, []) else None)

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

    async def _handle_restart(self, msg: InboundMessage) -> None:
        """Restart the process in-place via os.execv."""
        await self.bus.publish_outbound(OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content="Restarting...",
        ))

        async def _do_restart() -> None:
            await asyncio.sleep(1)
            os.execv(sys.executable, [sys.executable] + sys.argv)

        asyncio.create_task(_do_restart())

    def _resolve_session_key(self, msg: InboundMessage, session_key: str | None = None) -> str:
        """Resolve the canonical session key for both chat and system messages."""
        if session_key:
            return session_key
        if msg.channel == "system":
            if ":" in msg.chat_id:
                channel, chat_id = msg.chat_id.split(":", 1)
                return f"{channel}:{chat_id}"
            return f"cli:{msg.chat_id}"
        return msg.session_key

    def _get_session_lock(self, session_key: str) -> asyncio.Lock:
        """Return the lock guarding a single conversation session."""
        lock = self._session_locks.get(session_key)
        if lock is None:
            lock = asyncio.Lock()
            self._session_locks[session_key] = lock
        return lock

    async def _process_with_session_lock(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> OutboundMessage | None:
        """Serialize processing within one session while allowing other sessions to run."""
        key = self._resolve_session_key(msg, session_key=session_key)
        async with self._get_session_lock(key):
            return await self._process_message(msg, session_key=key, on_progress=on_progress)

    async def _dispatch(self, msg: InboundMessage) -> None:
        """Process a message under a per-session lock."""
        key = self._resolve_session_key(msg)
        try:
            response = await self._process_with_session_lock(msg, session_key=key)
            if response is not None:
                await self.bus.publish_outbound(response)
            elif msg.channel == "cli":
                await self.bus.publish_outbound(OutboundMessage(
                    channel=msg.channel, chat_id=msg.chat_id,
                    content="", metadata=msg.metadata or {},
                ))
        except asyncio.CancelledError:
            logger.info("Task cancelled for session {}", key)
            raise
        except Exception:
            logger.exception("Error processing message for session {}", key)
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
            await self.memory_consolidator.maybe_consolidate_by_tokens(session)
            self._set_tool_context(channel, chat_id, msg.metadata.get("message_id"))
            history = session.get_history(max_messages=0)
            messages = self.context.build_messages(
                history=history,
                current_message=msg.content, channel=channel, chat_id=chat_id,
            )
            final_content, _, all_msgs = await self._run_agent_loop(messages)
            self._save_turn(session, all_msgs, 1 + len(history))
            self.sessions.save(session)
            await self.memory_consolidator.maybe_consolidate_by_tokens(session)
            return OutboundMessage(channel=channel, chat_id=chat_id,
                                  content=final_content or "Background task completed.")

        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info("Processing message from {}:{}: {}", msg.channel, msg.sender_id, preview)

        key = self._resolve_session_key(msg, session_key=session_key)
        session = self.sessions.get_or_create(key)

        # Slash commands
        cmd = msg.content.strip().lower()
        if cmd == "/new":
            try:
                if not await self.memory_consolidator.archive_unconsolidated(session):
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

            session.clear()
            self.sessions.save(session)
            self.sessions.invalidate(session.key)
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content="New session started.")
        if cmd == "/help":
            lines = [
                "🐈 nanobot commands:",
                "/new — Start a new conversation",
                "/stop — Stop the current task",
                "/restart — Restart the bot",
                "/help — Show available commands",
                "/account <name> — Switch to an AI profile",
                "/model <name> — Switch default model",
                "/rmaccount <name> — Remove an AI profile",
            ]
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="\n".join(lines),
            )

        if cmd == "/account":
            keyboard = [
                [{"text": "🔄 Switch Account", "callback_data": "/account_menu_switch"}],
                [{"text": "➕ Add Account", "callback_data": "/account_menu_add"}],
                [{"text": "🗑️ Delete Account", "callback_data": "/account_menu_delete"}]
            ]
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="⚙️ **Account Management**\nChoose an action below:",
                metadata={"inline_keyboard": keyboard}
            )

        if cmd == "/account_menu_switch":
            try:
                from nanobot.config.profiles import ProfileManager
                profiles = ProfileManager().list_profiles()
                if not profiles:
                    return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content="No AI account profiles found. Add one via terminal.")

                keyboard = []
                for p in profiles:
                    keyboard.append([{"text": f"{p.name} ({p.model})", "callback_data": f"/account {p.name}"}])

                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="🔄 **Select an account to switch to:**",
                    metadata={"inline_keyboard": keyboard}
                )
            except Exception:
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content="Error fetching profiles.")

        if cmd == "/account_menu_delete":
            try:
                from nanobot.config.profiles import ProfileManager
                profiles = ProfileManager().list_profiles()
                if not profiles:
                    return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content="No AI account profiles found.")

                keyboard = []
                for p in profiles:
                    keyboard.append([{"text": f"❌ {p.name}", "callback_data": f"/rmaccount {p.name}"}])

                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="🗑️ **Select an account to remove:**",
                    metadata={"inline_keyboard": keyboard}
                )
            except Exception:
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content="Error fetching profiles.")

        if cmd == "/account_menu_add":
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="➕ **Add a New Account**\n\nTo add an account, open your computer terminal and type:\n\n`nanobot account add <Name> --model <Model> --api-key <Key> --api-base <URL>`\n\nExample:\n`nanobot account add zhipu4 --model zhipu/glm-5 --api-key sk-abc`"
            )

        if cmd.startswith("/account "):
            profile_name = cmd.split(" ", 1)[1].strip()
            try:
                from nanobot.config.profiles import ProfileManager
                profile = ProfileManager().get_profile(profile_name)
                if not profile:
                    return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=f"❌ Profile '{profile_name}' not found.")

                from nanobot.cli.commands import _make_provider
                from nanobot.config.loader import load_config, save_config
                config = load_config()

                # Setup provider block (if missing) and inject key/baseUrl
                provider_name = config.get_provider_name(profile.model)
                p = getattr(config.providers, provider_name, None)
                if p is None:
                    setattr(config.providers, provider_name, type("ProviderConfig", (), {"api_key": profile.api_key, "api_base": profile.api_base})())
                else:
                    p.api_key = profile.api_key
                    p.api_base = profile.api_base

                # Update default model
                config.agents.defaults.model = profile.model
                save_config(config)

                # Hot swap runtime properties
                self.model = profile.model
                self.provider = _make_provider(config)
                self.subagents.provider = self.provider
                self.subagents.model = self.model

                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=f"✅ Switched to profile **{profile.name}** using model `{profile.model}`.")
            except Exception as e:
                logger.error("Error switching account: {}", e)
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=f"❌ Error switching account: {e}")

        if cmd.startswith("/model"):
            parts = cmd.split(" ", 1)
            if len(parts) < 2 or not parts[1].strip():
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content="Please provide a model name. Usage: `/model <name>`\nExample: `/model zhipu/glm-5`")
            new_model = parts[1].strip()
            try:
                from nanobot.cli.commands import _make_provider
                from nanobot.config.loader import load_config, save_config
                config = load_config()
                config.agents.defaults.model = new_model
                save_config(config)

                self.model = new_model
                self.provider = _make_provider(config)
                self.subagents.provider = self.provider
                self.subagents.model = self.model

                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=f"✅ Switched default model to `{new_model}`.")
            except Exception as e:
                logger.error("Error switching model: {}", e)
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=f"❌ Error switching model: {e}")

        if cmd.startswith("/rmaccount"):
            parts = cmd.split(" ", 1)
            if len(parts) < 2 or not parts[1].strip():
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content="Please provide a profile name to remove. Usage: `/rmaccount <name>`\nExample: `/rmaccount gemini`")
            profile_name = parts[1].strip()
            try:
                from nanobot.config.profiles import ProfileManager
                mgr = ProfileManager()
                if not mgr.get_profile(profile_name):
                    return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=f"❌ Profile '{profile_name}' not found.")
                mgr.remove_profile(profile_name)
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=f"🗑️ Successfully removed profile `{profile_name}`.")
            except Exception as e:
                logger.error("Error removing account: {}", e)
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=f"❌ Error removing account: {e}")

                self.model = new_model
                self.provider = _make_provider(config)
                self.subagents.provider = self.provider
                self.subagents.model = self.model

                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=f"✅ Switched default model to `{new_model}`.")
            except Exception as e:
                logger.error("Error switching model: {}", e)
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=f"❌ Error switching model: {e}")

        await self.memory_consolidator.maybe_consolidate_by_tokens(session)

        self._set_tool_context(msg.channel, msg.chat_id, msg.metadata.get("message_id"))
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.start_turn()

        history = session.get_history(max_messages=0)
        initial_messages = self.context.build_messages(
            history=history,
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel, chat_id=msg.chat_id,
        )

        async def _bus_progress(
            content: str,
            *,
            tool_hint: bool = False,
            replace: bool = False,
        ) -> None:
            meta = dict(msg.metadata or {})
            meta["_progress"] = True
            meta["_tool_hint"] = tool_hint
            if replace:
                meta["_progress_mode"] = "replace"
            await self.bus.publish_outbound(OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id, content=content, metadata=meta,
            ))

        final_content, _, all_msgs = await self._run_agent_loop(
            initial_messages,
            on_progress=on_progress or _bus_progress,
            stream_text_progress=(msg.channel == "telegram"),
        )

        if final_content is None:
            final_content = "I've completed processing but have no response to give."

        self._save_turn(session, all_msgs, 1 + len(history))
        self.sessions.save(session)
        await self.memory_consolidator.maybe_consolidate_by_tokens(session)

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
                    parts = content.split("\n\n", 1)
                    if len(parts) > 1 and parts[1].strip():
                        entry["content"] = parts[1]
                    else:
                        continue
                if isinstance(content, list):
                    filtered = []
                    for c in content:
                        if c.get("type") == "text" and isinstance(c.get("text"), str) and c["text"].startswith(ContextBuilder._RUNTIME_CONTEXT_TAG):
                            continue
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

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> str:
        """Process a message directly (for CLI or cron usage)."""
        await self._connect_mcp()
        msg = InboundMessage(channel=channel, sender_id="user", chat_id=chat_id, content=content)
        response = await self._process_with_session_lock(
            msg,
            session_key=session_key,
            on_progress=on_progress,
        )
        return response.content if response else ""
