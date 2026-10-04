"""Real loopback sockets and subprocess pipes; no external host or credentials."""

import asyncio
import contextlib
import socket
import sys
from unittest.mock import MagicMock

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from nanobot.webui import remote_ssh
from nanobot.webui.remote_ssh import RemoteError, RemoteProfile, open_tunnel

PROFILE = RemoteProfile(name="Fixture", host="fixture.test")
ECHO = "import os\nwhile data := os.read(0, 65536):\n os.write(1, data)\n"


def assert_owned(port):
    with socket.socket() as competitor:
        competitor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        with pytest.raises(OSError):
            competitor.bind(("127.0.0.1", port))
            competitor.listen()


@pytest.fixture
def ssh_child(monkeypatch):
    real_spawn = asyncio.create_subprocess_exec
    children = []
    state = {"script": ECHO, "port": 0, "gate": None, "started": asyncio.Event()}
    monkeypatch.setattr(remote_ssh.shutil, "which", lambda _: "fixture-ssh")

    async def spawn(*args, **kwargs):
        assert args[-3:] == ("-W", "127.0.0.1:8765", "fixture.test")
        assert "-L" not in args
        assert_owned(state["port"])
        child = await real_spawn(sys.executable, "-u", "-c", state["script"], **kwargs)
        children.append(child)
        state["started"].set()
        if state["gate"] is not None:
            await state["gate"].wait()
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    return state, children


async def test_large_binary_stream_and_half_close(ssh_child):
    state, children = ssh_child
    tunnel = await open_tunnel(PROFILE, 8765)
    state["port"] = tunnel.port
    reader, writer = await asyncio.open_connection("127.0.0.1", tunnel.port)
    payload = bytes(range(256)) * 4096

    async def upload():
        writer.write(payload)
        await writer.drain()
        writer.write_eof()

    try:
        _, response = await asyncio.wait_for(asyncio.gather(upload(), reader.read()), 10)
        assert response == payload
        assert_owned(tunnel.port)
    finally:
        writer.close()
        await writer.wait_closed()
        await tunnel.close()
    assert children and all(child.returncode is not None for child in children)


async def test_http_keepalive_and_chunked_upload(ssh_child):
    import httpx

    state, _ = ssh_child
    state["script"] = """
import sys
stream = sys.stdin.buffer
while stream.readline():
    headers = {}
    while (line := stream.readline()) not in (b'\\r\\n', b''):
        key, value = line.decode().split(':', 1)
        headers[key.lower()] = value.strip()
    if headers.get('transfer-encoding') == 'chunked':
        body = b''
        while size := int(stream.readline(), 16):
            body += stream.read(size)
            stream.read(2)
        stream.read(2)
    else:
        body = stream.read(int(headers.get('content-length', '0')))
    sys.stdout.buffer.write(b'HTTP/1.1 200 OK\\r\\nContent-Length: ' + str(len(body)).encode() + b'\\r\\n\\r\\n' + body)
    sys.stdout.buffer.flush()
"""
    tunnel = await open_tunnel(PROFILE, 8765)
    state["port"] = tunnel.port

    async def chunks():
        for _ in range(4):
            yield b"chunk" * 10000

    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            base = f"http://127.0.0.1:{tunnel.port}"
            response = await client.post(base, content=chunks())
            assert response.content == b"chunk" * 40000
            response = await client.post(base, content=b"keepalive")
            assert response.content == b"keepalive"
    finally:
        await tunnel.close()


