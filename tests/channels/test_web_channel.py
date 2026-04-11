"""Tests for the Web channel.

Covers the module-level history/name helpers as unit tests, and the aiohttp
server endpoints + WebSocket handler as lightweight integration tests backed
by a real running WebChannel on a random loopback port.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from nanobot.channels import web as web_module
from nanobot.channels.web import WebChannel

# --- Fixtures ---------------------------------------------------------------


@pytest.fixture()
def bus() -> MagicMock:
    b = MagicMock()
    b.publish_inbound = AsyncMock()
    b.publish_outbound = AsyncMock()
    return b


@pytest.fixture()
def tmp_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the module-level history directory into tmp_path.

    All helpers read the module-level ``_HISTORY_DIR`` each call, so swapping
    it here keeps tests hermetic without touching ``~/.nanobot``.
    """
    monkeypatch.setattr(web_module, "_HISTORY_DIR", tmp_path)
    return tmp_path


def _make_channel(bus: Any, port: int, **overrides: Any) -> WebChannel:
    cfg: dict[str, Any] = {
        "enabled": True,
        "host": "127.0.0.1",
        "port": port,
        "allow_from": ["*"],
        "bearer_token": "test-token",
        "streaming": False,  # avoid the streaming _wants_stream path for these tests
    }
    cfg.update(overrides)
    return WebChannel(cfg, bus)


async def _start(channel: WebChannel) -> asyncio.Task:
    task = asyncio.create_task(channel.start())
    # Give the aiohttp site a moment to bind.
    for _ in range(20):
        await asyncio.sleep(0.05)
        if channel._runner is not None:
            return task
    return task


async def _stop(channel: WebChannel, task: asyncio.Task) -> None:
    await channel.stop()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()


# --- Unit tests: history helpers -------------------------------------------


def test_append_and_read_history_since(tmp_history: Path) -> None:
    cid = "chat1"
    web_module._append_history(cid, {"ts": 100.0, "type": "user_message", "content": "a"})
    web_module._append_history(cid, {"ts": 200.0, "type": "message", "content": "b"})
    web_module._append_history(cid, {"ts": 300.0, "type": "message", "content": "c"})

    all_entries = web_module._read_history_since(cid, 0)
    assert [e["content"] for e in all_entries] == ["a", "b", "c"]

    recent = web_module._read_history_since(cid, 150.0)
    assert [e["content"] for e in recent] == ["b", "c"]

    nothing = web_module._read_history_since(cid, 999.0)
    assert nothing == []


def test_read_history_missing_file_returns_empty(tmp_history: Path) -> None:
    assert web_module._read_history_since("never-written", 0) == []


def test_history_trims_to_max(tmp_history: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_module, "_HISTORY_MAX", 5)
    cid = "chat2"
    for i in range(12):
        web_module._append_history(cid, {"ts": float(i), "type": "message", "content": f"m{i}"})

    entries = web_module._read_history_since(cid, 0)
    assert len(entries) == 5
    # Only the newest 5 survive.
    assert [e["content"] for e in entries] == ["m7", "m8", "m9", "m10", "m11"]


def test_chat_name_roundtrip(tmp_history: Path) -> None:
    assert web_module._get_chat_name("c") is None
    web_module._set_chat_name("c", "  My Chat  ")
    assert web_module._get_chat_name("c") == "My Chat"


def test_chat_name_truncates_to_80_chars(tmp_history: Path) -> None:
    long = "x" * 200
    web_module._set_chat_name("c", long)
    stored = web_module._get_chat_name("c")
    assert stored is not None and len(stored) == 80


def test_check_rename_prefix(tmp_history: Path) -> None:
    assert web_module._check_rename("c", "hello world") is None
    assert web_module._check_rename("c", "rename chat: Groceries") == "Groceries"
    assert web_module._get_chat_name("c") == "Groceries"
    # Case-insensitive prefix
    assert web_module._check_rename("c", "RENAME CHAT: Todo") == "Todo"


# --- Integration tests: HTTP endpoints -------------------------------------


@pytest.mark.asyncio
async def test_unauthenticated_chats_endpoint_rejected(
    bus: MagicMock, tmp_history: Path
) -> None:
    ch = _make_channel(bus, 29951)
    task = await _start(ch)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("http://127.0.0.1:29951/chats?ids=abc") as resp:
                assert resp.status == 401
    finally:
        await _stop(ch, task)


