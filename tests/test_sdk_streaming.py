"""Tests for SDK streaming primitives."""

import asyncio

import pytest

from nanobot.sdk.streaming import SDKStreamEmitter
from nanobot.sdk.types import STREAM_EVENT_TEXT_DELTA, StreamEvent


@pytest.mark.asyncio
async def test_close_preserves_events_when_queue_is_full():
    queue: asyncio.Queue[StreamEvent | object] = asyncio.Queue(maxsize=1)
    emitter = SDKStreamEmitter(queue)
    event = StreamEvent(type=STREAM_EVENT_TEXT_DELTA, delta="kept")
    await emitter.emit(event)

    close_task = asyncio.create_task(emitter.close())
    await asyncio.sleep(0)

    assert not close_task.done()
    assert queue.get_nowait() is event
    await close_task
    assert queue.qsize() == 1
