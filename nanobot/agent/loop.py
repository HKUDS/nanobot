"""Agent loop: the core processing engine."""

from __future__ import annotations

import asyncio
import json
import re
import os
import time
from contextlib import AsyncExitStack, nullcontext
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from nanobot.agent.context import ContextBuilder
from nanobot.agent.hook import AgentHook, AgentHookContext, CompositeHook
from nanobot.agent.memory import Dream, MemoryConsolidator
from nanobot.agent.pruner import ContextPruner
from nanobot.agent.runner import AgentRunResult, AgentRunSpec, AgentRunner
from nanobot.agent.subagent import SubagentManager
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.skills import BUILTIN_SKILLS_DIR
from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool
from nanobot.bus.events import InboundMessage, OutboundMessage, TurnContext
from nanobot.command import CommandContext, CommandRouter, register_builtin_commands
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider
from nanobot.session.manager import Session, SessionManager
from nanobot.workspace.layout import WorkspaceLayout, make_layout

if TYPE_CHECKING:
    from nanobot.config.schema import ChannelsConfig, ExecToolConfig, WebToolsConfig
    from nanobot.cron.service import CronService


class _LoopHook(AgentHook):
    """Core lifecycle hook for the main agent loop.

    Handles streaming delta relay, progress reporting, tool-call logging,
    and think-tag stripping for the built-in agent path.
    """

    def __init__(
        self,
        agent_loop: AgentLoop,
        on_progress: Callable[..., Awaitable[None]] | None = None,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
        *,
        channel: str = "cli",
        chat_id: str = "direct",
        message_id: str | None = None,
    ) -> None:
        self._loop = agent_loop
        self._on_progress = on_progress
        self._on_stream = on_stream
        self._on_stream_end = on_stream_end
        self._channel = channel
        self._chat_id = chat_id
        self._message_id = message_id
        self._stream_buf = ""

    def wants_streaming(self) -> bool:
        return self._on_stream is not None

    async def on_stream(self, context: AgentHookContext, delta: str) -> None:
        from nanobot.utils.helpers import strip_think

        prev_clean = strip_think(self._stream_buf)
        self._stream_buf += delta
        new_clean = strip_think(self._stream_buf)
        incremental = new_clean[len(prev_clean):]
        if incremental and self._on_stream:
            await self._on_stream(incremental)

    async def on_stream_end(self, context: AgentHookContext, *, resuming: bool) -> None:
        if self._on_stream_end:
            await self._on_stream_end(resuming=resuming)
        self._stream_buf = ""

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        if self._on_progress:
            if not self._on_stream:
                thought = self._loop._strip_think(
                    context.response.content if context.response else None
                )
                if thought:
                    await self._on_progress(thought)
            tool_hint = self._loop._strip_think(self._loop._tool_hint(context.tool_calls))
            await self._on_progress(tool_hint, tool_hint=True)
        for tc in context.tool_calls:
            args_str = json.dumps(tc.arguments, ensure_ascii=False)
            logger.info("Tool call: {}({})", tc.name, args_str[:200])
        # Preserve session_metadata already set by _process_message
        existing_meta = getattr(self._loop.tools.get("message"), "_session_metadata", None)
        self._loop._set_tool_context(self._channel, self._chat_id, self._message_id, session_metadata=existing_meta)

    def finalize_content(self, context: AgentHookContext, content: str | None) -> str | None:
        return self._loop._strip_think(content)