@pytest.mark.asyncio
async def test_chats_endpoint_returns_metadata_for_known_chat(
    bus: MagicMock, tmp_history: Path
) -> None:
    web_module._append_history("cidA", {
        "ts": 100.0, "type": "user_message", "content": "hello there friend"
    })
    web_module._append_history("cidA", {
        "ts": 150.0, "type": "message", "content": "hi back"
    })
    web_module._set_chat_name("cidA", "Test Chat")

    ch = _make_channel(bus, 29952)
    task = await _start(ch)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "http://127.0.0.1:29952/chats?ids=cidA,unknownChat",
                headers={"Authorization": "Bearer test-token"},
            ) as resp:
                assert resp.status == 200
                body = await resp.json()

        assert "chats" in body
        # Unknown chat is dropped silently; only cidA comes back.
        assert [c["id"] for c in body["chats"]] == ["cidA"]
        entry = body["chats"][0]
        assert entry["name"] == "Test Chat"
        assert entry["preview"].startswith("hello there")
        assert entry["count"] == 2
        assert entry["first_ts"] == 100.0
        assert entry["last_ts"] == 150.0
    finally:
        await _stop(ch, task)


@pytest.mark.asyncio
async def test_rename_endpoint_persists_and_surfaces_in_chats(
    bus: MagicMock, tmp_history: Path
) -> None:
    web_module._append_history("cidB", {
        "ts": 1.0, "type": "user_message", "content": "seed"
    })

    ch = _make_channel(bus, 29953)
    task = await _start(ch)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "http://127.0.0.1:29953/chats/cidB/rename",
                headers={"Authorization": "Bearer test-token"},
                json={"name": "Project Fleet"},
            ) as resp:
                assert resp.status == 200
                result = await resp.json()
                assert result["ok"] is True
                assert result["name"] == "Project Fleet"

            async with session.get(
                "http://127.0.0.1:29953/chats?ids=cidB",
                headers={"Authorization": "Bearer test-token"},
            ) as resp:
                body = await resp.json()

        assert body["chats"][0]["name"] == "Project Fleet"
    finally:
        await _stop(ch, task)


# --- Hardening ------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_accepts_file_above_legacy_1mib_cap(
    bus: MagicMock, tmp_history: Path, tmp_path: Path
) -> None:
    """aiohttp's default client_max_size is 1 MiB, which would silently
    reject voice notes longer than ~60 seconds. The channel bumps it to
    16 MiB via web.Application(client_max_size=...). This test uploads
    a 2 MiB payload and asserts it completes successfully."""
    ch = _make_channel(bus, 29959)
    task = await _start(ch)
    try:
        big = tmp_path / "big.bin"
        big.write_bytes(b"\x00" * (2 * 1024 * 1024))
        async with aiohttp.ClientSession() as session:
            data = aiohttp.FormData()
            data.add_field("file", big.open("rb"), filename="big.bin",
                           content_type="application/octet-stream")
            async with session.post(
                "http://127.0.0.1:29959/upload",
                headers={"Authorization": "Bearer test-token"},
                data=data,
            ) as resp:
                assert resp.status == 200
                body = await resp.json()
                assert "path" in body and "url" in body
    finally:
        await _stop(ch, task)


@pytest.mark.asyncio
async def test_websocket_client_id_clamped_to_128_chars(
    bus: MagicMock, tmp_history: Path
) -> None:
    """A rogue client with a giant client_id query param should not be
    able to inject an unbounded dict key into self._clients. The channel
    truncates client_id (and chat_id) to 128 characters at connect time."""
    ch = _make_channel(bus, 29960)
    task = await _start(ch)
    try:
        oversized = "x" * 500
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(
                f"http://127.0.0.1:29960/ws?token=test-token&client_id={oversized}"
            ) as ws:
                msg = await asyncio.wait_for(ws.receive(), timeout=2.0)
                payload = json.loads(msg.data)
                # Length clamp applied.
                assert len(payload["client_id"]) == 128
                assert payload["client_id"] == oversized[:128]
    finally:
        await _stop(ch, task)


# --- Integration tests: WebSocket ------------------------------------------


