"""Pairing changes invalidate authenticated WebUI snapshots without idle polling."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from threading import Event as ThreadEvent
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import websockets

from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.channels.websocket.tests.ws_test_client import wait_for_listener
from nanobot.config.loader import save_config
from nanobot.config.schema import Config
from nanobot.pairing import notifications
from nanobot.pairing import store as pairing
from nanobot.pairing.notifications import PairingNotifications
from nanobot.webui.gateway_services import build_gateway_services


def _channel(tmp_path: Path) -> WebSocketChannel:
    config = WebSocketConfig(
        host="127.0.0.1", port=0, path="/ws", allow_from=["*"],
        token="fixture-client", token_issue_secret="fixture-bootstrap", websocket_requires_token=True,
    )
    bus = MessageBus()
    config_path = tmp_path / "configuration" / "config.json"
    save_config(Config(), config_path)
    gateway = build_gateway_services(
        config=config, bus=bus, session_manager=None, static_dist_path=None,
        workspace_path=tmp_path / "workspace", default_restrict_to_workspace=False,
        config_path=config_path, runtime_model_name=None, runtime_surface="browser",
        runtime_capabilities_overrides=None,
    )
    return WebSocketChannel(config, bus, gateway=gateway)


async def _write_in_another_process(operation: str) -> float:
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", """
import sys, time
from pathlib import Path
from nanobot.config.loader import set_config_path
from nanobot.pairing.store import generate_code, record_delivery, list_pending
set_config_path(Path(sys.argv[1]) / "config.json")
""" + operation + "\nprint(time.monotonic(), flush=True)\n",
        str(pairing.pairing_store_path().parent),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5)
        assert process.returncode == 0, (stdout.decode(), stderr.decode())
        return float(stdout.decode().strip())
    finally:
        if process.returncode is None:
            process.kill()
        await process.communicate()


def _assert_sources_closed() -> None:
    assert not [task for task in asyncio.all_tasks() if task.get_name().startswith("pairing-")]


async def test_cross_process_changes_reach_only_bootstrap_authenticated_webui(tmp_path: Path) -> None:
    channel = _channel(tmp_path)
    serving = asyncio.create_task(channel.start())
    try:
        port = await wait_for_listener(channel, serving)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", trust_env=False) as http:
            assert (await http.get("/webui/bootstrap")).status_code == 401
            response = await http.get("/webui/bootstrap", headers={"X-Nanobot-Auth": "fixture-bootstrap"})
            assert response.status_code == 200
            bootstrap = response.json()
            http.headers["Authorization"] = f"Bearer {bootstrap['api_token']}"
            assert (await http.get("/api/settings/pairing")).json() == {"requests": []}
            async with (
                websockets.connect(f"ws://127.0.0.1:{port}/ws?token={bootstrap['token']}") as webui,
                websockets.connect(f"ws://127.0.0.1:{port}/ws?token=fixture-client&client_id=webui") as ordinary,
            ):
                assert json.loads(await webui.recv())["event"] == "ready"
                assert json.loads(await ordinary.recv())["event"] == "ready"
                assert not pairing.pairing_store_path().exists()
                committed = await _write_in_another_process('generate_code("telegram", "private-sender")')
                assert json.loads(await asyncio.wait_for(webui.recv(), timeout=2)) == {"event": "pairing_changed"}
                assert time.monotonic() - committed < 2
                request = (await http.get("/api/settings/pairing")).json()["requests"][0]
                assert request["sender_id"] == "private-sender"

                # Delivery replaces the same file; the event still contains no code or sender.
                await _write_in_another_process('record_delivery(list_pending()[0]["code"], "sent")')
                assert json.loads(await asyncio.wait_for(webui.recv(), timeout=2)) == {"event": "pairing_changed"}
                assert (await http.get("/api/settings/pairing")).json()["requests"][0]["delivery_status"] == "sent"

                # The existing mutation route needs no extra explicit notification.
                await webui.send(json.dumps({
                    "type": "webui_request", "request_id": "approve", "action": "settings.pairing.approve",
                    "payload": {"code": request["code"]},
                }))
                messages = [json.loads(await asyncio.wait_for(webui.recv(), timeout=2)) for _ in range(2)]
                assert {"event": "pairing_changed"} in messages
                result = next(message for message in messages if message["event"] == "webui_response")
                assert result["request_id"] == "approve" and result["ok"] is True
                assert (await http.get("/api/settings/pairing")).json()["requests"] == []
                assert pairing.is_approved("telegram", "private-sender")
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(ordinary.recv(), timeout=0.3)
    finally:
        await channel.stop()
        await serving
    _assert_sources_closed()


async def test_initial_pending_request_expires_without_writing_the_store() -> None:
    code = pairing.generate_code("telegram", "expiry", ttl=1)
    path = pairing.pairing_store_path()
    before = path.read_bytes(), path.stat().st_mtime_ns
    changed = asyncio.Event()
    source = PairingNotifications()
    await source.start(AsyncMock(side_effect=changed.set))
    try:
        await asyncio.wait_for(changed.wait(), timeout=2)
        assert pairing.list_pending() == []
        assert pairing.approve_code(code) is None
        assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    finally:
        await source.close()
    _assert_sources_closed()


async def test_sibling_noise_neither_notifies_nor_starves_registration_or_pairing_changes() -> None:
    path = pairing.pairing_store_path()
    changes: asyncio.Queue[None] = asyncio.Queue()
    written = asyncio.Event()
    writes = 0

    async def sender() -> None:
        await changes.put(None)

    async def write_noise() -> None:
        nonlocal writes
        with (path.parent / "noise.log").open("ab", buffering=0) as noise:
            while True:
                noise.write(b"unrelated\n")
                writes += 1
                written.set()
                await asyncio.sleep(0.01)

    source = PairingNotifications()
    writer = asyncio.create_task(write_noise())
    starting = asyncio.create_task(source.start(sender))
    try:
        await asyncio.wait_for(written.wait(), timeout=2)
        await asyncio.wait_for(asyncio.shield(starting), timeout=2)
        writes_at_ready = writes
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(changes.get(), timeout=0.35)
        assert writes > writes_at_ready and not writer.done()
        committed = await _write_in_another_process('generate_code("telegram", "amid-noise")')
        await asyncio.wait_for(changes.get(), timeout=2)
        assert time.monotonic() - committed < 2
        assert pairing.list_pending()[0]["sender_id"] == "amid-noise"
        assert not writer.done()
    finally:
        starting.cancel()
        writer.cancel()
        await asyncio.gather(starting, writer, return_exceptions=True)
        await source.close()
    _assert_sources_closed()


async def test_failed_registration_can_restart_and_close_can_reopen(monkeypatch: pytest.MonkeyPatch) -> None:
    real_awatch = notifications.awatch

    async def failed_watch(*_args, **_kwargs):
        raise OSError("native registration failed")
        yield set()

    source = PairingNotifications()
    monkeypatch.setattr(notifications, "awatch", failed_watch)
    with pytest.raises(OSError, match="registration failed"):
        await source.start(AsyncMock())
    _assert_sources_closed()
    monkeypatch.setattr(notifications, "awatch", real_awatch)
    for sender_id in ("first-lifetime", "second-lifetime"):
        changed = asyncio.Event()
        await source.start(AsyncMock(side_effect=changed.set))
        try:
            pairing.generate_code("telegram", sender_id)
            await asyncio.wait_for(changed.wait(), timeout=2)
        finally:
            await source.close()
            await source.close()
        _assert_sources_closed()


@pytest.mark.parametrize("cancel_during", ["start", "close"])
async def test_cancel_joins_domain_locked_deadline_read(
    monkeypatch: pytest.MonkeyPatch, cancel_during: str,
) -> None:
    entered = ThreadEvent()
    original = notifications.pending_expirations
    source = PairingNotifications()
    if cancel_during == "close":
        await source.start(AsyncMock())
        pairing.generate_code("telegram", "read-during-close")

    def read_deadlines(path: Path) -> tuple[float, ...]:
        entered.set()
        return original(path)

    monkeypatch.setattr(notifications, "pending_expirations", read_deadlines)
    pairing._LOCK.acquire()
    operation = asyncio.create_task(source.start(AsyncMock())) if cancel_during == "start" else None
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        if operation is None:
            operation = asyncio.create_task(source.close())
            await asyncio.sleep(0)
        operation.cancel()
        await asyncio.sleep(0.05)
        assert not operation.done()
    finally:
        pairing._LOCK.release()
        if operation is not None:
            with pytest.raises(asyncio.CancelledError):
                await operation
        await source.close()
    _assert_sources_closed()


@pytest.mark.parametrize("failure", [
    OSError("native watch interrupted"),
    ExceptionGroup("unhandled errors in a TaskGroup", [OSError("native watch interrupted")]),
], ids=["direct", "native-task-group"])
async def test_re_registered_watch_reconciles_gap_and_observes_later_replaces(
    monkeypatch: pytest.MonkeyPatch, failure: Exception,
) -> None:
    # Recovery must reconcile the missed change before expiry, independent of
    # wall-clock jumps. Real deadline expiration has separate native coverage.
    now = [time.time()]
    clock = SimpleNamespace(time=lambda: now[0])
    monkeypatch.setattr(notifications, "time", clock)
    monkeypatch.setattr(pairing, "time", clock)
    real_awatch = notifications.awatch
    interrupt, interrupted = asyncio.Event(), asyncio.Event()

    async def interrupted_watch(*args, **kwargs):
        async for batch in real_awatch(*args, **kwargs):
            yield batch
            if not interrupted.is_set():
                await interrupt.wait()
                interrupted.set()
                raise failure

    monkeypatch.setattr(notifications, "awatch", interrupted_watch)
    changed = asyncio.Event()
    source = PairingNotifications()
    await source.start(AsyncMock(side_effect=changed.set))
    try:
        interrupt.set()
        await asyncio.wait_for(interrupted.wait(), timeout=2)
        pairing.generate_code("telegram", "during-recovery", ttl=2)
        await asyncio.wait_for(changed.wait(), timeout=3)
        assert pairing.list_pending()[0]["sender_id"] == "during-recovery"
        changed.clear()
        now[0] += 3
        await asyncio.wait_for(changed.wait(), timeout=3)
        assert pairing.list_pending() == []
        changed.clear()
        await _write_in_another_process('generate_code("telegram", "after-recovery")')
        await asyncio.wait_for(changed.wait(), timeout=2)
        assert pairing.list_pending()[0]["sender_id"] == "after-recovery"
    finally:
        await source.close()
    _assert_sources_closed()


async def test_unknown_deadline_source_error_is_not_native_watch_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    def failed_read(_path: Path) -> tuple[float, ...]:
        raise RuntimeError("unexpected domain failure")

    monkeypatch.setattr(notifications, "pending_expirations", failed_read)
    source = PairingNotifications()
    with pytest.raises(RuntimeError, match="unexpected domain failure"):
        await source.start(AsyncMock())
    await source.close()
    _assert_sources_closed()


async def test_listener_bind_failure_closes_pairing_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    channel = _channel(tmp_path)

    async def failed_serve(*_args, **_kwargs):
        raise OSError(98, "fixture listener bind failed")

    monkeypatch.setattr("nanobot.channels.websocket.runtime.serve", failed_serve)
    with pytest.raises(OSError, match="listener bind failed"):
        await channel.start()
    await channel.stop()
    _assert_sources_closed()
