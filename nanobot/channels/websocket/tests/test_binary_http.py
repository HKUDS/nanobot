"""Real socket regressions for body-capable HTTP beside bounded WebSockets."""

import asyncio
import logging

import aiohttp
import pytest
import websockets
from aiohttp import web
from packaging.version import Version
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from nanobot.channels.websocket.attachment_store import AttachmentStore
from nanobot.channels.websocket.binary_http import BinaryHTTPBridge


@pytest.mark.asyncio
async def test_binary_body_exceeds_ws_frame_limit_without_changing_ws(tmp_path):
    store = AttachmentStore(tmp_path)

    async def upload(request):
        if request.headers.get("Authorization") != "Bearer isolated-test":
            return web.json_response({"error": "Unauthorized"}, status=401)
        if request.method != "POST" or request.path != "/api/attachments":
            return web.Response(status=404)
        if request.content_length is None or request.headers.get("Content-Encoding"):
            return web.Response(status=400)
        ref = await store.upload(
            request.content.iter_chunked(65536), owner="authenticated-owner",
            mime=request.content_type, size=request.content_length,
        )
        return web.json_response({"ref": ref})

    async def echo(connection):
        async for message in connection:
            await connection.send(message)

    bridge = BinaryHTTPBridge(upload)
    server = await serve(echo, "127.0.0.1", 0, max_size=1024 * 1024,
                         create_connection=bridge.connection_factory)
    port = server.sockets[0].getsockname()[1]
    body = b"x" * 1_453_245
    try:
        async with aiohttp.ClientSession() as client:
            async with client.post(f"http://127.0.0.1:{port}/api/attachments", data=body,
                                   headers={"Content-Type": "image/png"}) as response:
                assert response.status == 401
            assert not list(tmp_path.iterdir())
            async with client.post(f"http://127.0.0.1:{port}/api/attachments", data=body,
                                   headers={"Content-Type": "image/png",
                                            "Authorization": "Bearer isolated-test"}) as response:
                assert response.status == 200
                ref = (await response.json())["ref"]
        paths = store.resolve([ref], owner="authenticated-owner")
        assert len(paths) == 1
        assert (tmp_path / paths[0]).read_bytes() == body
        async with connect(f"ws://127.0.0.1:{port}/") as ws:
            await ws.send(ref)
            assert await ws.recv() == ref
            await ws.send(body)
            await ws.wait_closed()
            assert ws.close_code == 1009
    finally:
        server.close()
        await bridge.shutdown()
        await server.wait_closed()
        store.clear()


@pytest.mark.asyncio
async def test_fragmented_method_and_shutdown_of_undecided_connection():
    async def upload(request):
        return web.Response(body=await request.read())

    async def echo(connection):
        async for message in connection:
            await connection.send(message)

    bridge = BinaryHTTPBridge(upload)
    server = await serve(echo, "127.0.0.1", 0, create_connection=bridge.connection_factory)
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        for fragment in (b"P", b"O", b"S", b"T / HTTP/1.1\r\nHost: localhost\r\n",
                         b"Content-Length: 4\r\nConnection: close\r\n\r\ntest"):
            writer.write(fragment)
            await writer.drain()
            await asyncio.sleep(0)
        response = await asyncio.wait_for(reader.read(), 2)
        assert b"200 OK" in response
        assert response.endswith(b"test")
        idle_reader, idle_writer = await asyncio.open_connection("127.0.0.1", port)
        idle_writer.write(b"P")
        await idle_writer.drain()
        async with asyncio.timeout(2):
            while not any(connection._prefix == b"P" for connection in bridge.pending_connections):
                await asyncio.sleep(0)
        server.close()
        await bridge.shutdown()
        await server.wait_closed()
        assert await asyncio.wait_for(idle_reader.read(), 2) == b""
        idle_writer.close()
        await idle_writer.wait_closed()
    finally:
        writer.close()
        await writer.wait_closed()
        server.close()
        await bridge.shutdown()
        await server.wait_closed()


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [
    b"Content-Length: 4\r\nTransfer-Encoding: chunked\r\n",
    b"Content-Length: 4\r\nContent-Length: 5\r\n",
    b"Content-Length: -1\r\n",
])
async def test_ambiguous_http_framing_is_rejected_before_handler(headers):
    calls = []

    async def upload(request):
        calls.append(request)
        return web.Response(status=200)

    async def echo(connection):
        await connection.wait_closed()

    bridge = BinaryHTTPBridge(upload)
    server = await serve(echo, "127.0.0.1", 0, create_connection=bridge.connection_factory)
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(b"POST / HTTP/1.1\r\nHost: localhost\r\n" + headers
                     + b"Connection: close\r\n\r\ntest")
        await writer.drain()
        response = await asyncio.wait_for(reader.read(), 2)
        assert b"400 Bad Request" in response
        assert calls == []
    finally:
        writer.close()
        await writer.wait_closed()
        server.close()
        await bridge.shutdown()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_request_body_is_not_automatically_decompressed():
    import gzip

    body = gzip.compress(b"x" * 2_000_000)
    received = []

    async def upload(request):
        received.append(await request.read())
        return web.Response(status=204)

    async def echo(connection):
        await connection.wait_closed()

    bridge = BinaryHTTPBridge(upload)
    server = await serve(echo, "127.0.0.1", 0, create_connection=bridge.connection_factory)
    port = server.sockets[0].getsockname()[1]
    try:
        async with aiohttp.ClientSession() as client:
            async with client.post(f"http://127.0.0.1:{port}/", data=body,
                                   headers={"Content-Encoding": "gzip"}) as response:
                assert response.status == 204
        assert received == [body]
    finally:
        server.close()
        await bridge.shutdown()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_incomplete_http_headers_have_a_deadline(monkeypatch):
    monkeypatch.setattr("nanobot.channels.websocket.binary_http._HTTP_HEADER_TIMEOUT_S", .05)

    async def upload(request):
        pytest.fail("Incomplete headers must not invoke the upload handler")

    async def echo(connection):
        await connection.wait_closed()

    bridge = BinaryHTTPBridge(upload)
    server = await serve(echo, "127.0.0.1", 0, create_connection=bridge.connection_factory)
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(b"POST /api/attachments HTTP/1.1\r\nHost: localhost\r\n")
        await writer.drain()
        assert await asyncio.wait_for(reader.read(), 2) == b""
    finally:
        writer.close()
        await writer.wait_closed()
        server.close()
        await bridge.shutdown()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_parsed_request_outlasts_header_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.channels.websocket.binary_http._HTTP_HEADER_TIMEOUT_S", .1)
    monkeypatch.setattr("nanobot.channels.websocket.binary_http._HTTP_CONNECTION_TIMEOUT_S", 1)
    store = AttachmentStore(tmp_path, upload_timeout=1, upload_idle_timeout=.1)
    started = asyncio.Event()

    async def upload(request):
        started.set()
        ref = await store.upload(
            request.content.iter_chunked(65536), owner="owner", mime="image/png", size=3,
        )
        response = web.json_response({"ref": ref})
        response.force_close()
        return response

    async def echo(connection):
        await connection.wait_closed()

    bridge = BinaryHTTPBridge(upload)
    server = await serve(echo, "127.0.0.1", 0, create_connection=bridge.connection_factory)
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(b"POST /api/attachments HTTP/1.1\r\nHost: localhost\r\nContent-Length: 3\r\n\r\n")
        await writer.drain()
        await asyncio.wait_for(started.wait(), 1)
        for _ in range(3):
            await asyncio.sleep(.05)
            writer.write(b"x")
            await writer.drain()
        response = await asyncio.wait_for(reader.read(), 1)
        assert b"200 OK" in response
        assert [p.read_bytes() for p in tmp_path.glob("*.png")] == [b"xxx"]
    finally:
        writer.close()
        await writer.wait_closed()
        server.close()
        await bridge.shutdown()
        await server.wait_closed()
        store.clear()