@pytest.mark.asyncio
async def test_websocket_connect_announces_ids(bus: MagicMock, tmp_history: Path) -> None:
    ch = _make_channel(bus, 29954)
    task = await _start(ch)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(
                "http://127.0.0.1:29954/ws?token=test-token&client_id=dev1&chat_id=chatX"
            ) as ws:
                msg = await asyncio.wait_for(ws.receive(), timeout=2.0)
                assert msg.type == aiohttp.WSMsgType.TEXT
                payload = json.loads(msg.data)
                assert payload == {
                    "type": "connected",
                    "client_id": "dev1",
                    "chat_id": "chatX",
                }
    finally:
        await _stop(ch, task)


@pytest.mark.asyncio
async def test_websocket_rejects_missing_token(bus: MagicMock, tmp_history: Path) -> None:
    ch = _make_channel(bus, 29955)
    task = await _start(ch)
    try:
        async with aiohttp.ClientSession() as session:
            with pytest.raises(aiohttp.WSServerHandshakeError) as excinfo:
                await session.ws_connect("http://127.0.0.1:29955/ws?client_id=dev1")
            assert excinfo.value.status == 401
    finally:
        await _stop(ch, task)


@pytest.mark.asyncio
async def test_message_published_to_bus_and_persisted(
    bus: MagicMock, tmp_history: Path
) -> None:
    ch = _make_channel(bus, 29956)
    task = await _start(ch)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(
                "http://127.0.0.1:29956/ws?token=test-token&client_id=dev1&chat_id=chatY"
            ) as ws:
                await ws.receive()  # discard "connected"
                await ws.send_json({"type": "message", "content": "hello agent"})
                # Give the server a tick to publish and persist.
                await asyncio.sleep(0.1)

        # The bus should have seen exactly one InboundMessage from this chat.
        bus.publish_inbound.assert_called()
        inbound = bus.publish_inbound.call_args[0][0]
        assert inbound.channel == "web"
        assert inbound.chat_id == "chatY"
        assert inbound.content == "hello agent"

        # And the history file should carry it.
        persisted = web_module._read_history_since("chatY", 0)
        assert len(persisted) == 1
        assert persisted[0]["type"] == "user_message"
        assert persisted[0]["content"] == "hello agent"
    finally:
        await _stop(ch, task)


@pytest.mark.asyncio
async def test_sync_replays_history_since_timestamp(
    bus: MagicMock, tmp_history: Path
) -> None:
    # Seed three entries: one old, two newer than the client's last_seen.
    web_module._append_history("chatZ", {
        "ts": 10.0, "type": "user_message", "content": "ancient"
    })
    web_module._append_history("chatZ", {
        "ts": 50.0, "type": "message", "content": "mid"
    })
    web_module._append_history("chatZ", {
        "ts": 90.0, "type": "message", "content": "recent"
    })

    ch = _make_channel(bus, 29957)
    task = await _start(ch)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(
                "http://127.0.0.1:29957/ws?token=test-token&client_id=dev&chat_id=chatZ"
            ) as ws:
                await ws.receive()  # "connected"
                await ws.send_json({"type": "sync", "last_seen": 30.0})
                raw = await asyncio.wait_for(ws.receive(), timeout=2.0)
                payload = json.loads(raw.data)

        assert payload["type"] == "sync"
        assert [m["content"] for m in payload["messages"]] == ["mid", "recent"]
    finally:
        await _stop(ch, task)


@pytest.mark.asyncio
async def test_multi_device_message_broadcast(bus: MagicMock, tmp_history: Path) -> None:
    """A message from device A on a chat is mirrored to device B on the same chat."""
    ch = _make_channel(bus, 29958)
    task = await _start(ch)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(
                "http://127.0.0.1:29958/ws?token=test-token&client_id=devA&chat_id=shared"
            ) as ws_a, session.ws_connect(
                "http://127.0.0.1:29958/ws?token=test-token&client_id=devB&chat_id=shared"
            ) as ws_b:
                await ws_a.receive()  # "connected" for A
                await ws_b.receive()  # "connected" for B

                await ws_a.send_json({"type": "message", "content": "from A"})
                raw = await asyncio.wait_for(ws_b.receive(), timeout=2.0)
                payload = json.loads(raw.data)

        assert payload["type"] == "user_message"
        assert payload["content"] == "from A"
    finally:
        await _stop(ch, task)
