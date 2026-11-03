import asyncio
import json
import logging
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from websockets.asyncio.client import connect, unix_connect

from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket import runtime
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.webui.gateway_services import build_gateway_services
from nanobot.webui.websocket_logging import WebSocketHandshakeNoiseFilter


@pytest.fixture
def listener_path(tmp_path):
    if sys.platform != "darwin":
        yield tmp_path
        return
    # macOS limits sockaddr_un to 104 bytes; pytest's descriptive temporary
    # paths can exceed it. Keep the real socket in its own private short root.
    with tempfile.TemporaryDirectory(prefix="nb-ws-", dir="/tmp") as root:
        yield Path(root)


@asynccontextmanager
async def _listener(tmp_path, monkeypatch, caplog, unix, process_request):
    if unix and sys.platform == "win32":
        pytest.skip("asyncio Unix sockets are unavailable on Windows")
    config = WebSocketConfig(
        enabled=True, allow_from=["*"], host="127.0.0.1", port=0, path="/ws",
        websocket_requires_token=False,
        unix_socket_path=str(tmp_path / "ws.sock") if unix else "",
    )
    bus = MessageBus()
    gateway = build_gateway_services(
        config=config, bus=bus, session_manager=None, static_dist_path=None,
        workspace_path=tmp_path, default_restrict_to_workspace=False,
        runtime_model_name=None, runtime_surface="browser",
        runtime_capabilities_overrides=None,
    )
    channel = WebSocketChannel(config.model_dump(), bus, gateway=gateway)
    dispatch_http = channel._dispatch_http

    async def dispatch(connection, request):
        if request.path in {"/delayed", "/probe"}:
            return await process_request(connection, request)
        return await dispatch_http(connection, request)

    monkeypatch.setattr(channel, "_dispatch_http", dispatch)
    logger = logging.Logger("websockets.eof-regression", level=logging.ERROR)
    logger.addHandler(caplog.handler)
    logger.addFilter(WebSocketHandshakeNoiseFilter())
    monkeypatch.setattr(runtime, "websockets_server_logger", lambda: logger)
    task = asyncio.create_task(channel.start())
    try:
        async with asyncio.timeout(5):
            while channel._server is None or not channel._server.is_serving():
                if task.done():
                    await task
                    raise AssertionError("listener stopped before becoming ready")
                await asyncio.sleep(0)
        address = config.unix_socket_path if unix else (
            "127.0.0.1", channel._server.sockets[0].getsockname()[1],
        )
        yield channel, address
    finally:
        await channel.stop()
        await asyncio.wait_for(task, 5)


@asynccontextmanager
async def _stream(address):
    reader, writer = await (
        asyncio.open_unix_connection(address) if isinstance(address, str)
        else asyncio.open_connection(*address)
    )
    try:
        yield reader, writer
    finally:
        writer.close()
        await writer.wait_closed()


async def _request(writer, path):
    writer.write(f"GET {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n".encode())
    await writer.drain()


@pytest.mark.parametrize("unix", [False, True], ids=["tcp", "unix"])
@pytest.mark.parametrize("half_close", [False, True], ids=["close", "half-close"])
async def test_disconnect_during_http_response_keeps_listener_usable(
    listener_path, monkeypatch, caplog, unix, half_close,
):
    arrived = asyncio.get_running_loop().create_future()
    release = asyncio.Event()
    completed = asyncio.Event()

    async def process_request(connection, request):
        if request.path == "/delayed":
            arrived.set_result(connection)
            await release.wait()
            completed.set()
        return connection.respond(200, "healthy\n")

    async with _listener(listener_path, monkeypatch, caplog, unix, process_request) as (channel, address):
        try:
            async with _stream(address) as (_reader, writer):
                await _request(writer, "/delayed")
                connection = await asyncio.wait_for(arrived, 2)
                if half_close:
                    writer.write_eof()
                    await writer.drain()
                else:
                    writer.close()
                    await writer.wait_closed()
                await asyncio.wait_for(connection.wait_closed(), 2)
                release.set()

            async with _stream(address) as (reader, writer):
                await _request(writer, "/probe")
                response = await asyncio.wait_for(reader.read(), 2)
                assert response.startswith(b"HTTP/1.1 200 OK\r\n")
                assert response.endswith(b"healthy\n")
            uri = "ws://localhost/ws?client_id=still-alive"
            client = unix_connect(address, uri=uri) if unix else connect(
                f"ws://{address[0]}:{address[1]}/ws?client_id=still-alive", proxy=None,
            )
            async with client as ws:
                ready = json.loads(await asyncio.wait_for(ws.recv(), 2))
                assert ready["event"] == "ready"
                await ws.send("still-alive")
                inbound = await asyncio.wait_for(channel.bus.consume_inbound(), 2)
                assert inbound.content == "still-alive"
            assert completed.is_set()
        finally:
            release.set()

    assert not [r for r in caplog.records if r.name == "websockets.eof-regression"], caplog.text


@pytest.mark.parametrize("unix", [False, True], ids=["tcp", "unix"])
@pytest.mark.parametrize("peer_left", [False, True], ids=["connected", "disconnected"])
async def test_http_callback_failure_remains_visible(
    listener_path, monkeypatch, caplog, unix, peer_left,
):
    arrived = asyncio.get_running_loop().create_future()
    release = asyncio.Event()
    failure = RuntimeError("HTTP callback failed after awaiting")

    async def process_request(connection, request):
        arrived.set_result(connection)
        await release.wait()
        raise failure

    async with _listener(listener_path, monkeypatch, caplog, unix, process_request) as (_channel, address):
        try:
            async with _stream(address) as (reader, writer):
                await _request(writer, "/delayed")
                connection = await asyncio.wait_for(arrived, 2)
                if peer_left:
                    writer.close()
                    await writer.wait_closed()
                    await asyncio.wait_for(connection.wait_closed(), 2)
                release.set()
                if not peer_left:
                    response = await asyncio.wait_for(reader.read(), 2)
                    assert response.startswith(b"HTTP/1.1 500 Internal Server Error\r\n")
        finally:
            release.set()

    records = [r for r in caplog.records if r.name == "websockets.eof-regression"]
    assert any(r.exc_info and r.exc_info[1] is failure for r in records), caplog.text
    assert not any(r.getMessage() == "unexpected internal error" for r in records), caplog.text
