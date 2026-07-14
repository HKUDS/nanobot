from __future__ import annotations

import asyncio
import threading
from typing import Any

from nanobot.channels._feishu_ws import FeishuWsRunner


class _CleanCloseError(Exception):
    pass


class _SdkLikeClient:
    """Model the lark SDK's detached receive task and reconnect behavior."""

    def __init__(self) -> None:
        self._auto_reconnect = True
        self.connected = asyncio.Event()
        self.reconnected = asyncio.Event()
        self.receive_errors = 0
        self.reconnects = 0
        self.disconnects = 0
        self._receiving = False
        self._receive_events: asyncio.Queue[Exception] = asyncio.Queue()

    async def _connect(self) -> None:
        self.connected.set()
        asyncio.create_task(self._receive_message_loop())

    async def _receive_message_loop(self) -> None:
        try:
            self._receiving = True
            error = await self._receive_events.get()
            self._receiving = False
            raise error
        except asyncio.CancelledError:
            self._receiving = False
            raise
        except Exception:
            self.receive_errors += 1
            await self._disconnect()
            if self._auto_reconnect:
                self.reconnects += 1
                await self._connect()
                self.reconnected.set()

    async def _disconnect(self) -> None:
        self.disconnects += 1
        if self._receiving:
            await self._receive_events.put(_CleanCloseError("1000 OK"))

    async def _ping_loop(self) -> None:
        await asyncio.Event().wait()


def test_concurrent_loop_initialization_starts_one_thread(monkeypatch) -> None:
    runner = FeishuWsRunner()
    created_loops: list[asyncio.AbstractEventLoop] = []
    release_start = threading.Event()

    def fake_run_loop() -> None:
        loop = asyncio.new_event_loop()
        created_loops.append(loop)
        assert release_start.wait(timeout=2)
        runner._loop = loop
        runner._ready.set()

    monkeypatch.setattr(runner, "_run_loop", fake_run_loop)
    loops: list[asyncio.AbstractEventLoop] = []
    threads = [threading.Thread(target=lambda: loops.append(runner._ensure_loop())) for _ in range(2)]

    for thread in threads:
        thread.start()
    release_start.set()
    for thread in threads:
        thread.join(timeout=2)

    assert len(created_loops) == 1
    assert loops == [created_loops[0], created_loops[0]]
    created_loops[0].close()


async def test_stop_cancels_sdk_receive_loop_without_reconnecting() -> None:
    runner = FeishuWsRunner()
    client = _SdkLikeClient()
    original_receive_loop: Any = client._receive_message_loop

    await runner._start_client("default", client)
    await asyncio.wait_for(client.connected.wait(), timeout=1)
    await runner._stop_client("default")
    await asyncio.sleep(0)

    assert client.receive_errors == 0
    assert client.reconnects == 0
    assert client._auto_reconnect is True
    assert client._receive_message_loop == original_receive_loop


async def test_network_failure_keeps_sdk_auto_reconnect_behavior() -> None:
    runner = FeishuWsRunner()
    client = _SdkLikeClient()

    await runner._start_client("default", client)
    await asyncio.wait_for(client.connected.wait(), timeout=1)
    await client._receive_events.put(RuntimeError("network dropped"))
    await asyncio.wait_for(client.reconnected.wait(), timeout=1)

    assert client.receive_errors == 1
    assert client.reconnects == 1
    assert client._auto_reconnect is True

    await runner._stop_client("default")
    await asyncio.sleep(0)
    assert client.receive_errors == 1
    assert client.reconnects == 1
