from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.triggers.runner import run_external_trigger_queue
from nanobot.triggers.store import ExternalTriggerStore, TriggerDisabledError
from nanobot.webui.metadata import WEBUI_MESSAGE_SOURCE_METADATA_KEY, WEBUI_TURN_METADATA_KEY


def test_trigger_store_allows_multiple_triggers_per_session(tmp_path: Path) -> None:
    store = ExternalTriggerStore(tmp_path)

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
    store = ExternalTriggerStore(tmp_path)
    trigger = store.create(
        name="Disabled",
        channel="telegram",
        chat_id="123",
        session_key="telegram:123",
    )
    store.enable(trigger.id, enabled=False)

    with pytest.raises(TriggerDisabledError):
        store.enqueue(trigger.id, "Review PR #4502")


@pytest.mark.asyncio
async def test_external_trigger_queue_publishes_bound_inbound_message(tmp_path: Path) -> None:
    store = ExternalTriggerStore(tmp_path)
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
        run_external_trigger_queue(store=store, bus=_Bus(), poll_interval_s=0.01)
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
        "kind": "trigger",
        "label": "PR review",
    }
    assert msg.metadata["_external_trigger"]["trigger_id"] == trigger.id

    stored = store.get(trigger.id)
    assert stored is not None
    assert stored.last_status == "ok"
    assert stored.last_run_at_ms is not None
    assert store.claim_deliveries() == []
