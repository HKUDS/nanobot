from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from nanobot.channels.whatsapp.connect import (
    WhatsAppConnectStore,
    WhatsAppDatabaseRecoveryError,
)


class _FakeClient:
    def __init__(
        self,
        channel: "_FakeChannel",
        *,
        complete: bool,
        stop_error: Exception | None = None,
    ) -> None:
        self.channel = channel
        self.complete = complete
        self.stop_error = stop_error
        self.result: asyncio.Future[None] | None = None
        self.qr_handler: Any = None
        self.stopped = False
        self.connect_calls = 0

    async def connect(self) -> None:
        self.connect_calls += 1
        await self.qr_handler(b"whatsapp-qr-payload")
        if self.complete:
            Path(self.channel.config.database_path).write_bytes(b"new-session")
            assert self.result is not None
            self.result.set_result(None)
            return
        await asyncio.Event().wait()

    async def stop(self) -> None:
        if self.stop_error is not None:
            raise self.stop_error
        self.stopped = True


class _FakeChannel:
    def __init__(self, *, complete: bool, stop_error: Exception | None = None) -> None:
        self.config = SimpleNamespace(database_path="")
        self.client = _FakeClient(self, complete=complete, stop_error=stop_error)

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
    prepared = await store.poll(started["session_id"])

    assert started["status"] == "pending"
    assert started["qr_url"] == "whatsapp-qr-payload"
    assert prepared == {
        "session_id": started["session_id"],
        "status": "prepared",
        "message": "Finishing the WhatsApp connection.",
        "_requires_finalize": True,
    }
    assert target.read_bytes() == b"old-session"
    assert channel.client.stopped is True

    repeated_start = await store.start(force=True)
    assert repeated_start == prepared

    completed = await store.finalize(started["session_id"])

    assert completed["status"] == "succeeded"
    assert target.read_bytes() == b"new-session"

    store._sessions[started["session_id"]].deadline = 0
    await store._cleanup()
    retry = await store.poll(started["session_id"])
    assert retry["status"] == "prepared"

    acknowledged = await store.complete(started["session_id"])
    replayed = await store.poll(started["session_id"])
    assert acknowledged["status"] == "succeeded"
    assert replayed["status"] == "succeeded"
    assert replayed["_terminal_replay"] is True


@pytest.mark.asyncio
async def test_whatsapp_connect_does_not_prepare_when_client_stop_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "neonize.db"
    target.write_bytes(b"old-session")
    channel = _FakeChannel(
        complete=True,
        stop_error=RuntimeError("could not close login database"),
    )
    store = WhatsAppConnectStore()
    monkeypatch.setattr(store, "_build_channel", lambda: (channel, target))
    started = await store.start(force=True)
    pending_path = Path(channel.config.database_path)

    failed = await store.poll(started["session_id"])

    assert failed["status"] == "failed"
    assert failed["retryable"] is True
    assert "could not close login database" in failed["message"]
    assert target.read_bytes() == b"old-session"
    assert pending_path.read_bytes() == b"new-session"
    assert store._sessions[started["session_id"]].state == "close_failed"

    # A persistent close failure is isolated to this session instead of
    # raising from global cleanup and poisoning every later request.
    store._sessions[started["session_id"]].deadline = 0
    await store._cleanup()
    repeated = await store.start(force=True)
    assert repeated["status"] == "failed"
    assert repeated["retryable"] is True
    assert store._sessions[started["session_id"]].state == "close_failed"

    channel.client.stop_error = None
    prepared = await store.poll(started["session_id"])
    assert prepared["status"] == "prepared"
    assert channel.client.stopped is True