async def test_websocket_upgrade_and_bidirectional_messages(ssh_child):
    state, _ = ssh_child

    async def echo(websocket):
        async for message in websocket:
            await websocket.send(message)

    async with serve(echo, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        state["script"] = f"""
import os, socket, threading
upstream = socket.create_connection(('127.0.0.1', {port}))
def upload():
    while data := os.read(0, 65536):
        upstream.sendall(data)
    upstream.shutdown(socket.SHUT_WR)
threading.Thread(target=upload, daemon=True).start()
while data := upstream.recv(65536):
    os.write(1, data)
"""
        tunnel = await open_tunnel(PROFILE, 8765)
        state["port"] = tunnel.port
        try:
            async with connect(f"ws://127.0.0.1:{tunnel.port}", proxy=None) as websocket:
                for message in ["hello", bytes(range(256)) * 1000, "still connected"]:
                    await websocket.send(message)
                    assert await asyncio.wait_for(websocket.recv(), 5) == message
        finally:
            await tunnel.close()


async def test_pause_keeps_origin_reserved_and_resume_reuses_it(ssh_child, tmp_path):
    state, children = ssh_child
    tunnel = await open_tunnel(PROFILE, 8765)
    state["port"] = tunnel.port
    reader, writer = await asyncio.open_connection("127.0.0.1", tunnel.port)
    try:
        writer.write(b"first")
        await writer.drain()
        assert await asyncio.wait_for(reader.readexactly(5), 5) == b"first"
        await tunnel.pause()
        assert not tunnel.active
        assert_owned(tunnel.port)
        assert all(child.returncode is not None for child in children)
        assert await reader.read() == b""
        blocked_reader, blocked_writer = await asyncio.open_connection("127.0.0.1", tunnel.port)
        try:
            assert await asyncio.wait_for(blocked_reader.read(), 2) == b""
            assert len(children) == 1
        finally:
            blocked_writer.close()
            await blocked_writer.wait_closed()
        tunnel.resume(PROFILE, 8765, tmp_path / "missing-known-hosts")
        resumed_reader, resumed_writer = await asyncio.open_connection("127.0.0.1", tunnel.port)
        try:
            resumed_writer.write(b"second")
            await resumed_writer.drain()
            assert await asyncio.wait_for(resumed_reader.readexactly(6), 5) == b"second"
        finally:
            resumed_writer.close()
            await resumed_writer.wait_closed()
    finally:
        writer.close()
        await writer.wait_closed()
        await tunnel.close()
    assert all(child.returncode is not None for child in children)


async def test_failed_ssh_never_releases_origin_or_forwards_to_competitor(ssh_child):
    state, children = ssh_child
    state["script"] = "import sys\nsys.stderr.write('Permission denied\\n' + 'x' * 100000)\nsys.exit(255)"
    tunnel = await open_tunnel(PROFILE, 8765)
    state["port"] = tunnel.port
    reader, writer = await asyncio.open_connection("127.0.0.1", tunnel.port)
    try:
        assert await asyncio.wait_for(reader.read(), 5) == b""
        await asyncio.gather(*tunnel._streams)
        assert tunnel.error == "ssh_auth_failed"
        assert_owned(tunnel.port)
        await tunnel.pause()
        assert_owned(tunnel.port)
    finally:
        writer.close()
        await writer.wait_closed()
        await tunnel.close()
    assert children[0].returncode == 255


async def test_cancellation_during_subprocess_creation_reaps_child(ssh_child):
    state, children = ssh_child
    state["gate"] = asyncio.Event()
    tunnel = await open_tunnel(PROFILE, 8765)
    state["port"] = tunnel.port
    reader, writer = await asyncio.open_connection("127.0.0.1", tunnel.port)
    try:
        await asyncio.wait_for(state["started"].wait(), 5)
        paused = asyncio.create_task(tunnel.pause())
        await asyncio.sleep(0)
        assert not paused.done()
        assert_owned(tunnel.port)
        state["gate"].set()
        await asyncio.wait_for(paused, 5)
        assert children[0].returncode is not None
        assert await reader.read() == b""
    finally:
        state["gate"].set()
        writer.close()
        await writer.wait_closed()
        await tunnel.close()


async def test_cancellation_before_relay_starts_closes_client():
    tunnel = remote_ssh.Tunnel([], 0)
    tunnel.server = MagicMock(is_serving=lambda: True)
    writer = MagicMock()
    tunnel.accept(asyncio.StreamReader(), writer)
    await tunnel.pause()
    writer.close.assert_called()
    assert not tunnel._streams


async def test_occupied_port_is_rejected_even_with_reuseaddr(monkeypatch):
    monkeypatch.setattr(remote_ssh.shutil, "which", lambda _: "fixture-ssh")
    with socket.socket() as owner:
        owner.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        owner.bind(("127.0.0.1", 0))
        owner.listen()
        with pytest.raises(RemoteError, match="local_port_in_use"):
            await open_tunnel(PROFILE, 8765, local_port=owner.getsockname()[1])


def test_windows_listener_uses_exclusive_bind(monkeypatch):
    listener = MagicMock()
    listener.getsockname.return_value = ("127.0.0.1", 24000)
    monkeypatch.setattr(remote_ssh.socket, "socket", lambda: listener)
    monkeypatch.setattr(remote_ssh.socket, "SO_EXCLUSIVEADDRUSE", 123456, raising=False)
    assert remote_ssh._listen(24000, set()) is listener
    listener.setsockopt.assert_called_once_with(socket.SOL_SOCKET, 123456, 1)
    listener.bind.assert_called_once_with(("127.0.0.1", 24000))


def test_new_origin_skips_retired_ports_without_releasing_them_early(monkeypatch):
    retired, fresh = MagicMock(), MagicMock()
    retired.getsockname.return_value = ("127.0.0.1", 24000)
    fresh.getsockname.return_value = ("127.0.0.1", 24001)

    def sockets():
        yield retired
        retired.close.assert_not_called()
        yield fresh

    candidates = sockets()
    monkeypatch.setattr(remote_ssh.socket, "socket", lambda: next(candidates))
    assert remote_ssh._listen(0, {24000}) is fresh
    retired.close.assert_called_once()
    fresh.close.assert_not_called()


async def test_listener_is_released_only_on_final_close(monkeypatch):
    monkeypatch.setattr(remote_ssh.shutil, "which", lambda _: "fixture-ssh")
    tunnel = await open_tunnel(PROFILE, 8765)
    try:
        assert_owned(tunnel.port)
        await tunnel.pause()
        assert_owned(tunnel.port)
    finally:
        await tunnel.close()
    with contextlib.closing(socket.socket()) as replacement:
        replacement.bind(("127.0.0.1", tunnel.port))
        replacement.listen()
