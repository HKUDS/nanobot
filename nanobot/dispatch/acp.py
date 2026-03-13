from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ACPBackendConfig, ChannelsConfig, MCPServerConfig


class _StreamState:
    def __init__(self, on_progress: Callable[..., Awaitable[None]] | None = None):
        self.text = ""
        self.on_progress = on_progress

    def merge_text(self, chunk: str) -> None:
        if not chunk:
            return
        if not self.text:
            self.text = chunk
            return
        if chunk.startswith(self.text):
            self.text = chunk
            return
        if self.text.endswith(chunk):
            return
        self.text += chunk

    def final(self) -> str:
        return self.text.strip()


class _ACPDispatchError(RuntimeError):
    def __init__(self, partial_response: str = "") -> None:
        super().__init__("ACP dispatch failed")
        self.partial_response = partial_response


class _SessionCapabilities:
    def __init__(self) -> None:
        self.available_models: list[str] = []
        self.current_model: str | None = None
        self.available_agents: list[str] = []
        self.current_agent: str | None = None


class _ProgressCoalescer:
    """
    进度聚合器：用于将 ACP 传来的细碎文本 chunk 聚合成较大的块再下发。

    设计思路：
    - ACP 的 session_update 会频繁发送文本片段（如 "我" -> "我先" -> "我先把"），
      如果每个片段都直接发到 Telegram，会导致逐字刷屏。
    - 此聚合器缓存文本，满足以下任一条件时才真正下发：
      1) 累计超过 max_chars（默认1024字符）
      2) 收到 tool_hint（工具提示）时先 flush 缓存的文本
      3) 超过 idle_flush_seconds（默认3秒）没有新内容
      4) 会话结束（finalize）时强制 flush

    防重复机制：
    - ACP 有时会发送"全量前缀"（如 "我先" 包含 "我"），
      _merge_text 会智能去重，避免 "我我先先把把" 这样的重复。
    """

    def __init__(
        self,
        *,
        publish: Callable[..., Awaitable[None]],
        max_chars: int,
        idle_flush_seconds: float,
    ) -> None:
        self._publish = publish  # 下发函数，将聚合后的文本发送到 MessageBus
        self._max_chars = max_chars  # 触发下发的最大字符数阈值
        self._idle_flush_seconds = idle_flush_seconds  # 空闲超时时间（秒）
        self._merged = ""  # 当前累计的完整文本（去重后）
        self._sent_prefix = ""  # 已经下发过的文本前缀
        self._lock = asyncio.Lock()  # 并发锁，保证状态一致性
        self._watchdog: asyncio.Task[Any] | None = None  # 空闲超时监控任务

    @staticmethod
    def _merge_text(current: str, chunk: str) -> str:
        """
        智能合并文本片段，处理 ACP 的"全量前缀"重复问题。

        场景：ACP 可能先传 "我"，再传 "我先"（包含之前的 "我"）
        - 如果 chunk 以 current 开头（如 current="我", chunk="我先"），直接用 chunk
        - 如果 current 以 chunk 结尾（如 current="我先", chunk="先"），保持 current
        - 否则是真正的增量，追加到 current

        这样可以避免 "我我先先把把目录" 这样的重复文本。
        """
        if not chunk:
            return current
        if not current:
            return chunk
        if chunk.startswith(current):
            return chunk
        if current.endswith(chunk):
            return current
        return current + chunk

    def _pending_text(self) -> str:
        """
        计算尚未下发的文本增量。

        思路：
        - _merged 是累计的完整文本
        - _sent_prefix 是已经下发过的部分
        - 两者的差值就是需要新下发的内容

        例如：
        - _merged="我先把目录"，_sent_prefix="我先把"
        - 返回 "目录"（只需下发新增部分）
        """
        if not self._merged:
            return ""
        if self._merged.startswith(self._sent_prefix):
            return self._merged[len(self._sent_prefix) :]
        return self._merged

    def _reset_watchdog_locked(self) -> None:
        if self._watchdog and not self._watchdog.done():
            self._watchdog.cancel()
        self._watchdog = asyncio.create_task(self._watchdog_loop())

    async def _watchdog_loop(self) -> None:
        try:
            await asyncio.sleep(self._idle_flush_seconds)
            await self.flush(reason="idle_timeout")
        except asyncio.CancelledError:
            pass

    async def add_text(self, chunk: str) -> None:
        async with self._lock:
            self._merged = self._merge_text(self._merged, chunk)
            pending = self._pending_text()
            if not pending:
                return
            self._reset_watchdog_locked()
            if len(pending) >= self._max_chars:
                await self._flush_locked(reason="size_limit")

    async def emit_tool_hint(self, content: str) -> None:
        async with self._lock:
            await self._flush_locked(reason="tool_hint")
            if content:
                await self._publish(content, tool_hint=True)

    async def flush(self, *, reason: str) -> None:
        async with self._lock:
            await self._flush_locked(reason=reason)

    async def _flush_locked(self, *, reason: str) -> None:
        """
        真正执行下发操作（必须在持有 _lock 时调用）。

        关键逻辑：
        1. 计算待下发的文本（_pending_text）
        2. 更新 _sent_prefix 标记已下发部分
        3. 取消 watchdog，但避免取消当前正在执行的任务自己（防止 idle timeout 时自己取消自己）
        4. 调用 _publish 下发到 MessageBus

        参数 reason：记录触发原因（tool_hint/size_limit/idle_timeout/finalize/acp_error），用于日志调试
        """
        pending = self._pending_text()
        if not pending:
            return
        self._sent_prefix = self._merged
        # 关键：判断 watchdog 是否是当前任务自己，避免自己取消自己
        watchdog = self._watchdog
        current = asyncio.current_task()
        if watchdog and watchdog is not current and not watchdog.done():
            watchdog.cancel()
        self._watchdog = None
        logger.debug("ACP progress flush reason={} chars={}", reason, len(pending))
        await self._publish(pending, tool_hint=False)


