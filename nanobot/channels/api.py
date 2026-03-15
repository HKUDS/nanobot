"""Unix-socket JSON-RPC API channel for external clients."""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel

_JSONRPC_VERSION = "2.0"
_RPC_PARSE_ERROR = -32700
_RPC_INVALID_REQUEST = -32600
_RPC_METHOD_NOT_FOUND = -32601
_RPC_INVALID_PARAMS = -32602
_RPC_INTERNAL_ERROR = -32603
_RPC_APPLICATION_ERROR = -32000


class _RpcError(Exception):
    """JSON-RPC application error."""

    def __init__(self, code: int, message: str, data: Any | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def _default_socket_path() -> str:
    return str(Path.home() / ".nanobot" / "api.sock")


def _encode(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode()


def _jsonrpc_notification(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "jsonrpc": _JSONRPC_VERSION,
        "method": method,
    }
    if params is not None:
        payload["params"] = params
    return payload


def _jsonrpc_success(request_id: Any, result: Any) -> dict[str, Any]:
    return {
        "jsonrpc": _JSONRPC_VERSION,
        "id": request_id,
        "result": result,
    }


def _jsonrpc_error(
    request_id: Any,
    code: int,
    message: str,
    data: Any | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
    }
    if data is not None:
        error["data"] = data
    return {
        "jsonrpc": _JSONRPC_VERSION,
        "id": request_id,
        "error": error,
    }


class _ClientConnection:
    """Represents one connected API client."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        channel: "ApiChannel",
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._channel = channel
        self._send_lock = asyncio.Lock()
        self.chat_id = "api"

    async def send(self, payload: dict[str, Any]) -> None:
        async with self._send_lock:
            try:
                self._writer.write(_encode(payload))
                await self._writer.drain()
            except (ConnectionResetError, BrokenPipeError, OSError):
                pass

    async def send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        await self.send(_jsonrpc_notification(method, params))

    async def send_result(self, request_id: Any, result: Any) -> None:
        await self.send(_jsonrpc_success(request_id, result))

    async def send_error(
        self,
        request_id: Any,
        code: int,
        message: str,
        data: Any | None = None,
    ) -> None:
        await self.send(_jsonrpc_error(request_id, code, message, data))

    async def run(self) -> None:
        peer = self._writer.get_extra_info("peername") or "unix"
        logger.info("API channel: client connected ({})", peer)
        try:
            while True:
                try:
                    line = await self._reader.readline()
                except (ConnectionResetError, OSError):
                    break
                if not line:
                    break
                await self._handle_line(line)
        finally:
            self._channel._remove_client(self)
            with contextlib.suppress(Exception):
                self._writer.close()
                await self._writer.wait_closed()
            logger.info("API channel: client disconnected ({})", peer)

    async def _handle_line(self, line: bytes) -> None:
        raw = line.decode(errors="replace").strip()
        if not raw:
            return

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            await self.send_error(None, _RPC_PARSE_ERROR, f"JSON parse error: {exc}")
            return

        if not isinstance(payload, dict):
            await self.send_error(None, _RPC_INVALID_REQUEST, "request must be a JSON object")
            return

        request_id = payload.get("id")
        has_response = "id" in payload
        if payload.get("jsonrpc") != _JSONRPC_VERSION:
            if has_response:
                await self.send_error(request_id, _RPC_INVALID_REQUEST, "jsonrpc must be '2.0'")
            return

        method = payload.get("method")
        if not isinstance(method, str) or not method.strip():
            if has_response:
                await self.send_error(request_id, _RPC_INVALID_REQUEST, "method must be a string")
            return

        params = payload.get("params", {})
        if params is None:
            params = {}
        if not isinstance(params, dict):
            if has_response:
                await self.send_error(request_id, _RPC_INVALID_PARAMS, "params must be an object")
            return

        try:
            result = await self._dispatch_method(method.strip(), params)
        except _RpcError as exc:
            if has_response:
                await self.send_error(request_id, exc.code, exc.message, exc.data)
            return
        except Exception:
            logger.exception("API channel request failed: {}", method)
            if has_response:
                await self.send_error(request_id, _RPC_INTERNAL_ERROR, "internal error")
            return

        if has_response:
            await self.send_result(request_id, result if result is not None else {"status": "ok"})

    async def _dispatch_method(self, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        if method == "ping":
            return {"pong": True}

        if method == "message.send":
            content = str(params.get("content", "")).strip()
            if not content:
                raise _RpcError(_RPC_INVALID_PARAMS, "content is required")
            chat_id = str(params.get("chat_id", self.chat_id)).strip() or "api"
            sender_id = str(params.get("sender_id", "user")).strip() or "user"
            media = params.get("media", [])
            metadata = params.get("metadata", {})
            self.chat_id = chat_id
            await self._channel.publish_message(
                chat_id=chat_id,
                sender_id=sender_id,
                content=content,
                media=media,
                metadata=metadata,
            )
            return {"status": "accepted"}

        if method == "command.execute":
            command = str(params.get("command", "")).strip().lower()
            chat_id = str(params.get("chat_id", self.chat_id)).strip() or "api"
            sender_id = str(params.get("sender_id", "user")).strip() or "user"
            self.chat_id = chat_id
            if command != "reset":
                raise _RpcError(_RPC_INVALID_PARAMS, f"unknown command: {command!r}")
            await self._channel.publish_command(
                chat_id=chat_id,
                sender_id=sender_id,
                command=command,
            )
            return {"status": "accepted"}

        if method == "tool.list":
            lister = self._channel._tool_lister
            if lister is None:
                return {"tools": []}
            return {"tools": await lister()}

        if method == "tool.call":
            caller = self._channel._tool_caller
            if caller is None:
                raise _RpcError(_RPC_APPLICATION_ERROR, "tool runtime is unavailable")

            tool_name = str(params.get("name", "")).strip()
            if not tool_name:
                raise _RpcError(_RPC_INVALID_PARAMS, "name is required")

            arguments = params.get("arguments", {})
            if arguments is None:
                arguments = {}
            if not isinstance(arguments, dict):
                raise _RpcError(_RPC_INVALID_PARAMS, "arguments must be an object")

            try:
                return await caller(tool_name, arguments)
            except LookupError as exc:
                raise _RpcError(_RPC_INVALID_PARAMS, str(exc)) from exc
            except ValueError as exc:
                raise _RpcError(_RPC_INVALID_PARAMS, str(exc)) from exc
            except RuntimeError as exc:
                raise _RpcError(_RPC_APPLICATION_ERROR, str(exc)) from exc

        raise _RpcError(_RPC_METHOD_NOT_FOUND, f"unknown method: {method!r}")


class ApiChannel(BaseChannel):
    """Unix-socket JSON-RPC channel for local external clients."""

    name = "api"

    def __init__(self, config: Any, bus: MessageBus) -> None:
        super().__init__(config, bus)
        raw_path = getattr(config, "socket_path", None) or _default_socket_path()
        self._socket_path = str(Path(raw_path).expanduser())
        self._clients: dict[int, _ClientConnection] = {}
        self._server: asyncio.AbstractServer | None = None
        self._tool_lister: Callable[[], Awaitable[list[dict[str, Any]]]] | None = None
        self._tool_caller: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]] | None = None

    def set_tool_runtime(
        self,
        *,
        list_tools: Callable[[], Awaitable[list[dict[str, Any]]]],
        call_tool: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
    ) -> None:
        self._tool_lister = list_tools
        self._tool_caller = call_tool

    async def start(self) -> None:
        path = Path(self._socket_path)
        path.unlink(missing_ok=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._server = await asyncio.start_unix_server(self._on_client_connected, path=str(path))
        self._running = True
        logger.info("API channel listening on {}", path)
        async with self._server:
            await self._server.serve_forever()

    async def stop(self) -> None:
        self._running = False
        if self._server:
            self._server.close()
            with contextlib.suppress(Exception):
                await self._server.wait_closed()
            self._server = None

        for conn in list(self._clients.values()):
            with contextlib.suppress(Exception):
                conn._writer.close()
                await conn._writer.wait_closed()
        self._clients.clear()

        with contextlib.suppress(FileNotFoundError):
            Path(self._socket_path).unlink()

    async def send(self, msg: OutboundMessage) -> None:
        payload = {
            "content": msg.content,
            "chat_id": msg.chat_id,
            "is_progress": bool(msg.metadata.get("_progress")),
            "is_tool_hint": bool(msg.metadata.get("_tool_hint")),
        }
        targets = self._target_clients(msg.chat_id)
        await asyncio.gather(
            *(conn.send_notification("message", payload) for conn in targets),
            return_exceptions=True,
        )

    async def publish_message(
        self,
        *,
        chat_id: str,
        sender_id: str,
        content: str,
        media: Any = None,
        metadata: Any = None,
    ) -> None:
        if not self.is_allowed(sender_id):
            raise _RpcError(_RPC_APPLICATION_ERROR, f"sender not allowed: {sender_id}")
        inbound = InboundMessage(
            channel=self.name,
            sender_id=sender_id,
            chat_id=chat_id,
            content=content,
            media=list(media) if isinstance(media, list) else [],
            metadata=dict(metadata) if isinstance(metadata, dict) else {},
        )
        await self.bus.publish_inbound(inbound)

    async def publish_command(self, *, chat_id: str, sender_id: str, command: str) -> None:
        if not self.is_allowed(sender_id):
            raise _RpcError(_RPC_APPLICATION_ERROR, f"sender not allowed: {sender_id}")
        if command != "reset":
            raise _RpcError(_RPC_INVALID_PARAMS, f"unknown command: {command!r}")
        inbound = InboundMessage(
            channel=self.name,
            sender_id=sender_id,
            chat_id=chat_id,
            content="/new",
        )
        await self.bus.publish_inbound(inbound)

    async def _on_client_connected(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        conn = _ClientConnection(reader, writer, self)
        self._clients[id(conn)] = conn
        await conn.run()

    def _remove_client(self, conn: _ClientConnection) -> None:
        self._clients.pop(id(conn), None)

    def _target_clients(self, chat_id: str) -> list[_ClientConnection]:
        matching = [conn for conn in self._clients.values() if conn.chat_id == chat_id]
        return matching if matching else list(self._clients.values())
