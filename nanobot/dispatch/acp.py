from __future__ import annotations

import asyncio
import os
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


class ACPDispatcher:
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
        self._active_tasks: dict[str, list[asyncio.Task[Any]]] = {}
        self.last_target: tuple[str, str] | None = None

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
        from acp.schema import AgentMessageChunk, TextContentBlock, ToolCallProgress, ToolCallStart

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

    async def _ensure_connection(self) -> None:
        if self._conn is not None:
            return

        async with self._connect_lock:
            if self._conn is not None:
                return

            from acp import spawn_agent_process
            from acp.schema import ClientCapabilities, Implementation

            client = _NanobotACPClient(self)
            env = {**os.environ, **self.acp_config.env}
            cwd = Path(self.acp_config.cwd).expanduser() if self.acp_config.cwd else self.workspace
            timeout = max(1, self.acp_config.startup_timeout_seconds)

            self._conn_cm = spawn_agent_process(
                client,
                self.acp_config.command,
                *self.acp_config.args,
                env=env,
                cwd=cwd,
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
            cwd = Path(self.acp_config.cwd).expanduser() if self.acp_config.cwd else self.workspace
            response = await self._conn.new_session(
                cwd=str(cwd),
                mcp_servers=self._convert_mcp_servers(),
            )
            self._session_map[session_key] = response.session_id
            return response.session_id

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

            content_esc = content.encode("unicode_escape", "ignore").decode("ascii")
            if len(content_esc) > 320:
                content_esc = f"{content_esc[:320]}..."
            logger.debug(
                "ACP prompt input session_key={} session_id={} chars={} content_esc='{}'",
                session_key,
                session_id,
                len(content),
                content_esc,
            )

            try:
                await self._conn.prompt(prompt=[text_block(content)], session_id=session_id)
            except Exception as exc:
                partial_esc = state.final().encode("unicode_escape", "ignore").decode("ascii")
                if len(partial_esc) > 320:
                    partial_esc = f"{partial_esc[:320]}..."
                logger.warning(
                    "ACP prompt failed session_key={} session_id={} partial_chars={} partial_esc='{}'",
                    session_key,
                    session_id,
                    len(state.final()),
                    partial_esc,
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

            command = msg.content.strip().lower()
            if command == "/help":
                await self.bus.publish_outbound(
                    OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content="🐈 nanobot commands:\n/new — Start a new conversation\n/stop — Stop the current task\n/help — Show available commands",
                    )
                )
                return
            if command == "/new":
                self._session_map.pop(key, None)
                await self.bus.publish_outbound(
                    OutboundMessage(
                        channel=msg.channel, chat_id=msg.chat_id, content="New session started."
                    )
                )
                return

            if msg.channel not in {"cli", "system"} and msg.chat_id:
                self.last_target = (msg.channel, msg.chat_id)

            content_esc = msg.content.encode("unicode_escape", "ignore").decode("ascii")
            if len(content_esc) > 320:
                content_esc = f"{content_esc[:320]}..."
            logger.debug(
                "ACP dispatch inbound channel={} sender={} chat={} session_key={} chars={} metadata_keys={} content_esc='{}'",
                msg.channel,
                msg.sender_id,
                msg.chat_id,
                key,
                len(msg.content),
                sorted((msg.metadata or {}).keys()),
                content_esc,
            )

            lock = self._process_locks.setdefault(key, asyncio.Lock())
            async with lock:
                try:
                    response = await self.process_direct(
                        msg.content,
                        session_key=key,
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                    )
                except _ACPDispatchError as exc:
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
