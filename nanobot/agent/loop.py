"""Agent loop: the core processing engine."""

from __future__ import annotations

import asyncio
import json
import re
from contextlib import AsyncExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

try:
    import tiktoken  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    tiktoken = None

from nanobot.agent.context import ContextBuilder
from nanobot.agent.subagent import SubagentManager
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.huggingface import HuggingFaceModelSearchTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.model_config import ValidateDeployJSONTool, ValidateUsageYAMLTool
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
        memory_window: int | None = None,  # backward-compat only (unused)
        reasoning_effort: str | None = None,
        max_tokens_input: int = 128_000,
        compression_start_ratio: float = 0.7,
        compression_target_ratio: float = 0.4,
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
        # max_tokens: per-call output token cap (maxTokensOutput in config)
        self.max_tokens = max_tokens
        # Keep legacy attribute for older call sites/tests; compression no longer uses it.
        self.memory_window = memory_window
        self.reasoning_effort = reasoning_effort
        # max_tokens_input: model native context window (maxTokensInput in config)
        self.max_tokens_input = max_tokens_input
        # Token-based compression watermarks (fractions of available input budget)
        self.compression_start_ratio = compression_start_ratio
        self.compression_target_ratio = compression_target_ratio
        # Reserve tokens for safety margin
        self._reserve_tokens = 1000
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
        self._active_tasks: dict[str, list[asyncio.Task]] = {}  # session_key -> tasks
        self._compression_tasks: dict[str, asyncio.Task] = {}  # session_key -> task
        self._processing_lock = asyncio.Lock()
        self._register_default_tools()

    @staticmethod
    def _estimate_prompt_tokens(
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> int:
        """Estimate prompt tokens with tiktoken (fallback only)."""
        if tiktoken is None:
            return 0

        try:
            enc = tiktoken.get_encoding("cl100k_base")
            parts: list[str] = []
            for msg in messages:
                content = msg.get("content")
                if isinstance(content, str):
                    parts.append(content)
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            txt = part.get("text", "")
                            if txt:
                                parts.append(txt)
            if tools:
                parts.append(json.dumps(tools, ensure_ascii=False))
            return len(enc.encode("\n".join(parts)))
        except Exception:
            return 0

    def _estimate_prompt_tokens_chain(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> tuple[int, str]:
        """Unified prompt-token estimation: provider counter -> tiktoken."""
        provider_counter = getattr(self.provider, "estimate_prompt_tokens", None)
        if callable(provider_counter):
            try:
                tokens, source = provider_counter(messages, tools, self.model)
                if isinstance(tokens, (int, float)) and tokens > 0:
                    return int(tokens), str(source or "provider_counter")
            except Exception:
                logger.debug("Provider token counter failed; fallback to tiktoken")

        estimated = self._estimate_prompt_tokens(messages, tools)
        if estimated > 0:
            return int(estimated), "tiktoken"
        return 0, "none"

    @staticmethod
    def _estimate_completion_tokens(content: str) -> int:
        """Estimate completion tokens with tiktoken (fallback only)."""
        if tiktoken is None:
            return 0
        try:
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(content or ""))
        except Exception:
            return 0

    def _get_compressed_until(self, session: Session) -> int:
        """Read/normalize compressed boundary and migrate old metadata format."""
        raw = session.metadata.get("_compressed_until", 0)
        try:
            compressed_until = int(raw)
        except (TypeError, ValueError):
            compressed_until = 0

        if compressed_until <= 0:
            ranges = session.metadata.get("_compressed_ranges")
            if isinstance(ranges, list):
                inferred = 0
                for item in ranges:
                    if not isinstance(item, (list, tuple)) or len(item) != 2:
                        continue
                    try:
                        inferred = max(inferred, int(item[1]))
                    except (TypeError, ValueError):
                        continue
                compressed_until = inferred

        compressed_until = max(0, min(compressed_until, len(session.messages)))
        session.metadata["_compressed_until"] = compressed_until
        # 兼容旧版本：一旦迁移出连续边界，就可以清理旧字段
        session.metadata.pop("_compressed_ranges", None)
        # 注意：不要删除 _cumulative_tokens，压缩逻辑需要它来跟踪累积 token 计数
        return compressed_until

    def _set_compressed_until(self, session: Session, idx: int) -> None:
        """Persist a contiguous compressed boundary."""
        session.metadata["_compressed_until"] = max(0, min(int(idx), len(session.messages)))
        session.metadata.pop("_compressed_ranges", None)
        # 注意：不要删除 _cumulative_tokens，压缩逻辑需要它来跟踪累积 token 计数

    @staticmethod
    def _estimate_message_tokens(message: dict[str, Any]) -> int:
        """Rough token estimate for a single persisted message."""
        content = message.get("content")
        parts: list[str] = []
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    txt = part.get("text", "")
                    if txt:
                        parts.append(txt)
                else:
                    parts.append(json.dumps(part, ensure_ascii=False))
        elif content is not None:
            parts.append(json.dumps(content, ensure_ascii=False))

        for key in ("name", "tool_call_id"):
            val = message.get(key)
            if isinstance(val, str) and val:
                parts.append(val)
        if message.get("tool_calls"):
            parts.append(json.dumps(message["tool_calls"], ensure_ascii=False))

        payload = "\n".join(parts)
        if not payload:
            return 1
        if tiktoken is not None:
            try:
                enc = tiktoken.get_encoding("cl100k_base")
                return max(1, len(enc.encode(payload)))
            except Exception:
                pass
        return max(1, len(payload) // 4)

    def _pick_compression_chunk_by_tokens(
        self,
        session: Session,
        reduction_tokens: int,
        *,
        tail_keep: int = 12,
    ) -> tuple[int, int, int] | None:
        """
        Pick one contiguous old chunk so its estimated size is roughly enough
        to reduce `reduction_tokens`.
        """
        messages = session.messages
        start = self._get_compressed_until(session)
        if len(messages) - start <= tail_keep + 2:
            return None

        end_limit = len(messages) - tail_keep
        if end_limit - start < 2:
            return None

        target = max(1, reduction_tokens)
        end = start
        collected = 0
        while end < end_limit and collected < target:
            collected += self._estimate_message_tokens(messages[end])
            end += 1

        if end - start < 2:
            end = min(end_limit, start + 2)
            collected = sum(self._estimate_message_tokens(m) for m in messages[start:end])
        if end - start < 2:
            return None
        return start, end, collected

    def _estimate_session_prompt_tokens(self, session: Session) -> tuple[int, str]:
        """
        Estimate current full prompt tokens for this session view
        (system + compressed history view + runtime/user placeholder + tools).
        """
        history = self._build_compressed_history_view(session)
        channel, chat_id = (session.key.split(":", 1) if ":" in session.key else (None, None))
        probe_messages = self.context.build_messages(
            history=history,
            current_message="[token-probe]",
            channel=channel,
            chat_id=chat_id,
        )
        return self._estimate_prompt_tokens_chain(probe_messages, self.tools.get_definitions())

    async def _maybe_compress_history(
        self,
        session: Session,
    ) -> None:
        """
        End-of-turn policy:
        - Estimate current prompt usage from persisted session view.
        - If above start ratio, perform one best-effort compression chunk.
        """
        if not session.messages:
            self._set_compressed_until(session, 0)
            return

        budget = max(1, self.max_tokens_input - self.max_tokens - self._reserve_tokens)
        start_threshold = int(budget * self.compression_start_ratio)
        target_threshold = int(budget * self.compression_target_ratio)
        if target_threshold >= start_threshold:
            target_threshold = max(0, start_threshold - 1)

        current_tokens, token_source = self._estimate_session_prompt_tokens(session)
        current_ratio = current_tokens / budget if budget else 0.0
        if current_tokens <= 0:
            logger.debug("Compression skip {}: token estimate unavailable", session.key)
            return
        if current_tokens < start_threshold:
            logger.debug(
                "Compression idle {}: {}/{} ({:.1%}) via {}",
                session.key,
                current_tokens,
                budget,
                current_ratio,
                token_source,
            )
            return
        logger.info(
            "Compression trigger {}: {}/{} ({:.1%}) via {}",
            session.key,
            current_tokens,
            budget,
            current_ratio,
            token_source,
        )

        reduction_by_target = max(0, current_tokens - target_threshold)
        reduction_by_delta = max(1, start_threshold - target_threshold)
        reduction_need = max(reduction_by_target, reduction_by_delta)

        chunk_range = self._pick_compression_chunk_by_tokens(session, reduction_need, tail_keep=10)
        if chunk_range is None:
            logger.info("Compression skipped for {}: no compressible chunk", session.key)
            return

        start_idx, end_idx, estimated_chunk_tokens = chunk_range
        chunk = session.messages[start_idx:end_idx]
        if len(chunk) < 2:
            return

        logger.info(
            "Compression chunk {}: msgs {}-{} (count={}, est~{}, need~{})",
            session.key,
            start_idx,
            end_idx - 1,
            len(chunk),
            estimated_chunk_tokens,
            reduction_need,
        )
        success, _ = await self.context.memory.consolidate_chunk(
            chunk,
            self.provider,
            self.model,
        )
        if not success:
            logger.warning("Compression aborted for {}: consolidation failed", session.key)
            return

        self._set_compressed_until(session, end_idx)
        self.sessions.save(session)

        after_tokens, after_source = self._estimate_session_prompt_tokens(session)
        after_ratio = after_tokens / budget if budget else 0.0
        reduced = max(0, current_tokens - after_tokens)
        reduced_ratio = (reduced / current_tokens) if current_tokens > 0 else 0.0
        logger.info(
            "Compression done {}: {}/{} ({:.1%}) via {}, reduced={} ({:.1%})",
            session.key,
            after_tokens,
            budget,
            after_ratio,
            after_source,
            reduced,
            reduced_ratio,
        )

    def _schedule_background_compression(self, session_key: str) -> None:
        """Schedule best-effort background compression for a session."""
        existing = self._compression_tasks.get(session_key)
        if existing is not None and not existing.done():
            return

        async def _runner() -> None:
            session = self.sessions.get_or_create(session_key)
            try:
                await self._maybe_compress_history(session)
            except Exception:
                logger.exception("Background compression failed for {}", session_key)

        task = asyncio.create_task(_runner())
        self._compression_tasks[session_key] = task

        def _cleanup(t: asyncio.Task) -> None:
            cur = self._compression_tasks.get(session_key)
            if cur is t:
                self._compression_tasks.pop(session_key, None)
            try:
                t.result()
            except BaseException:
                pass

        task.add_done_callback(_cleanup)

    async def wait_for_background_compression(self, timeout_s: float | None = None) -> None:
        """Wait for currently scheduled compression tasks."""
        pending = [t for t in self._compression_tasks.values() if not t.done()]
        if not pending:
            return

        logger.info("Waiting for {} background compression task(s)", len(pending))
        waiter = asyncio.gather(*pending, return_exceptions=True)
        if timeout_s is None:
            await waiter
            return

        try:
            await asyncio.wait_for(waiter, timeout=timeout_s)
        except asyncio.TimeoutError:
            logger.warning(
                "Background compression wait timed out after {}s ({} task(s) still running)",
                timeout_s,
                len([t for t in self._compression_tasks.values() if not t.done()]),
            )

    def _build_compressed_history_view(
        self,
        session: Session,
    ) -> list[dict]:
        """Build non-destructive history view using the compressed boundary."""
        compressed_until = self._get_compressed_until(session)
        if compressed_until <= 0:
            return session.get_history(max_messages=0)

        notice_msg: dict[str, Any] = {
            "role": "assistant",
            "content": (
                "As your assistant, I have compressed earlier context. "
                "If you need details, please check memory/HISTORY.md."
            ),
        }

        tail: list[dict[str, Any]] = []
        for msg in session.messages[compressed_until:]:
            entry: dict[str, Any] = {"role": msg["role"], "content": msg.get("content", "")}
            for k in ("tool_calls", "tool_call_id", "name"):
                if k in msg:
                    entry[k] = msg[k]
            tail.append(entry)

        # Drop leading non-user entries from tail to avoid orphan tool blocks.
        for i, m in enumerate(tail):
            if m.get("role") == "user":
                tail = tail[i:]
                break
        else:
            tail = []

        return [notice_msg, *tail]

    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        for cls in (ReadFileTool, WriteFileTool, EditFileTool, ListDirTool):
            self.tools.register(cls(workspace=self.workspace, allowed_dir=allowed_dir))
        self.tools.register(ValidateDeployJSONTool())
        self.tools.register(ValidateUsageYAMLTool())
        self.tools.register(HuggingFaceModelSearchTool())
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

    async def _run_agent_loop(
        self,
        initial_messages: list[dict],
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> tuple[str | None, list[str], list[dict], int, str]:
        """
        Run the agent iteration loop.

        Returns:
            (final_content, tools_used, messages, total_tokens_this_turn, token_source)
            total_tokens_this_turn: total tokens (prompt + completion) for this turn
            token_source: provider_total / provider_sum / provider_prompt /
                          provider_counter+tiktoken_completion / tiktoken / none
        """
        messages = initial_messages
        iteration = 0
        final_content = None
        tools_used: list[str] = []
        total_tokens_this_turn = 0
        token_source = "none"

        while iteration < self.max_iterations:
            iteration += 1

            tool_defs = self.tools.get_definitions()

            response = await self.provider.chat(
                messages=messages,
                tools=tool_defs,
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                reasoning_effort=self.reasoning_effort,
            )

            # Prefer provider usage from the turn-ending model call; fallback to tiktoken.
            # Calculate total tokens (prompt + completion) for this turn.
            usage = response.usage or {}
            t_tokens = usage.get("total_tokens")
            p_tokens = usage.get("prompt_tokens")
            c_tokens = usage.get("completion_tokens")
            
            if isinstance(t_tokens, (int, float)) and t_tokens > 0:
                total_tokens_this_turn = int(t_tokens)
                token_source = "provider_total"
            elif isinstance(p_tokens, (int, float)) and isinstance(c_tokens, (int, float)):
                # If we have both prompt and completion tokens, sum them
                total_tokens_this_turn = int(p_tokens) + int(c_tokens)
                token_source = "provider_sum"
            elif isinstance(p_tokens, (int, float)) and p_tokens > 0:
                # Fallback: use prompt tokens only (completion might be 0 for tool calls)
                total_tokens_this_turn = int(p_tokens)
                token_source = "provider_prompt"
            else:
                # Estimate with unified chain (provider counter -> tiktoken), plus completion tiktoken.
                estimated_prompt, prompt_source = self._estimate_prompt_tokens_chain(messages, tool_defs)
                estimated_completion = self._estimate_completion_tokens(response.content or "")
                total_tokens_this_turn = estimated_prompt + estimated_completion
                if total_tokens_this_turn > 0:
                    token_source = (
                        "tiktoken"
                        if prompt_source == "tiktoken"
                        else f"{prompt_source}+tiktoken_completion"
                    )
                if total_tokens_this_turn <= 0:
                    total_tokens_this_turn = 0
                    token_source = "none"

            logger.debug(
                "Turn token usage: source={}, total={}, prompt={}, completion={}",
                token_source,
                total_tokens_this_turn,
                p_tokens if isinstance(p_tokens, (int, float)) else None,
                c_tokens if isinstance(c_tokens, (int, float)) else None,
            )

            if response.has_tool_calls:
                if on_progress:
                    thought = self._strip_think(response.content)
                    if thought:
                        await on_progress(thought)
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

        return final_content, tools_used, messages, total_tokens_this_turn, token_source

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

            if msg.content.strip().lower() == "/stop":
                await self._handle_stop(msg)
            else:
                task = asyncio.create_task(self._dispatch(msg))
                self._active_tasks.setdefault(msg.session_key, []).append(task)
                task.add_done_callback(lambda t, k=msg.session_key: self._active_tasks.get(k, []) and self._active_tasks[k].remove(t) if t in self._active_tasks.get(k, []) else None)

    async def _handle_stop(self, msg: InboundMessage) -> None:
        """Cancel all active tasks and subagents for the session."""
        tasks = self._active_tasks.pop(msg.session_key, [])
        cancelled = sum(1 for t in tasks if not t.done() and t.cancel())
        comp = self._compression_tasks.get(msg.session_key)
        if comp is not None and not comp.done() and comp.cancel():
            cancelled += 1
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
        for task in list(self._compression_tasks.values()):
            if not task.done():
                task.cancel()
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
            history = self._build_compressed_history_view(session)
            messages = self.context.build_messages(
                history=history,
                current_message=msg.content, channel=channel, chat_id=chat_id,
            )
            final_content, _, all_msgs, _, _ = await self._run_agent_loop(messages)
            self._save_turn(session, all_msgs, 1 + len(history))
            self.sessions.save(session)
            self._schedule_background_compression(session.key)
            return OutboundMessage(channel=channel, chat_id=chat_id,
                                  content=final_content or "Background task completed.")

        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info("Processing message from {}:{}: {}", msg.channel, msg.sender_id, preview)

        key = session_key or msg.session_key
        session = self.sessions.get_or_create(key)

        # Slash commands
        cmd = msg.content.strip().lower()
        if cmd == "/new":
            try:
                # 在清空会话前，将当前完整对话做一次归档压缩到 MEMORY/HISTORY 中
                if session.messages:
                    ok, _ = await self.context.memory.consolidate_chunk(
                        session.messages,
                        self.provider,
                        self.model,
                    )
                    if not ok:
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

            session.clear()
            self.sessions.save(session)
            self.sessions.invalidate(session.key)
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content="New session started.")
        if cmd == "/help":
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content="🐈 nanobot commands:\n/new — Start a new conversation\n/stop — Stop the current task\n/help — Show available commands")

        self._set_tool_context(msg.channel, msg.chat_id, msg.metadata.get("message_id"))
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.start_turn()

        # 正常对话：使用压缩后的历史视图（压缩在回合结束后进行）
        history = self._build_compressed_history_view(session)
        initial_messages = self.context.build_messages(
            history=history,
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel, chat_id=msg.chat_id,
        )
        # Add [CRON JOB] identifier for cron sessions (session_key starts with "cron:")
        if session_key and session_key.startswith("cron:"):
            if initial_messages and initial_messages[0].get("role") == "system":
                initial_messages[0]["content"] = f"[CRON JOB] {initial_messages[0]['content']}"

        async def _bus_progress(content: str, *, tool_hint: bool = False) -> None:
            meta = dict(msg.metadata or {})
            meta["_progress"] = True
            meta["_tool_hint"] = tool_hint
            await self.bus.publish_outbound(OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id, content=content, metadata=meta,
            ))

        final_content, _, all_msgs, total_tokens_this_turn, token_source = await self._run_agent_loop(
            initial_messages, on_progress=on_progress or _bus_progress,
        )

        if final_content is None:
            final_content = "I've completed processing but have no response to give."

        self._save_turn(session, all_msgs, 1 + len(history), total_tokens_this_turn)
        self.sessions.save(session)
        self._schedule_background_compression(session.key)

        if (mt := self.tools.get("message")) and isinstance(mt, MessageTool) and mt._sent_in_turn:
            return None

        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info("Response to {}:{}: {}", msg.channel, msg.sender_id, preview)
        return OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=final_content,
            metadata=msg.metadata or {},
        )

    def _save_turn(self, session: Session, messages: list[dict], skip: int, total_tokens_this_turn: int = 0) -> None:
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
        
        # Update cumulative token count for compression tracking
        if total_tokens_this_turn > 0:
            current_cumulative = session.metadata.get("_cumulative_tokens", 0)
            if isinstance(current_cumulative, (int, float)):
                session.metadata["_cumulative_tokens"] = int(current_cumulative) + total_tokens_this_turn
            else:
                session.metadata["_cumulative_tokens"] = total_tokens_this_turn

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
