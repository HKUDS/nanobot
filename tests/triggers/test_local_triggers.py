from __future__ import annotations

import asyncio
import errno
import json
import os
from contextlib import suppress
from pathlib import Path

import pytest

from nanobot.agent.automation_turns import AutomationTurnError
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.triggers.local_runner import run_local_trigger_queue
from nanobot.triggers.local_store import LocalTriggerStore, TriggerDisabledError
from nanobot.webui.metadata import WEBUI_MESSAGE_SOURCE_METADATA_KEY, WEBUI_TURN_METADATA_KEY


def _channel_is_enabled(_name: str) -> bool:
    return True


def _write_delivery_file(path: Path, *, trigger_id: str, delivery_id: str) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "delivery": {
                    "id": delivery_id,
                    "triggerId": trigger_id,
                    "content": "queued",
                    "createdAtMs": 1,
                    "attempts": 0,
                    "lastError": None,
                },
            }
        ),
        encoding="utf-8",
    )


def _read_run_record(store: LocalTriggerStore, run_id: str) -> dict:
    return json.loads((store.runs_dir / f"{run_id}.json").read_text(encoding="utf-8"))


def test_trigger_store_allows_multiple_triggers_per_session(tmp_path: Path) -> None:
    store = LocalTriggerStore(tmp_path)

    first = store.create(
        name="PR review",
        channel="websocket",
        chat_id="chat-1",
        session_key="websocket:chat-1",
    )
    second = store.create(
        name="CI summary",
        channel="websocket",
        chat_id="chat-1",
        session_key="websocket:chat-1",
    )

    triggers = store.list_for_session("websocket:chat-1")
    assert {trigger.id for trigger in triggers} == {first.id, second.id}
    assert first.id.startswith("trg_")
    assert second.id.startswith("trg_")
    assert first.id != second.id


