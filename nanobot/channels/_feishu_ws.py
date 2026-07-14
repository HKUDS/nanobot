"""Shared Feishu/Lark WebSocket runtime.

The official lark_oapi websocket client stores an asyncio loop in a module-level
variable.  Running one blocking ``Client.start()`` per assistant would make
multiple Feishu instances fragile, so this module centralizes the loop patch and
starts each client through the SDK's async primitives on one dedicated loop.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Protocol

from loguru import logger


class _LarkWsClient(Protocol):
    """Private SDK surface isolated behind the Feishu runtime adapter."""

    _auto_reconnect: bool
    _receive_message_loop: Callable[[], Awaitable[None]]

    async def _connect(self) -> None: ...

    async def _disconnect(self) -> None: ...

    async def _ping_loop(self) -> None: ...


@dataclass
class _ClientRuntime:
    client: _LarkWsClient
    stop_event: asyncio.Event
    task: asyncio.Task[Any] | None
    receive_loop: Callable[[], Awaitable[None]]
    auto_reconnect: bool
    receive_tasks: set[asyncio.Task[Any]] = field(default_factory=set)


class FeishuWsRunner:
    """Run multiple lark_oapi websocket clients on one dedicated event loop."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._clients: dict[str, _ClientRuntime] = {}

    async def start_client(self, key: str, client: _LarkWsClient) -> None:
        """Start or replace one client runtime."""
        loop = self._ensure_loop()
        await asyncio.wrap_future(
            asyncio.run_coroutine_threadsafe(self._start_client(key, client), loop)
        )

    async def stop_client(self, key: str) -> None:
        """Stop one client runtime if it is active."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(self._stop_client(key), loop))

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is not None and not self._loop.is_closed():
                return self._loop
            self._ready.clear()
            self._thread = threading.Thread(target=self._run_loop, name="feishu-ws", daemon=True)
            self._thread.start()
            if not self._ready.wait(timeout=10) or self._loop is None:
                raise RuntimeError("Feishu WebSocket runner did not start")
            return self._loop

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            import lark_oapi.ws.client as lark_ws_client

            lark_ws_client.loop = loop
            self._loop = loop
            self._ready.set()
            loop.run_forever()
        finally:
            with suppress(Exception):
                loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    async def _start_client(self, key: str, client: _LarkWsClient) -> None:
        await self._stop_client(key)
        stop_event = asyncio.Event()
        receive_loop = client._receive_message_loop
        runtime = _ClientRuntime(
            client=client,
            stop_event=stop_event,
            task=None,
            receive_loop=receive_loop,
            auto_reconnect=client._auto_reconnect,
        )

        # The SDK discards this task handle. Track it at the adapter boundary so
        # an intentional stop can cancel recv() before closing the socket; otherwise
        # the SDK logs close code 1000 as an error and starts an unwanted reconnect.
        async def tracked_receive_loop() -> None:
            if stop_event.is_set():
                return
            task = asyncio.current_task()
            if task is not None:
                runtime.receive_tasks.add(task)
            try:
                await receive_loop()
            finally:
                if task is not None:
                    runtime.receive_tasks.discard(task)

        client._receive_message_loop = tracked_receive_loop
        runtime.task = asyncio.create_task(self._client_main(key, client, stop_event))
        self._clients[key] = runtime

    async def _stop_client(self, key: str) -> None:
        runtime = self._clients.pop(key, None)
        if runtime is None:
            return
        runtime.stop_event.set()
        runtime.client._auto_reconnect = False
        try:
            receive_tasks = tuple(runtime.receive_tasks)
            for task in receive_tasks:
                task.cancel()
            if receive_tasks:
                await asyncio.gather(*receive_tasks, return_exceptions=True)

            if runtime.task is not None:
                runtime.task.cancel()
                with suppress(asyncio.CancelledError):
                    await runtime.task
            with suppress(Exception):
                await runtime.client._disconnect()
        finally:
            runtime.client._receive_message_loop = runtime.receive_loop
            runtime.client._auto_reconnect = runtime.auto_reconnect

    async def _client_main(
        self, key: str, client: _LarkWsClient, stop_event: asyncio.Event
    ) -> None:
        ping_task: asyncio.Task | None = None
        while not stop_event.is_set():
            try:
                await client._connect()
                ping_task = asyncio.create_task(client._ping_loop())
                await stop_event.wait()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Feishu WebSocket client '{}' failed: {}", key, exc)
                with suppress(Exception):
                    await client._disconnect()
                if not stop_event.is_set():
                    await asyncio.sleep(5)
            finally:
                if ping_task is not None:
                    ping_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await ping_task
                with suppress(Exception):
                    await client._disconnect()


_RUNNER: FeishuWsRunner | None = None


def get_feishu_ws_runner() -> FeishuWsRunner:
    """Return the process-wide Feishu WebSocket runner."""
    global _RUNNER
    if _RUNNER is None:
        _RUNNER = FeishuWsRunner()
    return _RUNNER