class _LoopHookChain(AgentHook):
    """Run the core loop hook first, then best-effort extra hooks.

    This preserves the historical failure behavior of ``_LoopHook`` while still
    letting user-supplied hooks opt into ``CompositeHook`` isolation.
    """

    __slots__ = ("_primary", "_extras")

    def __init__(self, primary: AgentHook, extra_hooks: list[AgentHook]) -> None:
        self._primary = primary
        self._extras = CompositeHook(extra_hooks)

    def wants_streaming(self) -> bool:
        return self._primary.wants_streaming() or self._extras.wants_streaming()

    async def before_iteration(self, context: AgentHookContext) -> None:
        await self._primary.before_iteration(context)
        await self._extras.before_iteration(context)

    async def on_stream(self, context: AgentHookContext, delta: str) -> None:
        await self._primary.on_stream(context, delta)
        await self._extras.on_stream(context, delta)

    async def on_stream_end(self, context: AgentHookContext, *, resuming: bool) -> None:
        await self._primary.on_stream_end(context, resuming=resuming)
        await self._extras.on_stream_end(context, resuming=resuming)

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        await self._primary.before_execute_tools(context)
        await self._extras.before_execute_tools(context)

    async def after_iteration(self, context: AgentHookContext) -> None:
        await self._primary.after_iteration(context)
        await self._extras.after_iteration(context)

    def finalize_content(self, context: AgentHookContext, content: str | None) -> str | None:
        content = self._primary.finalize_content(context, content)
        return self._extras.finalize_content(context, content)


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
        web_config: WebToolsConfig | None = None,
        web_proxy: str | None = None,
        exec_config: ExecToolConfig | None = None,
        cron_service: CronService | None = None,
        restrict_to_workspace: bool = False,
        extra_allowed_paths: list[str] | None = None,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
        channels_config: ChannelsConfig | None = None,
        timezone: str | None = None,
        context_pruning_config=None,  # ContextPruningConfig | None
        skills_config=None,  # SkillsConfig | None
        hooks: list[AgentHook] | None = None,
        config: Any = None,
        layout: WorkspaceLayout | None = None,
    ):
        from nanobot.config.schema import ContextPruningConfig, ExecToolConfig, WebToolsConfig

        self.bus = bus
        self.channels_config = channels_config
        self.provider = provider
        self.workspace = workspace
        self.layout = layout
        self.model = model or provider.get_default_model()
        self._config = config                    # 原始 Config 对象，用于构建新 provider
        self._config_model = self.model          # config 中的默认 model，不可变
        self._config_provider = self.provider    # config 中的默认 provider（含 fallback），不可变
        self.max_iterations = max_iterations
        self.context_window_tokens = context_window_tokens
        self.web_config = web_config or WebToolsConfig()
        self.web_proxy = web_proxy
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        self.restrict_to_workspace = restrict_to_workspace
        self.extra_allowed_paths = [Path(p).expanduser().resolve() for p in (extra_allowed_paths or [])]
        self._start_time = time.time()
        self._last_usage: dict[str, int] = {}
        _pruning_cfg = context_pruning_config or ContextPruningConfig()
        self._pruner: ContextPruner | None = ContextPruner(_pruning_cfg) if _pruning_cfg.enabled else None
        self._extra_hooks: list[AgentHook] = hooks or []

        # Add TraceHook for LLM call logging
        from nanobot.agent.hook import TraceHook
        self._trace_hook = TraceHook()
        self._extra_hooks.append(self._trace_hook)

        self.context = ContextBuilder(workspace, timezone=timezone, skills_config=skills_config)
        self.sessions = session_manager or SessionManager(workspace)
        self.tools = ToolRegistry()
        self.runner = AgentRunner(provider)
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            max_tool_result_chars=self._TOOL_RESULT_MAX_CHARS,
            web_config=self.web_config,
            exec_config=exec_config,
            restrict_to_workspace=restrict_to_workspace,
        )

        self._running = False
        self._mcp_servers = mcp_servers or {}
        self._mcp_stack: AsyncExitStack | None = None
        self._mcp_connected = False
        self._mcp_connecting = False
        self._active_tasks: dict[str, list[asyncio.Task]] = {}  # session_key -> tasks
        self._background_tasks: list[asyncio.Task] = []
        self._session_locks: dict[str, asyncio.Lock] = {}
        # NANOBOT_MAX_CONCURRENT_REQUESTS: <=0 means unlimited; default 3.
        _max = int(os.environ.get("NANOBOT_MAX_CONCURRENT_REQUESTS", "3"))
        self._concurrency_gate: asyncio.Semaphore | None = (
            asyncio.Semaphore(_max) if _max > 0 else None
        )
        from nanobot.agent.memory import MemoryStore
        self._memory_store = MemoryStore(workspace, layout=self.layout)
        self.memory_consolidator = MemoryConsolidator(
            store=self._memory_store,
            provider=provider,
            model=self.model,
            sessions=self.sessions,
            context_window_tokens=context_window_tokens,
            build_messages=self.context.build_messages,
            get_tool_definitions=self.tools.get_definitions,
            max_completion_tokens=provider.generation.max_tokens,
        )
        self.dream = Dream(
            store=self._memory_store,
            provider=provider,
            model=self.model,
        )
        self._register_default_tools()
        self.commands = CommandRouter()
        register_builtin_commands(self.commands)

    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        extra_dirs = list(self.extra_allowed_paths) if self.extra_allowed_paths else []
        extra_read = ([BUILTIN_SKILLS_DIR] + extra_dirs) if allowed_dir else None
        extra_write = extra_dirs if allowed_dir else None
        self.tools.register(ReadFileTool(workspace=self.workspace, allowed_dir=allowed_dir, extra_allowed_dirs=extra_read))
        for cls in (WriteFileTool, EditFileTool, ListDirTool):
            self.tools.register(cls(workspace=self.workspace, allowed_dir=allowed_dir, extra_allowed_dirs=extra_write))
        if self.exec_config.enable:
            self.tools.register(ExecTool(
                working_dir=str(self.workspace),
                timeout=self.exec_config.timeout,
                restrict_to_workspace=self.restrict_to_workspace,
                extra_allowed_paths=[str(p) for p in self.extra_allowed_paths],
                path_append=self.exec_config.path_append,
                rtk_enabled=self.exec_config.rtk_enabled,
                rtk_verbose=self.exec_config.rtk_verbose,
            ))
        self.tools.register(WebSearchTool(config=self.web_config.search, proxy=self.web_proxy))
        self.tools.register(WebFetchTool(proxy=self.web_proxy))
        self.tools.register(MessageTool(send_callback=self.bus.publish_outbound))
        self.tools.register(SpawnTool(manager=self.subagents))
        if self.cron_service:
            self.tools.register(
                CronTool(self.cron_service, default_timezone=self.context.timezone or "UTC")
            )

    def switch_model(self, model: str) -> str:
        """运行时切换模型（无 fallback）。失败时抛出 ValueError。"""
        from nanobot.nanobot import _make_single_provider

        new_provider = _make_single_provider(self._config, model)
        new_provider.generation = self._config_provider.generation
        self.provider = new_provider
        self.model = model
        self.runner.provider = new_provider
        logger.info("Model switched to: {}", model)
        return model

    def reset_model(self) -> str:
        """恢复到 config 默认 model + provider（含 fallback chain）。"""
        self.provider = self._config_provider
        self.model = self._config_model
        self.runner.provider = self._config_provider
        logger.info("Model reset to default: {}", self._config_model)
        return self._config_model

    def get_model_choices(self) -> list[str]:
        """返回可切换的模型列表：config model + fallback models。"""
        if not self._config:
            return [self._config_model]
        fb = self._config.agents.defaults.fallback_models or []
        return [self._config_model] + list(fb)

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

    def _set_tool_context(
        self, channel: str, chat_id: str, message_id: str | None = None,
        session_metadata: dict | None = None,
    ) -> None:
        """Update context for all tools that need routing info."""
        for name in ("message", "spawn", "cron"):
            if tool := self.tools.get(name):
                if hasattr(tool, "set_context"):
                    if name == "message":
                        tool.set_context(channel, chat_id, message_id, session_metadata=session_metadata)
                    else:
                        tool.set_context(channel, chat_id)

    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        """Remove <think>…</think> blocks that some models embed in content."""
        if not text:
            return None
        from nanobot.utils.helpers import strip_think
        return strip_think(text) or None

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
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
        *,
        channel: str = "cli",
        chat_id: str = "direct",
        message_id: str | None = None,
        layout: WorkspaceLayout | None = None,
    ) -> AgentRunResult:
        """Run the agent iteration loop.

        *on_stream*: called with each content delta during streaming.
        *on_stream_end(resuming)*: called when a streaming session finishes.
        ``resuming=True`` means tool calls follow (spinner should restart);
        ``resuming=False`` means this is the final response.
        """
        loop_hook = _LoopHook(
            self,
            on_progress=on_progress,
            on_stream=on_stream,
            on_stream_end=on_stream_end,
            channel=channel,
            chat_id=chat_id,
            message_id=message_id,
        )
        # Route trace hooks to the correct session/log file
        for h in self._extra_hooks:
            if hasattr(h, "session_key"):
                h.session_key = f"{channel}:{chat_id}"
            if layout and hasattr(h, "set_log_path"):
                h.set_log_path(self.sessions.current_llm_log_path(layout))

        hook: AgentHook = (
            _LoopHookChain(loop_hook, self._extra_hooks)
            if self._extra_hooks
            else loop_hook
        )

        result = await self.runner.run(AgentRunSpec(
            initial_messages=initial_messages,
            tools=self.tools,
            model=self.model,
            max_iterations=self.max_iterations,
            max_tool_result_chars=self._TOOL_RESULT_MAX_CHARS,
            hook=hook,
            error_message="Sorry, I encountered an error calling the AI model.",
            concurrent_tools=True,
            pruner=self._pruner,
            context_window_tokens=self.context_window_tokens,
        ))
        self._last_usage = result.usage
        if result.stop_reason == "max_iterations":
            logger.warning("Max iterations ({}) reached", self.max_iterations)
        elif result.stop_reason == "error":
            logger.error("LLM returned error: {}", (result.final_content or "")[:200])
        return result

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

            raw = msg.content.strip()
            if self.commands.is_priority(raw):
                ctx = CommandContext(
                    msg=msg, session=None, key=msg.session_key, raw=raw, loop=self,
                    interaction_id=(msg.metadata or {}).get("interaction_id"),
                    interaction_token=(msg.metadata or {}).get("interaction_token"),
                )
                result = await self.commands.dispatch_priority(ctx)
                if result:
                    await self.bus.publish_outbound(result)
                continue
            task = asyncio.create_task(self._dispatch(msg))
            self._active_tasks.setdefault(msg.session_key, []).append(task)
            task.add_done_callback(lambda t, k=msg.session_key: self._active_tasks.get(k, []) and self._active_tasks[k].remove(t) if t in self._active_tasks.get(k, []) else None)

    async def _dispatch(self, msg: InboundMessage) -> None:
        """Process a message: per-session serial, cross-session concurrent."""
        lock = self._session_locks.setdefault(msg.session_key, asyncio.Lock())
        gate = self._concurrency_gate or nullcontext()
        async with lock, gate:
            try:
                on_stream = on_stream_end = None
                if msg.metadata.get("_wants_stream"):
                    # Split one answer into distinct stream segments.
                    stream_base_id = f"{msg.session_key}:{time.time_ns()}"
                    stream_segment = 0

                    def _current_stream_id() -> str:
                        return f"{stream_base_id}:{stream_segment}"

                    async def on_stream(delta: str) -> None:
                        await self.bus.publish_outbound(OutboundMessage(
                            channel=msg.channel, chat_id=msg.chat_id,
                            content=delta,
                            metadata={
                                "_stream_delta": True,
                                "_stream_id": _current_stream_id(),
                            },
                        ))

                    async def on_stream_end(*, resuming: bool = False) -> None:
                        nonlocal stream_segment
                        await self.bus.publish_outbound(OutboundMessage(
                            channel=msg.channel, chat_id=msg.chat_id,
                            content="",
                            metadata={
                                "_stream_end": True,
                                "_resuming": resuming,
                                "_stream_id": _current_stream_id(),
                            },
                        ))
                        stream_segment += 1

                response = await self._process_message(
                    msg, on_stream=on_stream, on_stream_end=on_stream_end,
                )
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

    def _resolve_layout(
        self, ctx: TurnContext, *, session_key: str | None = None,
    ) -> WorkspaceLayout | None:
        """Construct layout when channel_name is resolved; skip for explicit session_key."""
        if session_key:
            return None
        name = ctx.channel_name or ("cli" if ctx.channel == "cli" else None)
        if not name:
            return None
        return make_layout(
            self.workspace, ctx.channel, name, ctx.chat_id,
            scope_id=ctx.channel_scope_id or "",
        )

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
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
    ) -> OutboundMessage | None:
        """Process a single inbound message and return the response."""
        # System messages: parse origin from chat_id ("channel:chat_id")
        if msg.channel == "system":
            channel, chat_id = (msg.chat_id.split(":", 1) if ":" in msg.chat_id
                                else ("cli", msg.chat_id))
            ctx = TurnContext(
                channel=channel, chat_id=chat_id,
                message_id=msg.metadata.get("message_id"),
                channel_name=msg.metadata.get("channel_name"),
                channel_scope_id=msg.metadata.get("channel_scope_id"),
                sender_name=msg.metadata.get("sender_name"),
                sender_id=msg.sender_id,
            )
            logger.info("Processing system message from {}", ctx.sender_id)
            key = f"{ctx.channel}:{ctx.chat_id}"
            layout = self._resolve_layout(ctx)
            session = self.sessions.get_or_create_from_layout(layout) if layout else self.sessions.get_or_create(key)
            self._update_runtime_metadata(session, ctx)
            await self.memory_consolidator.maybe_consolidate_by_tokens(session)
            self._set_tool_context(ctx.channel, ctx.chat_id, ctx.message_id)
            history = session.get_history(max_messages=0)
            if ctx.sender_id == "subagent":
                current_role = "user"
                current_message = f"[Subagent completed] {msg.content}"
            else:
                current_role = "user"
                current_message = msg.content
            messages = self.context.build_messages(
                history=history,
                current_message=current_message, channel=ctx.channel, chat_id=ctx.chat_id,
                current_role=current_role,
                channel_name=ctx.channel_name,
                sender_name=ctx.sender_name,
                layout=layout,
            )
            result = await self._run_agent_loop(
                messages, channel=ctx.channel, chat_id=ctx.chat_id,
                message_id=ctx.message_id, layout=layout,
            )
            self._save_turn(session, result, 1 + len(history), ctx=ctx)
            self.sessions.save(session)
            self._schedule_background(self.memory_consolidator.maybe_consolidate_by_tokens(session))
            return OutboundMessage(channel=ctx.channel, chat_id=ctx.chat_id,
                                  content=result.final_content or "Background task completed.")

        ctx = TurnContext.from_message(msg)
        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info("Processing message from {}:{}: {}", ctx.channel, ctx.sender_id, preview)

        key = session_key or msg.session_key
        layout = self._resolve_layout(ctx, session_key=session_key)
        session = self.sessions.get_or_create_from_layout(layout) if layout else self.sessions.get_or_create(key)
        self._update_runtime_metadata(session, ctx)

        # Slash commands
        raw = msg.content.strip()
        cmd_ctx = CommandContext(
            msg=msg, session=session, key=key, raw=raw, loop=self, layout=layout,
            interaction_id=(msg.metadata or {}).get("interaction_id"),
            interaction_token=(msg.metadata or {}).get("interaction_token"),
        )
        if result := await self.commands.dispatch(cmd_ctx):
            return result

        # Slash command 来的 skill 请求：/{skill} {input} → 自然语言指令
        if cmd_ctx.interaction_token and raw.startswith("/"):
            parts = raw.split(None, 1)
            skill_name = parts[0].lstrip("/")
            skill_input = parts[1] if len(parts) > 1 else ""
            msg.content = f"Use the {skill_name} skill. {skill_input}".strip()

        await self.memory_consolidator.maybe_consolidate_by_tokens(session)

        self._set_tool_context(
            ctx.channel, ctx.chat_id, ctx.message_id,
            session_metadata=session.metadata,
        )
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.start_turn()

        history = session.get_history(max_messages=0)
        initial_messages = self.context.build_messages(
            history=history,
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=ctx.channel, chat_id=ctx.chat_id,
            channel_name=ctx.channel_name,
            sender_name=ctx.sender_name,
            layout=layout,
        )

        async def _bus_progress(content: str, *, tool_hint: bool = False) -> None:
            meta = dict(msg.metadata or {})
            meta["_progress"] = True
            meta["_tool_hint"] = tool_hint
            await self.bus.publish_outbound(OutboundMessage(
                channel=ctx.channel, chat_id=ctx.chat_id, content=content, metadata=meta,
            ))

        result = await self._run_agent_loop(
            initial_messages,
            on_progress=on_progress or _bus_progress,
            on_stream=on_stream,
            on_stream_end=on_stream_end,
            channel=ctx.channel, chat_id=ctx.chat_id,
            message_id=ctx.message_id, layout=layout,
        )

        final_content = result.final_content
        if final_content is None:
            final_content = "I've completed processing but have no response to give."

        self._save_turn(session, result, 1 + len(history), ctx=ctx)
        self.sessions.save(session)
        self._schedule_background(self.memory_consolidator.maybe_consolidate_by_tokens(session))

        if (mt := self.tools.get("message")) and isinstance(mt, MessageTool) and mt._sent_in_turn:
            return None

        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info("Response to {}:{}: {}", ctx.channel, ctx.sender_id, preview)

        meta = dict(msg.metadata or {})
        if on_stream is not None:
            meta["_streamed"] = True
        meta["_session_tts"] = session.metadata.get("tts", False)
        return OutboundMessage(
            channel=ctx.channel, chat_id=ctx.chat_id, content=final_content,
            metadata=meta,
        )

    @staticmethod
    def _image_placeholder(block: dict[str, Any]) -> dict[str, str]:
        """Convert an inline image block into a compact text placeholder."""
        path = (block.get("_meta") or {}).get("path", "")
        return {"type": "text", "text": f"[image: {path}]" if path else "[image]"}

    def _sanitize_persisted_blocks(
        self,
        content: list[dict[str, Any]],
        *,
        truncate_text: bool = False,
        drop_runtime: bool = False,
    ) -> list[dict[str, Any]]:
        """Strip volatile multimodal payloads before writing session history."""
        filtered: list[dict[str, Any]] = []
        for block in content:
            if not isinstance(block, dict):
                filtered.append(block)
                continue

            if (
                drop_runtime
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
                and block["text"].startswith(ContextBuilder._RUNTIME_CONTEXT_TAG)
            ):
                continue

            if (
                block.get("type") == "image_url"
                and block.get("image_url", {}).get("url", "").startswith("data:image/")
            ):
                filtered.append(self._image_placeholder(block))
                continue

            if block.get("type") == "text" and isinstance(block.get("text"), str):
                text = block["text"]
                if truncate_text and len(text) > self._TOOL_RESULT_MAX_CHARS:
                    text = text[:self._TOOL_RESULT_MAX_CHARS] + "\n... (truncated)"
                filtered.append({**block, "text": text})
                continue

            filtered.append(block)

        return filtered

    def _update_runtime_metadata(self, session: Session, ctx: TurnContext) -> None:
        """Keep runtime context fresh on every turn."""
        session.metadata["runtime"] = {
            "model": self.model,
            "context_window": self.context_window_tokens,
            "channel": ctx.channel,
            "chat_id": ctx.chat_id,
            "channel_name": ctx.channel_name,
        }

    def _save_turn(self, session: Session, result: AgentRunResult, skip: int,
                   ctx: TurnContext | None = None) -> None:
        """Save new-turn messages into session, truncating large tool results."""
        from datetime import datetime
        sender_id = ctx.sender_id if ctx else None
        sender_name = ctx.sender_name if ctx else None
        new_msgs = result.messages[skip:]
        usage = result.usage
        # Find the last assistant message index to attach usage
        last_assistant_idx = -1
        if usage:
            for i in range(len(new_msgs) - 1, -1, -1):
                if new_msgs[i].get("role") == "assistant":
                    last_assistant_idx = i
                    break
        first_user_seen = False
        for idx, m in enumerate(new_msgs):
            entry = dict(m)
            role, content = entry.get("role"), entry.get("content")
            if role == "assistant" and not content and not entry.get("tool_calls"):
                continue  # skip empty assistant messages — they poison session context
            if role == "assistant":
                entry.setdefault("model", self.model)
                if idx == last_assistant_idx:
                    if usage:
                        entry["usage"] = usage
                    if result.elapsed_ms:
                        entry["elapsed_ms"] = result.elapsed_ms
                    if result.llm_elapsed_ms:
                        entry["llm_elapsed_ms"] = result.llm_elapsed_ms
            if role == "tool":
                if isinstance(content, str) and len(content) > self._TOOL_RESULT_MAX_CHARS:
                    entry["content"] = content[:self._TOOL_RESULT_MAX_CHARS] + "\n... (truncated)"
                elif isinstance(content, list):
                    filtered = self._sanitize_persisted_blocks(content, truncate_text=True)
                    if not filtered:
                        continue
                    entry["content"] = filtered
            elif role == "user":
                if not first_user_seen:
                    first_user_seen = True
                    if sender_id:
                        entry["sender_id"] = sender_id
                    if sender_name:
                        entry["sender_name"] = sender_name
                if isinstance(content, str) and content.startswith(ContextBuilder._RUNTIME_CONTEXT_TAG):
                    # Strip the runtime-context prefix, keep only the user text.
                    parts = content.split("\n\n", 1)
                    if len(parts) > 1 and parts[1].strip():
                        entry["content"] = parts[1]
                    else:
                        continue
                if isinstance(content, list):
                    filtered = self._sanitize_persisted_blocks(content, drop_runtime=True)
                    if not filtered:
                        continue
                    entry["content"] = filtered
            entry.setdefault("timestamp", datetime.now().isoformat())
            session.messages.append(entry)

        # Emit skill-load events for read_file calls targeting SKILL.md
        loaded_skills = self._extract_loaded_skills(new_msgs)
        if loaded_skills:
            session.events.append({
                "_type": "event",
                "event": "skill_loaded",
                "skills": loaded_skills,
                "sender": sender_name,
                "timestamp": datetime.now().isoformat(),
            })

        session.updated_at = datetime.now()

    @staticmethod
    def _extract_loaded_skills(messages: list[dict]) -> list[str]:
        """Extract skill names from read_file tool calls targeting SKILL.md."""
        skills = []
        for m in messages:
            if m.get("role") != "assistant":
                continue
            for tc in m.get("tool_calls", []):
                func = tc.get("function", {})
                if func.get("name") != "read_file":
                    continue
                import json as _json
                try:
                    args = _json.loads(func.get("arguments", "{}"))
                except (ValueError, TypeError):
                    continue
                path = args.get("path", "")
                if path.endswith("/SKILL.md") or path.endswith("\\SKILL.md"):
                    # Extract skill name: parent directory name
                    parts = path.replace("\\", "/").rstrip("/").split("/")
                    if len(parts) >= 2:
                        skills.append(parts[-2])
        return skills

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
        on_stream: Callable[[str], Awaitable[None]] | None = None,
        on_stream_end: Callable[..., Awaitable[None]] | None = None,
    ) -> OutboundMessage | None:
        """Process a message directly and return the outbound payload."""
        await self._connect_mcp()
        msg = InboundMessage(channel=channel, sender_id="user", chat_id=chat_id, content=content)
        return await self._process_message(
            msg, session_key=session_key, on_progress=on_progress,
            on_stream=on_stream, on_stream_end=on_stream_end,
        )
