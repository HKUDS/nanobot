from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from nanobot.channels.whatsapp.connect import WhatsAppConnectStore
from nanobot.config.schema import Config


class _FakeClient:
    def __init__(
        self,
        channel: "_FakeChannel",
        *,
        complete: bool,
        stop_gate: asyncio.Event | None = None,
        linger_until_stopped: bool = False,
    ) -> None:
        self.channel = channel
        self.complete = complete
        self.result: asyncio.Future[None] | None = None
        self.qr_handler: Any = None
        self.stopped = False
        self.stop_gate = stop_gate
        self.linger_until_stopped = linger_until_stopped
        self.native_stop = asyncio.Event()
        self.native_released = False
        self.connect_task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        await self.qr_handler(b"whatsapp-qr-payload")
        if self.complete:
            Path(self.channel.config.database_path).write_bytes(b"new-session")
            assert self.result is not None
            self.result.set_result(None)
            if self.linger_until_stopped:
                await self.native_stop.wait()
                self.native_released = True
            return
        await self.native_stop.wait()
        self.native_released = True

    async def stop(self) -> None:
        if self.stop_gate is not None:
            await self.stop_gate.wait()
        self.native_stop.set()
        self.stopped = True


class _FakeChannel:
    def __init__(
        self,
        *,
        complete: bool,
        stop_gate: asyncio.Event | None = None,
        linger_until_stopped: bool = False,
    ) -> None:
        self.config = SimpleNamespace(database_path="")
        self.client = _FakeClient(
            self,
            complete=complete,
            stop_gate=stop_gate,
            linger_until_stopped=linger_until_stopped,
        )

    def connect_open_client(
        self,
        qr_handler: Any,
    ) -> tuple[_FakeClient, asyncio.Future[None]]:
        result = asyncio.get_running_loop().create_future()
        self.client.result = result
        self.client.qr_handler = qr_handler
        return self.client, result

    async def connect_start_client(
        self,
        client: _FakeClient,
        _result: asyncio.Future[None],
    ) -> asyncio.Task[None] | None:
        if client.linger_until_stopped:
            client.connect_task = asyncio.create_task(client.connect())
            await asyncio.sleep(0)
            return client.connect_task
        await client.connect()
        return None


@pytest.mark.asyncio
async def test_whatsapp_connect_commits_new_session_after_scan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "neonize.db"
    target.write_bytes(b"old-session")
    channel = _FakeChannel(complete=True)
    store = WhatsAppConnectStore()
    monkeypatch.setattr(store, "_build_channel", lambda: (channel, target))

    started = await store.start(force=True)
    completed = await store.poll(started["session_id"])

    assert started["status"] == "pending"
    assert started["qr_url"] == "whatsapp-qr-payload"
    assert completed["status"] == "succeeded"
    assert target.read_bytes() == b"new-session"
    assert channel.client.stopped is True
    assert store.has_pending_work is False


@pytest.mark.asyncio
async def test_whatsapp_connect_cancel_preserves_existing_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "neonize.db"
    target.write_bytes(b"working-session")
    channel = _FakeChannel(complete=False)
    store = WhatsAppConnectStore()
    monkeypatch.setattr(store, "_build_channel", lambda: (channel, target))

    started = await store.start(force=True)
    assert store.has_pending_work is True
    pending_path = Path(channel.config.database_path)
    pending_path.write_bytes(b"partial-session")
    cancelled = await store.cancel(started["session_id"])

    assert cancelled["status"] == "cancelled"
    assert target.read_bytes() == b"working-session"
    assert not pending_path.exists()
    assert channel.client.stopped is True
    assert store.has_pending_work is False