class ACPDispatcher:
    _PROGRESS_BUFFER_MAX_CHARS = 4096
    _PROGRESS_IDLE_FLUSH_SECONDS = 3.0

    _HELP_TEXT = (
        "🐈 nanobot commands:\n"
        "/new — Start a new conversation\n"
        "/stop — Stop the current task\n"
        "/help — Show available commands\n"
        "/models — List available/current models\n"
        "/set_model <model_id> — Switch model\n"
        "/agents — List available/current agents\n"
        "/set_agent <agent_id> — Switch agent"
    )

    def __init__(
        self,
        *,
        bus: MessageBus,
        workspace: Path,
        acp_config: ACPBackendConfig,
        mcp_servers: dict[str, MCPServerConfig] | None = None,
        channels_config: ChannelsConfig | None = None,
    ):
        self.bus = bus
        self.workspace = workspace
        self.channels_config = channels_config
        self.acp_config = acp_config
        self.mcp_servers = mcp_servers or {}

        self._running = False
        self._conn_cm = None
        self._conn = None
        self._proc = None
        self._connect_lock = asyncio.Lock()
        self._session_map: dict[str, str] = {}
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._process_locks: dict[str, asyncio.Lock] = {}
        self._session_states: dict[str, _StreamState] = {}
        self._session_caps: dict[str, _SessionCapabilities] = {}
        self._active_tasks: dict[str, list[asyncio.Task[Any]]] = {}
        self.last_target: tuple[str, str] | None = None

    @staticmethod
    def _pick(obj: Any, *names: str) -> Any:
        for name in names:
            if hasattr(obj, name):
                return getattr(obj, name)
        return None

    @staticmethod
    def _parse_command(content: str) -> tuple[str, str]:
        raw = content.strip()
        if not raw:
            return "", ""
        parts = raw.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""
        return cmd, arg

    @staticmethod
    def _preview_text(text: str, *, limit: int = 160) -> str:
        if not text:
            return ""
        normalized = text.replace("\r", " ").replace("\n", "\\n")
        if len(normalized) > limit:
            return f"{normalized[:limit]}..."
        return normalized

    def _update_caps_from_session_payload(self, session_id: str, payload: Any) -> None:
        caps = self._session_caps.setdefault(session_id, _SessionCapabilities())
        models = self._pick(payload, "models")
        if models is not None:
            current = self._pick(models, "current_model_id", "currentModelId")
            if isinstance(current, str) and current:
                caps.current_model = current
            available = self._pick(models, "available_models", "availableModels") or []
            parsed_models: list[str] = []
            for entry in available:
                model_id = self._pick(entry, "model_id", "modelId")
                if isinstance(model_id, str) and model_id:
                    parsed_models.append(model_id)
            if parsed_models:
                caps.available_models = parsed_models

        modes = self._pick(payload, "modes")
        if modes is not None:
            current = self._pick(modes, "current_mode_id", "currentModeId")
            if isinstance(current, str) and current:
                caps.current_agent = current
            available = self._pick(modes, "available_modes", "availableModes") or []
            parsed_agents: list[str] = []
            for entry in available:
                mode_id = self._pick(entry, "id")
                if isinstance(mode_id, str) and mode_id:
                    parsed_agents.append(mode_id)
            if parsed_agents:
                caps.available_agents = parsed_agents

    async def _list_models_command(self, session_id: str) -> str:
        caps = self._session_caps.get(session_id)
        if not caps or not caps.available_models:
            return "No model catalog returned by current ACP backend for this session."
        lines = []
        current = caps.current_model
        for model_id in caps.available_models:
            prefix = "* " if current == model_id else "  "
            lines.append(f"{prefix}{model_id}")
        header = f"Current model: {current}" if current else "Current model: unknown"
        return "\n".join([header, "Available models:", *lines])

    async def _list_agents_command(self, session_id: str) -> str:
        caps = self._session_caps.get(session_id)
        if not caps or not caps.available_agents:
            return "No agent/mode catalog returned by current ACP backend for this session."
        lines = []
        current = caps.current_agent
        for agent_id in caps.available_agents:
            prefix = "* " if current == agent_id else "  "
            lines.append(f"{prefix}{agent_id}")
        header = f"Current agent: {current}" if current else "Current agent: unknown"
        return "\n".join([header, "Available agents:", *lines])

    async def _emit_progress(
        self,
        callback: Callable[..., Awaitable[None]] | None,
        content: str,
        *,
        tool_hint: bool = False,
    ) -> None:
        if not callback or not content:
            return
        try:
            await callback(content, tool_hint=tool_hint)
        except TypeError:
            await callback(content)

    async def _permission_response(self, options: list[Any]) -> Any:
        from acp.schema import RequestPermissionResponse

        policy = self.acp_config.permissions_policy
        if policy == "strict":
            return RequestPermissionResponse.model_validate({"outcome": {"outcome": "cancelled"}})

        preferred = "allow_always" if policy == "trusted" else "allow_once"
        option_id = None
        for option in options:
            kind = getattr(option.kind, "value", option.kind)
            if kind == preferred:
                option_id = option.option_id
                break
        if option_id is None and options:
            option_id = options[0].option_id
        if option_id is None:
            return RequestPermissionResponse.model_validate({"outcome": {"outcome": "cancelled"}})
        return RequestPermissionResponse.model_validate(
            {"outcome": {"outcome": "selected", "optionId": option_id}}
        )

    async def _handle_session_update(self, session_id: str, update: Any) -> None:
        from acp.schema import (
            AgentMessageChunk,
            CurrentModeUpdate,
            TextContentBlock,
            ToolCallProgress,
            ToolCallStart,
        )

        state = self._session_states.get(session_id)
        if state is None:
            return

        if isinstance(update, AgentMessageChunk) and isinstance(update.content, TextContentBlock):
            state.merge_text(update.content.text)
            await self._emit_progress(state.on_progress, update.content.text)
            return

        if isinstance(update, ToolCallStart):
            title = update.title or "tool"
            await self._emit_progress(state.on_progress, title, tool_hint=True)
            return

        if isinstance(update, ToolCallProgress):
            status = getattr(update.status, "value", update.status) if update.status else None
            if status:
                await self._emit_progress(state.on_progress, status, tool_hint=True)

        if isinstance(update, CurrentModeUpdate):
            caps = self._session_caps.get(session_id)
            if caps is not None:
                caps.current_agent = update.current_mode_id

    async def _ensure_connection(self) -> None:
        if self._conn is not None:
            return

        async with self._connect_lock:
            if self._conn is not None:
                return

            local_sdk_src = self.workspace / "python-sdk" / "src"
            if local_sdk_src.exists():
                local_sdk_src_str = str(local_sdk_src)
                if local_sdk_src_str not in sys.path:
                    sys.path.insert(0, local_sdk_src_str)
                    logger.info("Using local python-sdk from {}", local_sdk_src_str)

            from acp import spawn_agent_process
            from acp.schema import ClientCapabilities, Implementation

            client = _NanobotACPClient(self)
            env = {**os.environ, **self.acp_config.env}
            cwd = self.acp_config.resolve_cwd(self.workspace)
            timeout = max(1, self.acp_config.startup_timeout_seconds)

            self._conn_cm = spawn_agent_process(
                client,
                self.acp_config.command,
                *self.acp_config.args,
                env=env,
                cwd=cwd,
                transport_kwargs={"limit": self.acp_config.stdio_buffer_limit_bytes},
            )
            try:
                self._conn, self._proc = await asyncio.wait_for(
                    self._conn_cm.__aenter__(), timeout=timeout
                )
                await asyncio.wait_for(
                    self._conn.initialize(
                        protocol_version=self.acp_config.protocol_version,
                        client_capabilities=ClientCapabilities(),
                        client_info=Implementation(name="nanobot", version="0.1.4.post2"),
                    ),
                    timeout=timeout,
                )
            except Exception:
                if self._conn_cm is not None:
                    await self._conn_cm.__aexit__(None, None, None)
                self._conn_cm = None
                self._conn = None
                self._proc = None
                raise

    async def _ensure_session(self, session_key: str) -> str:
        session_id = self._session_map.get(session_key)
        if session_id:
            return session_id

        lock = self._session_locks.setdefault(session_key, asyncio.Lock())
        async with lock:
            session_id = self._session_map.get(session_key)
            if session_id:
                return session_id
            await self._ensure_connection()
            if self._conn is None:
                raise RuntimeError("ACP connection is not available")
            cwd = self.acp_config.resolve_cwd(self.workspace)
            response = await self._conn.new_session(
                cwd=str(cwd),
                mcp_servers=self._convert_mcp_servers(),
            )
            self._session_map[session_key] = response.session_id
            self._update_caps_from_session_payload(response.session_id, response)
            await self._apply_session_defaults(response.session_id)
            return response.session_id

    async def _apply_session_defaults(self, session_id: str) -> None:
        if self._conn is None:
            return

        caps = self._session_caps.setdefault(session_id, _SessionCapabilities())

        default_model = self.acp_config.default_model
        if default_model:
            try:
                await self._conn.set_session_model(model_id=default_model, session_id=session_id)
                caps.current_model = default_model
            except Exception:
                logger.warning(
                    "Failed to set ACP default model '{}' for session {}",
                    default_model,
                    session_id,
                )

        default_agent = self.acp_config.default_agent
        if default_agent:
            try:
                await self._conn.set_session_mode(mode_id=default_agent, session_id=session_id)
                caps.current_agent = default_agent
            except Exception:
                logger.warning(
                    "Failed to set ACP default agent '{}' for session {}",
                    default_agent,
                    session_id,
                )

    def _convert_mcp_servers(self) -> list[Any]:
        from acp.schema import EnvVariable, HttpHeader, HttpMcpServer, McpServerStdio, SseMcpServer

        converted = []
        for name, cfg in self.mcp_servers.items():
            if cfg.command:
                converted.append(
                    McpServerStdio(
                        name=name,
                        command=cfg.command,
                        args=cfg.args,
                        env=[EnvVariable(name=k, value=v) for k, v in cfg.env.items()],
                        field_meta={"toolTimeout": cfg.tool_timeout},
                    )
                )
                continue
            if cfg.url:
                headers = [HttpHeader(name=k, value=v) for k, v in cfg.headers.items()]
                if cfg.url.startswith("http://") or cfg.url.startswith("https://"):
                    converted.append(
                        HttpMcpServer(
                            type="http",
                            name=name,
                            url=cfg.url,
                            headers=headers,
                            field_meta={"toolTimeout": cfg.tool_timeout},
                        )
                    )
                else:
                    converted.append(
                        SseMcpServer(
                            type="sse",
                            name=name,
                            url=cfg.url,
                            headers=headers,
                            field_meta={"toolTimeout": cfg.tool_timeout},
                        )
                    )
        return converted

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        del channel, chat_id
        await self._ensure_connection()
        if self._conn is None:
            raise RuntimeError("ACP connection is not available")
        session_id = await self._ensure_session(session_key)
        state = _StreamState(on_progress=on_progress)
        self._session_states[session_id] = state
        try:
            from acp import text_block

            try:
                await self._conn.prompt(prompt=[text_block(content)], session_id=session_id)
            except Exception as exc:
                logger.warning(
                    "ACP prompt failed session_key={} session_id={} partial_chars={} preview='{}'",
                    session_key,
                    session_id,
                    len(state.final()),
                    self._preview_text(state.final()),
                )
                raise _ACPDispatchError(partial_response=state.final()) from exc
            return state.final()
        finally:
            self._session_states.pop(session_id, None)

    async def _handle_stop(self, msg: InboundMessage) -> None:
        tasks = self._active_tasks.pop(msg.session_key, [])
        cancelled = sum(1 for task in tasks if not task.done() and task.cancel())
        for task in tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        content = f"⏹ Stopped {cancelled} task(s)." if cancelled else "No active task to stop."
        await self.bus.publish_outbound(
            OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=content)
        )

    async def _dispatch(self, msg: InboundMessage) -> None:
        try:
            key = msg.session_key
            if msg.channel == "system":
                origin = msg.chat_id if ":" in msg.chat_id else f"cli:{msg.chat_id}"
                key = origin

            command, arg = self._parse_command(msg.content)
            if command == "/help":
                await self.bus.publish_outbound(
                    OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=self._HELP_TEXT,
                    )
                )
                return
            if command == "/new":
                old_session_id = self._session_map.pop(key, None)
                if old_session_id:
                    self._session_caps.pop(old_session_id, None)
                await self.bus.publish_outbound(
                    OutboundMessage(
                        channel=msg.channel, chat_id=msg.chat_id, content="New session started."
                    )
                )
                return
            if command == "/models":
                session_id = await self._ensure_session(key)
                content = await self._list_models_command(session_id)
                await self.bus.publish_outbound(
                    OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=content)
                )
                return
            if command == "/agents":
                session_id = await self._ensure_session(key)
                content = await self._list_agents_command(session_id)
                await self.bus.publish_outbound(
                    OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=content)
                )
                return
            if command == "/set_model":
                if not arg:
                    await self.bus.publish_outbound(
                        OutboundMessage(
                            channel=msg.channel,
                            chat_id=msg.chat_id,
                            content="Usage: /set_model <model_id>",
                        )
                    )
                    return
                await self._ensure_connection()
                if self._conn is None:
                    raise RuntimeError("ACP connection is not available")
                session_id = await self._ensure_session(key)
                await self._conn.set_session_model(model_id=arg, session_id=session_id)
                caps = self._session_caps.setdefault(session_id, _SessionCapabilities())
                caps.current_model = arg
                await self.bus.publish_outbound(
                    OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=f"Model switched to: {arg}",
                    )
                )
                return
            if command == "/set_agent":
                if not arg:
                    await self.bus.publish_outbound(
                        OutboundMessage(
                            channel=msg.channel,
                            chat_id=msg.chat_id,
                            content="Usage: /set_agent <agent_id>",
                        )
                    )
                    return
                await self._ensure_connection()
                if self._conn is None:
                    raise RuntimeError("ACP connection is not available")
                session_id = await self._ensure_session(key)
                await self._conn.set_session_mode(mode_id=arg, session_id=session_id)
                caps = self._session_caps.setdefault(session_id, _SessionCapabilities())
                caps.current_agent = arg
                await self.bus.publish_outbound(
                    OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=f"Agent switched to: {arg}",
                    )
                )
                return

            if msg.channel not in {"cli", "system"} and msg.chat_id:
                self.last_target = (msg.channel, msg.chat_id)

            lock = self._process_locks.setdefault(key, asyncio.Lock())
            async with lock:

                async def _bus_progress(content: str, *, tool_hint: bool = False) -> None:
                    meta = dict(msg.metadata or {})
                    meta["_progress"] = True
                    meta["_tool_hint"] = tool_hint
                    logger.debug(
                        "[OB-ACP-PUB] kind={} channel={} chat={} session={} chars={} preview='{}'",
                        "tool_hint" if tool_hint else "progress",
                        msg.channel,
                        msg.chat_id,
                        key,
                        len(content),
                        self._preview_text(content),
                    )
                    await self.bus.publish_outbound(
                        OutboundMessage(
                            channel=msg.channel,
                            chat_id=msg.chat_id,
                            content=content,
                            metadata=meta,
                        )
                    )

                coalescer = _ProgressCoalescer(
                    publish=_bus_progress,
                    max_chars=self._PROGRESS_BUFFER_MAX_CHARS,
                    idle_flush_seconds=self._PROGRESS_IDLE_FLUSH_SECONDS,
                )

                # 包装回调：区分文本进度和工具提示，分别交给聚合器处理
                async def _coalesced_progress(content: str, *, tool_hint: bool = False) -> None:
                    if tool_hint:
                        await coalescer.emit_tool_hint(content)
                        return
                    await coalescer.add_text(content)

                try:
                    response = await self.process_direct(
                        msg.content,
                        session_key=key,
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        on_progress=_coalesced_progress,
                    )
                    # 会话正常结束，强制 flush 剩余缓存的文本
                    await coalescer.flush(reason="finalize")
                except _ACPDispatchError as exc:
                    # ACP 调用出错，先 flush 已缓存的内容，让用户看到部分结果
                    await coalescer.flush(reason="acp_error")
                    partial = exc.partial_response.strip()
                    if partial:
                        partial_esc = partial.encode("unicode_escape", "ignore").decode("ascii")
                        if len(partial_esc) > 320:
                            partial_esc = f"{partial_esc[:320]}..."
                        logger.warning(
                            "ACP dispatch fallback using partial response channel={} chat={} session_key={} partial_chars={} partial_esc='{}'",
                            msg.channel,
                            msg.chat_id,
                            key,
                            len(partial),
                            partial_esc,
                        )
                        await self.bus.publish_outbound(
                            OutboundMessage(
                                channel=msg.channel,
                                chat_id=msg.chat_id,
                                content=partial,
                                metadata=msg.metadata or {},
                            )
                        )
                        return
                    raise
            logger.debug(
                "[OB-ACP-PUB] kind=final channel={} chat={} session={} chars={} preview='{}'",
                msg.channel,
                msg.chat_id,
                key,
                len(response),
                self._preview_text(response),
            )
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=response,
                    metadata=msg.metadata or {},
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("ACP dispatcher failed for {}", msg.session_key)
            await self.bus.publish_outbound(
                OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="Sorry, I encountered an error.",
                )
            )

    async def run(self) -> None:
        self._running = True
        await self._ensure_connection()
        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            if msg.content.strip().lower() == "/stop":
                await self._handle_stop(msg)
                continue

            task = asyncio.create_task(self._dispatch(msg))
            self._active_tasks.setdefault(msg.session_key, []).append(task)
            task.add_done_callback(
                lambda done, key=msg.session_key: self._active_tasks.get(key, [])
                and self._active_tasks[key].remove(done)
                if done in self._active_tasks.get(key, [])
                else None
            )

    def stop(self) -> None:
        self._running = False

    async def close(self) -> None:
        self.stop()
        if self._conn_cm is not None:
            await self._conn_cm.__aexit__(None, None, None)
        self._conn_cm = None
        self._conn = None
        self._proc = None


