from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.triggers.local_runner import run_local_trigger_queue
from nanobot.triggers.local_store import LocalTriggerStore, TriggerDisabledError
from nanobot.webui.metadata import WEBUI_MESSAGE_SOURCE_METADATA_KEY, WEBUI_TURN_METADATA_KEY


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
async def test_local_trigger_queue_publishes_bound_inbound_message(tmp_path: Path) -> None:
    store = LocalTriggerStore(tmp_path)
    trigger = store.create(
        name="PR review",
        channel="websocket",
        chat_id="chat-1",
        session_key="websocket:chat-1",
        origin_metadata={"webui": True, WEBUI_TURN_METADATA_KEY: "old-turn"},
    )
    store.enqueue(trigger.id, "Review PR #4502")
    published: list[InboundMessage] = []

    class _Bus:
        async def publish_inbound(self, msg: InboundMessage) -> None:
            published.append(msg)

    task = asyncio.create_task(
        run_local_trigger_queue(store=store, bus=_Bus(), poll_interval_s=0.01)
    )
    try:
        for _ in range(100):
            if published:
                break
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    assert len(published) == 1
    msg = published[0]
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

    stored = store.get(trigger.id)
    assert stored is not None
    assert stored.last_status == "ok"
    assert stored.last_run_at_ms is not None
    assert store.claim_deliveries() == []


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
    store.enqueue(trigger.id, "Review failed CI")
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
    store.enqueue(trigger.id, "Review failed CI")
    started = asyncio.Event()

    async def _submit_turn(_msg: InboundMessage):
        started.set()
        await asyncio.Future()

    task = asyncio.create_task(
        run_local_trigger_queue(
            store=store,
            submit_turn=_submit_turn,
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
    published: list[InboundMessage] = []

    class _Bus:
        async def publish_inbound(self, msg: InboundMessage) -> None:
            published.append(msg)

    restarted = LocalTriggerStore(tmp_path)
    task = asyncio.create_task(
        run_local_trigger_queue(store=restarted, bus=_Bus(), poll_interval_s=0.01)
    )
    try:
        for _ in range(100):
            if published:
                break
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    assert len(published) == 1
    assert published[0].content == "Review PR #4591"
    assert published[0].metadata["_local_trigger"]["trigger_id"] == trigger.id
    assert restarted.claim_deliveries() == []