def test_trigger_store_atomic_writes_ignore_unsupported_directory_fsync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Shared folders may allow opening directories but reject directory fsync."""
    store = LocalTriggerStore(tmp_path)
    real_open = os.open
    real_close = os.close
    real_fsync = os.fsync
    directory_fds: set[int] = set()

    def fake_open(path: str, flags: int, *args: object, **kwargs: object) -> int:
        fd = real_open(path, flags, *args, **kwargs)
        if Path(path).name in {"triggers", "runs"}:
            directory_fds.add(fd)
        return fd

    def fake_fsync(fd: int) -> None:
        if fd in directory_fds:
            raise OSError(errno.EINVAL, "Invalid argument")
        real_fsync(fd)

    def fake_close(fd: int) -> None:
        directory_fds.discard(fd)
        real_close(fd)

    monkeypatch.setattr(os, "open", fake_open)
    monkeypatch.setattr(os, "close", fake_close)
    monkeypatch.setattr(os, "fsync", fake_fsync)

    trigger = store.create(
        name="Shared folder safe",
        channel="websocket",
        chat_id="chat-1",
        session_key="websocket:chat-1",
    )

    assert store.get(trigger.id) is not None
    delivery = store.enqueue(trigger.id, "queued from shared folder")
    record = _read_run_record(store, delivery.id)
    assert record["content"] == "queued from shared folder"


def test_enqueue_rejects_disabled_trigger(tmp_path: Path) -> None:
    store = LocalTriggerStore(tmp_path)
    trigger = store.create(
        name="Disabled",
        channel="telegram",
        chat_id="123",
        session_key="telegram:123",
    )
    store.enable(trigger.id, enabled=False)

    with pytest.raises(TriggerDisabledError):
        store.enqueue(trigger.id, "Review PR #4502")


def test_enqueue_writes_trigger_run_record(tmp_path: Path) -> None:
    store = LocalTriggerStore(tmp_path)
    trigger = store.create(
        name="PR review",
        channel="websocket",
        chat_id="chat-1",
        session_key="websocket:chat-1",
        origin_metadata={"webui": True},
    )

    delivery = store.enqueue(trigger.id, "Review PR #4591")

    record = _read_run_record(store, delivery.id)
    assert record["run_id"] == delivery.id
    assert record["kind"] == "local_trigger"
    assert record["status"] == "queued"
    assert record["trigger_id"] == trigger.id
    assert record["trigger_name"] == "PR review"
    assert record["delivery_id"] == delivery.id
    assert record["session_key"] == "websocket:chat-1"
    assert record["channel"] == "websocket"
    assert record["chat_id"] == "chat-1"
    assert record["sender_id"] == "trigger"
    assert record["content"] == "Review PR #4591"
    assert record["origin_metadata"] == {"webui": True}
    assert record["updated_at_ms"] > 0


def test_delivery_run_record_truncates_large_content_and_response(tmp_path: Path) -> None:
    store = LocalTriggerStore(tmp_path)
    trigger = store.create(
        name="Large audit",
        channel="websocket",
        chat_id="chat-1",
        session_key="websocket:chat-1",
    )
    large_content = "content-" * 1000
    large_response = "response-" * 1000

    delivery = store.enqueue(trigger.id, large_content)
    queued_record = _read_run_record(store, delivery.id)
    assert queued_record["content"].startswith("content-")
    assert queued_record["content"].endswith("\n... (truncated)")
    assert len(queued_record["content"]) < len(large_content)

    store.write_delivery_run_record(
        delivery,
        trigger=trigger,
        status="ok",
        response=large_response,
    )

    final_record = _read_run_record(store, delivery.id)
    assert final_record["content"].endswith("\n... (truncated)")
    assert final_record["response"].startswith("response-")
    assert final_record["response"].endswith("\n... (truncated)")
    assert len(final_record["response"]) < len(large_response)


def test_delete_removes_delivery_files_for_trigger(tmp_path: Path) -> None:
    store = LocalTriggerStore(tmp_path)
    trigger = store.create(
        name="PR review",
        channel="websocket",
        chat_id="chat-1",
        session_key="websocket:chat-1",
    )
    other = store.create(
        name="CI summary",
        channel="websocket",
        chat_id="chat-2",
        session_key="websocket:chat-2",
    )
    inbox = store.inbox_dir / "1-tdl_inbox.json"
    processing = store.processing_dir / "2-tdl_processing.json"
    failed = store.failed_dir / "3-tdl_failed.json"
    other_inbox = store.inbox_dir / "4-tdl_other.json"
    _write_delivery_file(inbox, trigger_id=trigger.id, delivery_id="tdl_inbox")
    _write_delivery_file(processing, trigger_id=trigger.id, delivery_id="tdl_processing")
    _write_delivery_file(failed, trigger_id=trigger.id, delivery_id="tdl_failed")
    _write_delivery_file(other_inbox, trigger_id=other.id, delivery_id="tdl_other")

    assert store.delete(trigger.id) is True

    assert store.get(trigger.id) is None
    assert not inbox.exists()
    assert not processing.exists()
    assert not failed.exists()
    assert other_inbox.exists()
    assert store.get(other.id) is not None


def test_recover_processing_deliveries_requeues_claimed_delivery(tmp_path: Path) -> None:
    store = LocalTriggerStore(tmp_path)
    trigger = store.create(
        name="PR review",
        channel="websocket",
        chat_id="chat-1",
        session_key="websocket:chat-1",
    )
    store.enqueue(trigger.id, "Review PR #4591")

    claimed = store.claim_deliveries()
    assert len(claimed) == 1
    assert claimed[0].path is not None
    assert claimed[0].path.parent.name == "processing"
    assert LocalTriggerStore(tmp_path).claim_deliveries() == []

    restarted = LocalTriggerStore(tmp_path)
    assert restarted.recover_processing_deliveries() == 1

    reclaimed = restarted.claim_deliveries()
    assert len(reclaimed) == 1
    assert reclaimed[0].trigger_id == trigger.id
    assert reclaimed[0].content == "Review PR #4591"
    assert reclaimed[0].attempts == 1
    assert reclaimed[0].last_error == "delivery was recovered from interrupted processing"


@pytest.mark.asyncio
async def test_local_trigger_queue_submits_bound_inbound_message(tmp_path: Path) -> None:
    store = LocalTriggerStore(tmp_path)
    trigger = store.create(
        name="PR review",
        channel="websocket",
        chat_id="chat-1",
        session_key="websocket:chat-1",
        origin_metadata={"webui": True, WEBUI_TURN_METADATA_KEY: "old-turn"},
    )
    delivery = store.enqueue(trigger.id, "Review PR #4502")
    submitted: list[InboundMessage] = []

    async def _submit_turn(msg: InboundMessage):
        submitted.append(msg)
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content="done")

    task = asyncio.create_task(
        run_local_trigger_queue(
            store=store,
            submit_turn=_submit_turn,
            is_channel_enabled=_channel_is_enabled,
            poll_interval_s=0.01,
        )
    )
    try:
        for _ in range(100):
            if submitted:
                break
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    assert len(submitted) == 1
    msg = submitted[0]
    assert msg.channel == "websocket"
    assert msg.chat_id == "chat-1"
    assert msg.sender_id == "trigger"
    assert msg.content == "Review PR #4502"
    assert msg.session_key_override == "websocket:chat-1"
    assert msg.metadata[WEBUI_TURN_METADATA_KEY].startswith(f"trigger:{trigger.id}:")
    assert msg.metadata[WEBUI_TURN_METADATA_KEY] != "old-turn"
    assert msg.metadata[WEBUI_MESSAGE_SOURCE_METADATA_KEY] == {
        "kind": "local_trigger",
        "label": "PR review",
    }
    assert msg.metadata["_local_trigger"]["trigger_id"] == trigger.id
    assert (
        msg.metadata["_local_trigger"]["persist_content"]
        == "Local trigger received: PR review\n\nReview PR #4502"
    )

    stored = store.get(trigger.id)
    assert stored is not None
    assert stored.last_status == "ok"
    assert stored.last_run_at_ms is not None
    assert store.claim_deliveries() == []
    record = _read_run_record(store, delivery.id)
    assert record["status"] == "ok"
    assert record["response"] == "done"
    assert record["trigger_id"] == trigger.id


@pytest.mark.asyncio
async def test_local_trigger_queue_rejects_unavailable_target_channel(tmp_path: Path) -> None:
    store = LocalTriggerStore(tmp_path)
    trigger = store.create(
        name="PR review",
        channel="telegram",
        chat_id="chat-1",
        session_key="telegram:chat-1",
    )
    delivery = store.enqueue(trigger.id, "Review PR #4502")
    submitted: list[InboundMessage] = []

    async def _submit_turn(msg: InboundMessage):
        submitted.append(msg)
        return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content="done")

    task = asyncio.create_task(
        run_local_trigger_queue(
            store=store,
            submit_turn=_submit_turn,
            is_channel_enabled=lambda name: name == "websocket",
            poll_interval_s=0.01,
        )
    )
    try:
        for _ in range(100):
            stored = store.get(trigger.id)
            if stored and stored.last_status == "error":
                break
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    stored = store.get(trigger.id)
    assert submitted == []
    assert stored is not None
    assert stored.last_status == "error"
    assert stored.last_error == "target channel is not enabled: telegram"
    assert store.claim_deliveries() == []
    record = _read_run_record(store, delivery.id)
    assert record["status"] == "error"
    assert record["error"] == "target channel is not enabled: telegram"


@pytest.mark.asyncio
async def test_local_trigger_queue_waits_for_submitted_turn_before_ack(
    tmp_path: Path,
) -> None:
    store = LocalTriggerStore(tmp_path)
    trigger = store.create(
        name="CI review",
        channel="websocket",
        chat_id="chat-1",
        session_key="websocket:chat-1",
    )
    delivery = store.enqueue(trigger.id, "Review failed CI")
    submitted: list[InboundMessage] = []
    release = asyncio.Event()

    async def _submit_turn(msg: InboundMessage):
        submitted.append(msg)
        await release.wait()
        return None

    task = asyncio.create_task(
        run_local_trigger_queue(
            store=store,
            submit_turn=_submit_turn,
            is_channel_enabled=_channel_is_enabled,
            poll_interval_s=0.01,
        )
    )
    try:
        for _ in range(100):
            if submitted:
                break
            await asyncio.sleep(0.01)

        assert len(submitted) == 1
        assert list(store.processing_dir.glob("*.json"))
        record = _read_run_record(store, delivery.id)
        assert record["status"] == "processing"
        stored = store.get(trigger.id)
        assert stored is not None
        assert stored.last_status is None

        release.set()
        for _ in range(100):
            stored = store.get(trigger.id)
            if stored and stored.last_status == "ok":
                break
            await asyncio.sleep(0.01)

        assert not list(store.processing_dir.glob("*.json"))
        stored = store.get(trigger.id)
        assert stored is not None
        assert stored.last_status == "ok"
        assert store.claim_deliveries() == []
        record = _read_run_record(store, delivery.id)
        assert record["status"] == "ok"
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_local_trigger_queue_requeues_when_submitted_turn_is_interrupted(
    tmp_path: Path,
) -> None:
    store = LocalTriggerStore(tmp_path)
    trigger = store.create(
        name="CI review",
        channel="websocket",
        chat_id="chat-1",
        session_key="websocket:chat-1",
    )
    delivery = store.enqueue(trigger.id, "Review failed CI")
    started = asyncio.Event()

    async def _submit_turn(_msg: InboundMessage):
        started.set()
        await asyncio.Future()

    task = asyncio.create_task(
        run_local_trigger_queue(
            store=store,
            submit_turn=_submit_turn,
            is_channel_enabled=_channel_is_enabled,
            poll_interval_s=0.01,
        )
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

        reclaimed = store.claim_deliveries()
        assert len(reclaimed) == 1
        assert reclaimed[0].trigger_id == trigger.id
        assert reclaimed[0].attempts == 1
        assert reclaimed[0].last_error == "CancelledError"
        record = _read_run_record(store, delivery.id)
        assert record["status"] == "interrupted"
        assert record["attempts"] == 1
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_local_trigger_queue_does_not_retry_completed_agent_failure(
    tmp_path: Path,
) -> None:
    store = LocalTriggerStore(tmp_path)
    trigger = store.create(
        name="CI review",
        channel="websocket",
        chat_id="chat-1",
        session_key="websocket:chat-1",
    )
    delivery = store.enqueue(trigger.id, "Review failed CI")
    started = asyncio.Event()

    async def _submit_turn(_msg: InboundMessage):
        started.set()
        raise AutomationTurnError("model failed")

    task = asyncio.create_task(
        run_local_trigger_queue(
            store=store,
            submit_turn=_submit_turn,
            is_channel_enabled=_channel_is_enabled,
            poll_interval_s=0.01,
        )
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        for _ in range(100):
            stored = store.get(trigger.id)
            if stored and stored.last_status == "error":
                break
            await asyncio.sleep(0.01)

        stored = store.get(trigger.id)
        assert stored is not None
        assert stored.last_status == "error"
        assert stored.last_error == "model failed"
        assert store.claim_deliveries() == []
        assert not list(store.processing_dir.glob("*.json"))
        assert not list(store.failed_dir.glob("*.json"))
        record = _read_run_record(store, delivery.id)
        assert record["status"] == "error"
        assert record["error"] == "model failed"
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_local_trigger_queue_recovers_processing_delivery_on_start(
    tmp_path: Path,
) -> None:
    store = LocalTriggerStore(tmp_path)
    trigger = store.create(
        name="PR review",
        channel="websocket",
        chat_id="chat-1",
        session_key="websocket:chat-1",
    )
    store.enqueue(trigger.id, "Review PR #4591")
    assert len(store.claim_deliveries()) == 1
    submitted: list[InboundMessage] = []

    async def _submit_turn(msg: InboundMessage):
        submitted.append(msg)
        return None

    restarted = LocalTriggerStore(tmp_path)
    task = asyncio.create_task(
        run_local_trigger_queue(
            store=restarted,
            submit_turn=_submit_turn,
            is_channel_enabled=_channel_is_enabled,
            poll_interval_s=0.01,
        )
    )
    try:
        for _ in range(100):
            if submitted:
                break
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    assert len(submitted) == 1
    assert submitted[0].content == "Review PR #4591"
    assert submitted[0].metadata["_local_trigger"]["trigger_id"] == trigger.id
    assert restarted.claim_deliveries() == []