class _NanobotACPClient:
    def __init__(self, dispatcher: ACPDispatcher):
        self.dispatcher = dispatcher

    async def request_permission(self, options, session_id, tool_call, **kwargs):
        del session_id, tool_call, kwargs
        return await self.dispatcher._permission_response(options)

    async def session_update(self, session_id, update, **kwargs) -> None:
        del kwargs
        await self.dispatcher._handle_session_update(session_id, update)

    async def write_text_file(self, content, path, session_id, **kwargs):
        del content, path, session_id, kwargs
        return None

    async def read_text_file(self, path, session_id, limit=None, line=None, **kwargs):
        del path, session_id, limit, line, kwargs
        raise NotImplementedError

    async def create_terminal(
        self,
        command,
        session_id,
        args=None,
        cwd=None,
        env=None,
        output_byte_limit=None,
        **kwargs,
    ):
        del command, session_id, args, cwd, env, output_byte_limit, kwargs
        raise NotImplementedError

    async def terminal_output(self, session_id, terminal_id, **kwargs):
        del session_id, terminal_id, kwargs
        raise NotImplementedError

    async def release_terminal(self, session_id, terminal_id, **kwargs):
        del session_id, terminal_id, kwargs
        return None

    async def wait_for_terminal_exit(self, session_id, terminal_id, **kwargs):
        del session_id, terminal_id, kwargs
        raise NotImplementedError

    async def kill_terminal(self, session_id, terminal_id, **kwargs):
        del session_id, terminal_id, kwargs
        return None

    async def ext_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        del method, params
        return {}

    async def ext_notification(self, method: str, params: dict[str, Any]) -> None:
        del method, params

    def on_connect(self, conn) -> None:
        del conn