@pytest.mark.asyncio
async def test_whatsapp_connect_cancel_retries_failed_close_and_removes_pending_database(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "neonize.db"
    target.write_bytes(b"old-session")
    channel = _FakeChannel(
        complete=True,
        stop_error=RuntimeError("could not close login database"),
    )
    store = WhatsAppConnectStore()
    monkeypatch.setattr(store, "_build_channel", lambda: (channel, target))
    started = await store.start(force=True)
    pending_path = Path(channel.config.database_path)

    assert (await store.poll(started["session_id"]))["status"] == "failed"
    assert pending_path.read_bytes() == b"new-session"

    channel.client.stop_error = None
    cancelled = await store.cancel(started["session_id"])

    assert cancelled["status"] == "cancelled"
    assert target.read_bytes() == b"old-session"
    assert not pending_path.exists()
    assert started["session_id"] not in store._sessions


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

    replayed = await store.poll(started["session_id"])
    assert replayed["status"] == "cancelled"
    assert replayed["_terminal_replay"] is True


@pytest.mark.asyncio
async def test_whatsapp_connect_reuses_active_session_for_same_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "neonize.db"
    channel = _FakeChannel(complete=False)
    store = WhatsAppConnectStore()
    monkeypatch.setattr(store, "_build_channel", lambda: (channel, target))

    first = await store.start(force=True)
    second = await store.start(force=True)

    assert second["session_id"] == first["session_id"]
    assert second["qr_url"] == first["qr_url"]
    assert channel.client.connect_calls == 1

    await store.cancel(first["session_id"])


@pytest.mark.asyncio
async def test_whatsapp_connect_finalize_wins_over_queued_cancel(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "neonize.db"
    target.write_bytes(b"old-session")
    channel = _FakeChannel(complete=True)
    store = WhatsAppConnectStore()
    monkeypatch.setattr(store, "_build_channel", lambda: (channel, target))
    started = await store.start(force=True)
    assert (await store.poll(started["session_id"]))["status"] == "prepared"

    await store._lock.acquire()
    finalized_task = asyncio.create_task(store.finalize(started["session_id"]))
    await asyncio.sleep(0)
    cancelled_task = asyncio.create_task(store.cancel(started["session_id"]))
    await asyncio.sleep(0)
    store._lock.release()
    finalized, cancelled = await asyncio.gather(finalized_task, cancelled_task)

    assert finalized["status"] == "succeeded"
    assert "_terminal_replay" not in finalized
    assert cancelled["status"] == "failed"
    assert cancelled["retryable"] is True
    assert "can no longer be cancelled" in cancelled["message"]
    assert "_requires_finalize" not in cancelled
    acknowledged = await store.complete(started["session_id"])
    assert acknowledged["status"] == "succeeded"
    assert target.read_bytes() == b"new-session"


@pytest.mark.asyncio
async def test_whatsapp_connect_cancel_wins_over_queued_finalize(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "neonize.db"
    target.write_bytes(b"old-session")
    channel = _FakeChannel(complete=True)
    store = WhatsAppConnectStore()
    monkeypatch.setattr(store, "_build_channel", lambda: (channel, target))
    started = await store.start(force=True)
    assert (await store.poll(started["session_id"]))["status"] == "prepared"

    await store._lock.acquire()
    cancelled_task = asyncio.create_task(store.cancel(started["session_id"]))
    await asyncio.sleep(0)
    finalized_task = asyncio.create_task(store.finalize(started["session_id"]))
    await asyncio.sleep(0)
    store._lock.release()
    cancelled, finalized = await asyncio.gather(cancelled_task, finalized_task)

    assert cancelled["status"] == "cancelled"
    assert "_terminal_replay" not in cancelled
    assert finalized["status"] == "cancelled"
    assert finalized["_terminal_replay"] is True
    assert target.read_bytes() == b"old-session"


@pytest.mark.asyncio
async def test_whatsapp_connect_transient_finalize_failure_can_be_retried(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "neonize.db"
    target.write_bytes(b"old-session")
    channel = _FakeChannel(complete=True)
    store = WhatsAppConnectStore()
    monkeypatch.setattr(store, "_build_channel", lambda: (channel, target))

    attempts = 0
    commit_database = store._commit_database

    def fail_once(pending: Path, destination: Path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("database busy")
        commit_database(pending, destination)

    monkeypatch.setattr(store, "_commit_database", fail_once)
    started = await store.start(force=True)
    pending_path = Path(channel.config.database_path)
    assert (await store.poll(started["session_id"]))["status"] == "prepared"
    store._sessions[started["session_id"]].deadline = 0

    failed = await store.finalize(started["session_id"])
    retry = await store.poll(started["session_id"])

    assert failed["status"] == "failed"
    assert "database busy" in failed["message"]
    assert failed["retryable"] is True
    assert retry["status"] == "prepared"
    assert target.read_bytes() == b"old-session"
    assert pending_path.read_bytes() == b"new-session"

    completed = await store.finalize(started["session_id"])
    assert completed["status"] == "succeeded"
    assert target.read_bytes() == b"new-session"


def test_whatsapp_database_promotion_rolls_back_entire_file_family(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "neonize.db"
    pending = tmp_path / ".neonize.db.session.connect"
    target.write_bytes(b"old-main")
    target.with_name(target.name + "-shm").write_bytes(b"old-shm")
    target.with_name(target.name + "-wal").write_bytes(b"old-wal")
    pending.write_bytes(b"new-main")
    pending.with_name(pending.name + "-wal").write_bytes(b"new-wal")
    real_replace = os.replace

    def fail_during_promotion(source: os.PathLike[str], destination: os.PathLike[str]) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        if (
            source_path == pending.with_name(pending.name + "-wal")
            and destination_path == target.with_name(target.name + "-wal")
        ):
            raise PermissionError("simulated sidecar failure")
        real_replace(source, destination)

    monkeypatch.setattr(
        "nanobot.channels.whatsapp.connect.os.replace",
        fail_during_promotion,
    )

    with pytest.raises(PermissionError, match="simulated sidecar failure"):
        WhatsAppConnectStore._commit_database(pending, target)

    assert target.read_bytes() == b"old-main"
    assert target.with_name(target.name + "-shm").read_bytes() == b"old-shm"
    assert target.with_name(target.name + "-wal").read_bytes() == b"old-wal"
    assert pending.read_bytes() == b"new-main"
    assert pending.with_name(pending.name + "-wal").read_bytes() == b"new-wal"
    assert not any(".backup" in path.name for path in tmp_path.iterdir())


def test_whatsapp_database_incomplete_rollback_preserves_both_generations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "neonize.db"
    pending = tmp_path / ".neonize.db.session.connect"
    target.write_bytes(b"old-main")
    target.with_name(target.name + "-shm").write_bytes(b"old-shm")
    target.with_name(target.name + "-wal").write_bytes(b"old-wal")
    pending.write_bytes(b"new-main")
    pending.with_name(pending.name + "-wal").write_bytes(b"new-wal")
    real_replace = os.replace

    def fail_promotion_and_main_rollback(
        source: os.PathLike[str],
        destination: os.PathLike[str],
    ) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        if source_path == pending.with_name(pending.name + "-wal"):
            raise PermissionError("simulated sidecar promotion failure")
        if source_path == target and destination_path == pending:
            raise PermissionError("simulated main rollback failure")
        real_replace(source, destination)

    monkeypatch.setattr(
        "nanobot.channels.whatsapp.connect.os.replace",
        fail_promotion_and_main_rollback,
    )

    with pytest.raises(WhatsAppDatabaseRecoveryError, match="rollback failed"):
        WhatsAppConnectStore._commit_database(pending, target)

    # Never overwrite the promoted generation when its inverse move failed.
    assert target.read_bytes() == b"new-main"
    main_backups = [
        path
        for path in tmp_path.iterdir()
        if path.name.startswith(".neonize.db.")
        and path.name.endswith(".backup")
    ]
    assert len(main_backups) == 1
    assert main_backups[0].read_bytes() == b"old-main"
    assert pending.with_name(pending.name + "-wal").read_bytes() == b"new-wal"
    assert target.with_name(target.name + "-wal").read_bytes() == b"old-wal"


@pytest.mark.asyncio
async def test_whatsapp_recovery_session_and_artifacts_do_not_expire(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "neonize.db"
    target.write_bytes(b"old-session")
    channel = _FakeChannel(complete=True)
    store = WhatsAppConnectStore()
    monkeypatch.setattr(store, "_build_channel", lambda: (channel, target))
    started = await store.start(force=True)
    pending_path = Path(channel.config.database_path)
    assert (await store.poll(started["session_id"]))["status"] == "prepared"

    def require_recovery(_pending: Path, _target: Path) -> None:
        raise WhatsAppDatabaseRecoveryError("manual database recovery required")

    monkeypatch.setattr(store, "_commit_database", require_recovery)
    failed = await store.finalize(started["session_id"])
    store._sessions[started["session_id"]].deadline = 0
    await store._cleanup()

    assert failed["recovery_required"] is True
    assert failed["restart_blocked"] is True
    assert failed["requires_restart"] is False
    assert started["session_id"] in store._sessions
    assert pending_path.read_bytes() == b"new-session"
    retry = await store.poll(started["session_id"])
    assert retry["recovery_required"] is True
    assert retry["_recovery_required"] is True


def test_whatsapp_database_promotion_removes_stale_target_sidecars(tmp_path: Path) -> None:
    target = tmp_path / "neonize.db"
    pending = tmp_path / ".neonize.db.session.connect"
    target.write_bytes(b"old-main")
    target.with_name(target.name + "-shm").write_bytes(b"old-shm")
    target.with_name(target.name + "-wal").write_bytes(b"old-wal")
    pending.write_bytes(b"new-main")

    WhatsAppConnectStore._commit_database(pending, target)

    assert target.read_bytes() == b"new-main"
    assert not target.with_name(target.name + "-shm").exists()
    assert not target.with_name(target.name + "-wal").exists()
    assert not any(".backup" in path.name for path in tmp_path.iterdir())
