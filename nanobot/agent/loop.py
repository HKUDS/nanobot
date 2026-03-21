"""Agent loop: the core processing engine."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from nanobot.agent.context import ContextBuilder
from nanobot.agent.memory import MemoryConsolidator, MemoryStore
from nanobot.agent.registry import AgentRegistry, NamedAgent
from nanobot.agent.subagent import SubagentManager
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.delegate import DelegateTool
from nanobot.agent.tools.discuss import DiscussTool
from nanobot.agent.tools.manage_agents import ManageAgentsTool
from nanobot.agent.skills import BUILTIN_SKILLS_DIR
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
    from nanobot.config.schema import ChannelsConfig, Config, ExecToolConfig, WebSearchConfig
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
        context_window_tokens: int = 65_536,
        web_search_config: WebSearchConfig | None = None,
        web_proxy: str | None = None,
        exec_config: ExecToolConfig | None = None,
        cron_service: CronService | None = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
        channels_config: ChannelsConfig | None = None,
        config: Config | None = None,
    ):
        from nanobot.config.schema import ExecToolConfig, WebSearchConfig

        self.bus = bus
        self.channels_config = channels_config
        self._config = config
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.context_window_tokens = context_window_tokens
        self.web_search_config = web_search_config or WebSearchConfig()
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
            web_search_config=self.web_search_config,
            web_proxy=web_proxy,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
        )

        self._running = False
        self._mcp_servers = mcp_servers or {}
        self._mcp_stack: AsyncExitStack | None = None
        self._mcp_connected = False
        self._mcp_connecting = False
        self._active_tasks: dict[str, list[asyncio.Task]] = {}  # session_key -> tasks
        self._background_tasks: list[asyncio.Task] = []
        self._processing_lock = asyncio.Lock()
        self.memory_consolidator = MemoryConsolidator(
            workspace=workspace,
            provider=provider,
            model=self.model,
            sessions=self.sessions,
            context_window_tokens=context_window_tokens,
            build_messages=self.context.build_messages,
            get_tool_definitions=self.tools.get_definitions,
        )

        # Named agent registry (always created so runtime registration works)
        named_configs = config.agents.named if config else {}
        self.agent_registry = AgentRegistry(
                workspace=workspace,
                named_configs=named_configs,
                main_model=self.model,
                web_search_config=self.web_search_config,
                web_proxy=web_proxy,
                exec_config=self.exec_config,
                restrict_to_workspace=restrict_to_workspace,
            )

        self._register_default_tools()
        self._update_agents_prompt()

    def _update_agents_prompt(self) -> None:
        """Inject available agents summary into the main agent's system prompt (dynamic)."""
        if self.agent_registry:
            self.context.extra_system_sections = [self.agent_registry.build_agents_summary]

    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        extra_read = [BUILTIN_SKILLS_DIR] if allowed_dir else None
        self.tools.register(ReadFileTool(workspace=self.workspace, allowed_dir=allowed_dir, extra_allowed_dirs=extra_read))
        for cls in (WriteFileTool, EditFileTool, ListDirTool):
            self.tools.register(cls(workspace=self.workspace, allowed_dir=allowed_dir))
        if self.exec_config.enable:
            self.tools.register(ExecTool(
                working_dir=str(self.workspace),
                timeout=self.exec_config.timeout,
                restrict_to_workspace=self.restrict_to_workspace,
                path_append=self.exec_config.path_append,
            ))
        self.tools.register(WebSearchTool(config=self.web_search_config, proxy=self.web_proxy))
        self.tools.register(WebFetchTool(proxy=self.web_proxy))
        self.tools.register(MessageTool(send_callback=self.bus.publish_outbound))
        self.tools.register(SpawnTool(manager=self.subagents))
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))

        # Named agent tools
        if self.agent_registry:
            agent_names = lambda: [a.name for a in self.agent_registry.list_agents()]
            self.tools.register(DelegateTool(
                run_callback=self._run_named_agent,
                list_callback=agent_names,
            ))
            self.tools.register(DiscussTool(
                run_callback=self._run_named_agent,
                list_callback=agent_names,
            ))
            self.tools.register(ManageAgentsTool(registry=self.agent_registry))

        # Discover and register external tool plugins
        if self._config:
            from nanobot.agent.tools.registry import discover_tool_plugins, discover_skill_tools
            discover_tool_plugins(self.tools, self._config)
            discover_skill_tools(self.tools, self._config, self.workspace)

    def _handle_models_command(self, arg: str) -> str:
        """Handle /models command: list providers or models under a provider."""
        if not self._config:
            return "Config not available."

        providers_cfg = self._config.providers

        if not arg:
            # List all configured providers that have an api_key
            lines = ["📋 Configured providers:"]

            # Standard providers
            for field_name in providers_cfg.model_fields:
                if field_name == "extras":
                    continue
                p = getattr(providers_cfg, field_name, None)
                if p and p.api_key:
                    n_models = len(p.models)
                    suffix = f" ({n_models} models)" if n_models else ""
                    lines.append(f"  • {field_name}{suffix}")

            # Extras providers
            for key, p in providers_cfg.extras.items():
                if p.api_key:
                    n_models = len(p.models)
                    suffix = f" ({n_models} models)" if n_models else " (auto)"
                    lines.append(f"  • {key}{suffix}")

            return "\n".join(lines) if len(lines) > 1 else "No providers configured."

        # List models for a specific provider
        name = arg.lower()

        # Check extras first
        for key, p in providers_cfg.extras.items():
            if key.lower() == name:
                if p.models:
                    lines = [f"📋 Models for {key}:"]
                    for m in p.models:
                        lines.append(f"  • {key}/{m.id}")
                    return "\n".join(lines)
                return f"Provider '{key}' uses auto-fetch (no static model list). Use /model {key}/<model_name> to switch directly."

        # Check standard providers
        for field_name in providers_cfg.model_fields:
            if field_name == "extras":
                continue
            if field_name.lower() == name:
                p = getattr(providers_cfg, field_name, None)
                if p and p.api_key:
                    if p.models:
                        lines = [f"📋 Models for {field_name}:"]
                        for m in p.models:
                            lines.append(f"  • {field_name}/{m.id}")
                        return "\n".join(lines)
                    return f"Provider '{field_name}' has no static model list configured."
                return f"Provider '{field_name}' is not configured (no API key)."

        return f"Provider '{arg}' not found."

    def _handle_model_command(self, arg: str) -> str:
        """Handle /model command: show current model or switch to a new one."""
        if not arg:
            return f"Current model: {self.model}"

        new_model = arg
        old_model = self.model

        # Determine if we need to rebuild the provider (different provider prefix)
        old_prefix = old_model.split("/", 1)[0] if "/" in old_model else ""
        new_prefix = new_model.split("/", 1)[0] if "/" in new_model else ""

        need_new_provider = old_prefix != new_prefix

        if need_new_provider and self._config:
            # Rebuild provider for the new model
            saved_model = self._config.agents.defaults.model
            self._config.agents.defaults.model = new_model
            try:
                from nanobot.cli.commands import _make_provider
                new_provider = _make_provider(self._config)
                self.provider = new_provider
                self.subagents.provider = new_provider
                self.memory_consolidator.provider = new_provider
            except Exception as e:
                self._config.agents.defaults.model = saved_model
                return f"Failed to switch model: {e}"

        # Update model references everywhere
        self.model = new_model
        self.subagents.model = new_model
        self.memory_consolidator.model = new_model

        return f"✅ Switched model: {old_model} → {new_model}"

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
        except BaseException as e:
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
        for name in ("message", "spawn", "cron", "delegate", "discuss"):
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
        """Run the agent iteration loop."""
        messages = initial_messages
        iteration = 0
        final_content = None
        tools_used: list[str] = []

        while iteration < self.max_iterations:
            iteration += 1

            tool_defs = self.tools.get_definitions()

            response = await self.provider.chat_with_retry(
                messages=messages,
                tools=tool_defs,
                model=self.model,
            )

            if response.has_tool_calls:
                if on_progress:
                    thought = self._strip_think(response.content)
                    if thought:
                        await on_progress(thought)
                    tool_hint = self._tool_hint(response.tool_calls)
                    tool_hint = self._strip_think(tool_hint)
                    await on_progress(tool_hint, tool_hint=True)

                tool_call_dicts = [
                    tc.to_openai_tool_call()
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
                    import re
                    err_brief = re.sub(r"<[^>]+>", " ", clean or "").strip()
                    err_brief = re.sub(r"\s+", " ", err_brief)[:200]
                    logger.error("LLM returned error: {}", err_brief)
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
            except asyncio.CancelledError:
                # Preserve real task cancellation so shutdown can complete cleanly.
                # Only ignore non-task CancelledError signals that may leak from integrations.
                if not self._running or asyncio.current_task().cancelling():
                    raise
                continue
            except Exception as e:
                logger.warning("Error consuming inbound message: {}, continuing...", e)
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
        content = f"Stopped {total} task(s)." if total else "No active task to stop."
        await self.bus.publish_outbound(OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=content,
        ))

    async def _handle_restart(self, msg: InboundMessage) -> None:
        """Restart the process in-place via os.execv."""
        await self.bus.publish_outbound(OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content="Restarting...",
        ))

        async def _do_restart():
            await asyncio.sleep(1)
            # Use -m nanobot instead of sys.argv[0] for Windows compatibility
            # (sys.argv[0] may be just "nanobot" without full path on Windows)
            os.execv(sys.executable, [sys.executable, "-m", "nanobot"] + sys.argv[1:])

        asyncio.create_task(_do_restart())

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
        """Drain pending background archives, then close MCP connections."""
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()
        if self._mcp_stack:
            try:
                await self._mcp_stack.aclose()
            except (RuntimeError, BaseExceptionGroup):
                pass  # MCP SDK cancel scope cleanup is noisy but harmless
            self._mcp_stack = None

    def _schedule_background(self, coro) -> None:
        """Schedule a coroutine as a tracked background task (drained on shutdown)."""
        task = asyncio.create_task(coro)
        self._background_tasks.append(task)
        task.add_done_callback(self._background_tasks.remove)

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
            # Subagent results should be assistant role, other system messages use user role
            current_role = "assistant" if msg.sender_id == "subagent" else "user"
            messages = self.context.build_messages(
                history=history,
                current_message=msg.content, channel=channel, chat_id=chat_id,
                current_role=current_role,
            )
            final_content, _, all_msgs = await self._run_agent_loop(messages)
            self._save_turn(session, all_msgs, 1 + len(history))
            self.sessions.save(session)
            self._schedule_background(self.memory_consolidator.maybe_consolidate_by_tokens(session))
            return OutboundMessage(channel=channel, chat_id=chat_id,
                                  content=final_content or "Background task completed.")

        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info("Processing message from {}:{}: {}", msg.channel, msg.sender_id, preview)

        key = session_key or msg.session_key
        session = self.sessions.get_or_create(key)

        # Slash commands
        cmd = msg.content.strip().lower()
        if cmd == "/new":
            snapshot = session.messages[session.last_consolidated:]
            session.clear()
            self.sessions.save(session)
            self.sessions.invalidate(session.key)

            if snapshot:
                self._schedule_background(self.memory_consolidator.archive_messages(snapshot))

            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content="New session started.")
        if cmd == "/help":
            lines = [
                "🐈 nanobot commands:",
                "/new — Start a new conversation",
                "/stop — Stop the current task",
                "/restart — Restart the bot",
                "/model — Show current model (or /model <name> to switch)",
                "/models — List configured providers (or /models <provider> to list models)",
                "/help — Show available commands",
            ]
            return OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id, content="\n".join(lines),
            )

        # Parse commands with optional @botname suffix (e.g. /model@MyBot arg)
        raw = msg.content.strip()
        cmd_match = re.match(r'^(/\w+)(?:@\S+)?\s*(.*)', raw, re.DOTALL)
        if cmd_match:
            cmd_name = cmd_match.group(1).lower()
            cmd_arg = cmd_match.group(2).strip()
            if cmd_name == "/models":
                result = self._handle_models_command(cmd_arg)
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=result)
            if cmd_name == "/model":
                result = self._handle_model_command(cmd_arg)
                return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=result)

        # @mention routing to named agents
        if self.agent_registry:
            match = self.agent_registry.match_mention(raw)
            if match:
                agent_name, stripped_msg = match
                return await self._process_named_agent_message(
                    msg, agent_name, stripped_msg, on_progress=on_progress,
                )

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
        self._schedule_background(self.memory_consolidator.maybe_consolidate_by_tokens(session))

        if (mt := self.tools.get("message")) and isinstance(mt, MessageTool) and mt._sent_in_turn:
            return None

        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info("Response to {}:{}: {}", msg.channel, msg.sender_id, preview)
        return OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=final_content,
            metadata=msg.metadata or {},
        )

    def _get_provider_for_model(self, model: str) -> LLMProvider:
        """Get the appropriate provider for a model, creating a new one if needed."""
        main_prefix = self.model.split("/", 1)[0] if "/" in self.model else ""
        agent_prefix = model.split("/", 1)[0] if "/" in model else ""

        if agent_prefix == main_prefix or not agent_prefix:
            return self.provider

        # Different provider prefix — try to build a new provider
        if self._config:
            saved_model = self._config.agents.defaults.model
            self._config.agents.defaults.model = model
            try:
                from nanobot.cli.commands import _make_provider
                provider = _make_provider(self._config)
                return provider
            except Exception as e:
                logger.warning("Failed to create provider for model {}: {}, falling back", model, e)
            finally:
                self._config.agents.defaults.model = saved_model

        return self.provider

    async def _process_named_agent_message(
        self,
        msg: InboundMessage,
        agent_name: str,
        content: str,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> OutboundMessage | None:
        """Process a message routed directly to a named agent via @mention."""
        agent = self.agent_registry.get(agent_name)
        if not agent:
            return OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id,
                content=f"Agent '{agent_name}' not found.",
            )

        logger.info("Routing @{} message from {}:{}", agent_name, msg.channel, msg.chat_id)
        result = await self._run_named_agent(
            agent_name, content, msg.channel, msg.chat_id,
            media=msg.media if msg.media else None,
        )
        return OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id,
            content=result, metadata=msg.metadata or {},
        )

    async def _run_named_agent(
        self,
        agent_name: str,
        task: str,
        channel: str,
        chat_id: str,
        media: list[str] | None = None,
    ) -> str:
        """Run a named agent with its own session, context, and tools. Used by delegate/discuss/mention."""
        agent = self.agent_registry.get(agent_name)
        if not agent:
            return f"Agent '{agent_name}' not found."

        model = self.agent_registry.get_model(agent)
        provider = self._get_provider_for_model(model)
        session_key = f"{channel}:{chat_id}:agent:{agent_name}"
        session = self.sessions.get_or_create(session_key)

        # Memory consolidation for this agent's session
        consolidator = MemoryConsolidator(
            workspace=agent.workspace,
            provider=provider,
            model=model,
            sessions=self.sessions,
            context_window_tokens=self.context_window_tokens,
            build_messages=agent.context.build_messages,
            get_tool_definitions=agent.tools.get_definitions,
        )
        await consolidator.maybe_consolidate_by_tokens(session)

        history = session.get_history(max_messages=0)
        messages = agent.context.build_messages(
            history=history,
            current_message=task,
            media=media,
            channel=channel,
            chat_id=chat_id,
        )

        # Run the agent iteration loop with the named agent's tools
        iteration = 0
        max_iterations = agent.config.max_iterations
        final_content = None

        while iteration < max_iterations:
            iteration += 1
            tool_defs = agent.tools.get_definitions()
            response = await provider.chat_with_retry(
                messages=messages, tools=tool_defs, model=model,
            )

            if response.has_tool_calls:
                tool_call_dicts = [tc.to_openai_tool_call() for tc in response.tool_calls]
                messages = agent.context.add_assistant_message(
                    messages, response.content, tool_call_dicts,
                    reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                )
                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    logger.debug("[{}] Tool: {}({})", agent_name, tool_call.name, args_str[:200])
                    result = await agent.tools.execute(tool_call.name, tool_call.arguments)
                    messages = agent.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result,
                    )
            else:
                final_content = self._strip_think(response.content)
                if response.finish_reason == "error":
                    final_content = final_content or "Agent encountered an error."
                else:
                    messages = agent.context.add_assistant_message(
                        messages, final_content,
                        reasoning_content=response.reasoning_content,
                        thinking_blocks=response.thinking_blocks,
                    )
                break

        if final_content is None:
            final_content = f"Agent '{agent_name}' reached max iterations ({max_iterations})."

        # Save turn to the agent's session
        self._save_turn(session, messages, 1 + len(history))
        self.sessions.save(session)
        self._schedule_background(consolidator.maybe_consolidate_by_tokens(session))

        logger.info("[{}] completed, response: {}", agent_name, (final_content or "")[:120])
        return final_content

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
                            path = (c.get("_meta") or {}).get("path", "")
                            placeholder = f"[image: {path}]" if path else "[image]"
                            filtered.append({"type": "text", "text": placeholder})
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
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """Process a message directly (for CLI or cron usage)."""
        await self._connect_mcp()
        msg = InboundMessage(channel=channel, sender_id="user", chat_id=chat_id, content=content)
        response = await self._process_message(msg, session_key=session_key, on_progress=on_progress)
        return response.content if response else ""