@pytest.mark.asyncio
@pytest.mark.skipif(
    Version(websockets.__version__) < Version("17.0"),
    reason="Upstream EOF race is fixed in 17.0; Feishu still requires websockets<16",
)
@pytest.mark.parametrize("use_bridge", [False, True], ids=["native", "bridge"])
@pytest.mark.parametrize("half_close", [False, True], ids=["close", "half-close"])
async def test_disconnect_during_http_response_does_not_send_eof_twice(
    caplog, use_bridge, half_close,
):
    arrived = asyncio.get_running_loop().create_future()
    release = asyncio.Event()

    async def process_request(connection, request):
        if request.path == "/delayed":
            arrived.set_result(connection)
            await release.wait()
        if request.path in {"/delayed", "/health"}:
            return connection.respond(200, "healthy\n")
        return None

    async def upload(request):
        return web.Response(status=404)

    async def echo(connection):
        async for message in connection:
            await connection.send(message)

    # Capture directly even after channel startup redirects websockets logging.
    logger = logging.Logger("websockets.eof-regression", level=logging.ERROR)
    logger.addHandler(caplog.handler)
    bridge = BinaryHTTPBridge(upload) if use_bridge else None
    options = {"create_connection": bridge.connection_factory} if bridge else {}
    server = await serve(
        echo, "127.0.0.1", 0, process_request=process_request, logger=logger, **options,
    )
    port = server.sockets[0].getsockname()[1]
    _reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(b"GET /delayed HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
        await writer.drain()
        connection = await asyncio.wait_for(arrived, 2)
        if half_close:
            if not writer.can_write_eof():
                pytest.skip("Transport doesn't support TCP half-close")
            writer.write_eof()
            await writer.drain()
        else:
            writer.close()
            await writer.wait_closed()
        await asyncio.wait_for(connection.wait_closed(), 2)
        release.set()

        async with aiohttp.ClientSession() as client:
            async with client.get(f"http://127.0.0.1:{port}/health") as response:
                assert response.status == 200
                assert await response.text() == "healthy\n"
        async with connect(f"ws://127.0.0.1:{port}/", proxy=None) as ws:
            await ws.send("still-alive")
            assert await ws.recv() == "still-alive"
    finally:
        release.set()
        writer.close()
        await writer.wait_closed()
        server.close()
        await asyncio.wait_for(server.wait_closed(), 3)
        if bridge:
            await bridge.shutdown()

    assert not [
        record for record in caplog.records
        if record.name.startswith("websockets") and record.levelno >= logging.ERROR
    ], caplog.text