@pytest.mark.asyncio
async def test_whatsapp_connect_clears_qr_while_finishing_login(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "neonize.db"
    stop_gate = asyncio.Event()
    channel = _FakeChannel(complete=True, stop_gate=stop_gate)
    store = WhatsAppConnectStore()
    monkeypatch.setattr(store, "_build_channel", lambda: (channel, target))

    started = await store.start(force=True)
    finishing = await store.poll(started["session_id"])

    assert finishing["status"] == "pending"
    assert finishing["qr_url"] == ""
    assert store.has_pending_work is True

    stop_gate.set()
    await asyncio.sleep(0)
    completed = await store.poll(started["session_id"])

    assert completed["status"] == "succeeded"
    assert target.read_bytes() == b"new-session"


@pytest.mark.asyncio
async def test_whatsapp_connect_waits_for_native_client_before_committing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "neonize.db"
    channel = _FakeChannel(complete=True, linger_until_stopped=True)
    store = WhatsAppConnectStore()
    monkeypatch.setattr(store, "_build_channel", lambda: (channel, target))

    started = await store.start(force=True)
    completed: dict[str, Any] = {"status": "pending"}
    for _ in range(10):
        completed = await store.poll(started["session_id"])
        if completed["status"] != "pending":
            break
        await asyncio.sleep(0)

    assert completed["status"] == "succeeded"
    assert channel.client.native_released is True
    assert target.read_bytes() == b"new-session"


@pytest.mark.asyncio
async def test_whatsapp_connect_retries_transient_windows_database_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pending = tmp_path / ".neonize.db.connect"
    target = tmp_path / "neonize.db"
    pending.write_bytes(b"new-session")
    replace = os.replace
    attempts = 0

    def replace_after_release(source: Path, destination: Path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError(32, "file is in use", str(source), str(destination))
        replace(source, destination)

    monkeypatch.setattr(os, "replace", replace_after_release)

    await WhatsAppConnectStore._commit_database(pending, target)

    assert attempts == 2
    assert target.read_bytes() == b"new-session"


@pytest.mark.asyncio
async def test_whatsapp_connect_store_closes_pending_login(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "neonize.db"
    channel = _FakeChannel(complete=False)
    store = WhatsAppConnectStore()
    monkeypatch.setattr(store, "_build_channel", lambda: (channel, target))

    started = await store.start(force=True)
    pending_path = Path(channel.config.database_path)
    pending_path.write_bytes(b"partial-session")

    await store.close()

    assert started["status"] == "pending"
    assert not pending_path.exists()
    assert channel.client.stopped is True
    assert store.has_pending_work is False


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["cancel", "finalize"])
async def test_native_thread_timeout_keeps_database_and_can_retry_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, action: str,
) -> None:
    """A cancelled asyncio wrapper cannot prove a native SQLite writer stopped."""
    target = tmp_path / "neonize.db"
    target.write_bytes(b"working-session")
    native_entered, native_release, native_exited = (
        threading.Event(), threading.Event(), threading.Event(),
    )
    channel = _FakeChannel(complete=action == "finalize", linger_until_stopped=True)
    store = WhatsAppConnectStore()
    monkeypatch.setattr(store, "_build_channel", lambda: (channel, target))
    monkeypatch.setattr("nanobot.channels.whatsapp.connect._NATIVE_STOP_TIMEOUT_SECONDS", 0.03)

    def native_writer() -> None:
        native_entered.set()
        assert native_release.wait(3)
        native_exited.set()

    async def connect() -> None:
        await channel.client.qr_handler(b"whatsapp-qr-payload")
        Path(channel.config.database_path).write_bytes(b"new-session")
        if channel.client.complete:
            channel.client.result.set_result(None)
        await asyncio.to_thread(native_writer)

    monkeypatch.setattr(channel.client, "connect", connect)
    started = await store.start(force=True)
    pending = Path(channel.config.database_path)
    try:
        assert await asyncio.to_thread(native_entered.wait, 1)
        if action == "cancel":
            with pytest.raises(RuntimeError, match="still stopping"):
                await store.cancel(started["session_id"])
        else:
            result = await store.poll(started["session_id"])
            assert result["status"] == "failed"
            assert "still stopping" in result["message"]
        assert store.has_pending_work is True
        assert channel.client.connect_task is not None
        assert not channel.client.connect_task.done()
        assert not native_exited.is_set()
        assert pending.read_bytes() == b"new-session"
        assert target.read_bytes() == b"working-session"
    finally:
        native_release.set()
        await store.cancel(started["session_id"])
    assert native_exited.is_set()
    assert store.has_pending_work is False
    assert not pending.exists()
    assert target.read_bytes() == b"working-session"


@pytest.mark.asyncio
async def test_cancelling_cleanup_waiter_keeps_owned_shutdown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    target = tmp_path / "neonize.db"
    stop_gate = asyncio.Event()
    channel = _FakeChannel(complete=False, stop_gate=stop_gate)
    store = WhatsAppConnectStore()
    monkeypatch.setattr(store, "_build_channel", lambda: (channel, target))
    started = await store.start(force=True)
    pending = Path(channel.config.database_path)
    pending.write_bytes(b"partial-session")
    waiter = asyncio.create_task(store.cancel(started["session_id"]))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert store.has_pending_work is True
    assert pending.exists()
    stop_gate.set()
    await store.close()
    assert store.has_pending_work is False
    assert channel.client.native_released is True
    assert not pending.exists()


@pytest.mark.asyncio
async def test_abandoned_login_expires_without_another_browser_poll(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    target = tmp_path / "neonize.db"
    channel = _FakeChannel(complete=False)
    store = WhatsAppConnectStore()
    monkeypatch.setattr(store, "_build_channel", lambda: (channel, target))
    monkeypatch.setattr("nanobot.channels.whatsapp.connect._CONNECT_TTL_SECONDS", 0.02)
    started = await store.start(force=True)
    session = store._sessions[started["session_id"]]
    try:
        await asyncio.wait_for(channel.client.native_stop.wait(), timeout=1)
        assert session.discard_task is not None
        await asyncio.wait_for(asyncio.shield(session.discard_task), timeout=1)
        assert store.has_pending_work is False
        assert channel.client.native_released is True
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_cancel_during_finalize_does_not_promote_login_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    target = tmp_path / "neonize.db"
    target.write_bytes(b"working-session")
    stop_gate = asyncio.Event()
    channel = _FakeChannel(complete=True, stop_gate=stop_gate)
    store = WhatsAppConnectStore()
    monkeypatch.setattr(store, "_build_channel", lambda: (channel, target))
    started = await store.start(force=True)
    assert (await store.poll(started["session_id"]))["status"] == "pending"
    cancelling = asyncio.create_task(store.cancel(started["session_id"]))
    await asyncio.sleep(0)
    polling = asyncio.create_task(store.poll(started["session_id"]))
    try:
        assert store.has_pending_work is True
    finally:
        stop_gate.set()
        cancelled, polled = await asyncio.gather(cancelling, polling)
    assert cancelled["status"] == polled["status"] == "cancelled"
    assert target.read_bytes() == b"working-session"
    assert not Path(channel.config.database_path).exists()
    assert store.has_pending_work is False


def test_connect_builds_channel_with_shared_network_settings(monkeypatch, tmp_path) -> None:
    database = tmp_path / "neonize.db"
    config = Config.model_validate({
        "network": {"proxy": "http://127.0.0.1:7890"},
        "channels": {"whatsapp": {"useProxy": True, "databasePath": str(database)}},
    })
    monkeypatch.setattr("nanobot.channels.whatsapp.connect.load_config", lambda: config)

    channel, target = WhatsAppConnectStore._build_channel()

    assert channel.network is config.network
    assert channel.config.use_proxy is True
    assert target == database
