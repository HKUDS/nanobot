from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from nanobot.channels.whatsapp.connect import WhatsAppConnectStore


class _FakeClient:
    def __init__(self, channel: "_FakeChannel", *, complete: bool) -> None:
        self.channel = channel
        self.complete = complete
        self.result: asyncio.Future[None] | None = None
        self.qr_handler: Any = None
        self.stopped = False

    async def connect(self) -> None:
        await self.qr_handler(b"whatsapp-qr-payload")
        if self.complete:
            Path(self.channel.config.database_path).write_bytes(b"new-session")
            assert self.result is not None
            self.result.set_result(None)
            return
        await asyncio.Event().wait()

    async def stop(self) -> None:
        self.stopped = True


class _FakeChannel:
    def __init__(self, *, complete: bool) -> None:
        self.config = SimpleNamespace(database_path="")
        self.client = _FakeClient(self, complete=complete)

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
    ) -> None:
        await client.connect()


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
    pending_path = Path(channel.config.database_path)
    pending_path.write_bytes(b"partial-session")
    cancelled = await store.cancel(started["session_id"])

    assert cancelled["status"] == "cancelled"
    assert target.read_bytes() == b"working-session"
    assert not pending_path.exists()
    assert channel.client.stopped is True
