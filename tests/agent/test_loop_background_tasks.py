from __future__ import annotations

import asyncio
import gc
from contextlib import suppress

import pytest
from loguru import logger


@pytest.mark.asyncio
async def test_background_success_removed_without_error_log(
    loop_factory,
) -> None:
    loop = loop_factory(patch_deps=True)
    records: list[str] = []
    sink_id = logger.add(records.append, level="ERROR")
    try:
        loop.schedule_background(asyncio.sleep(0))
        await asyncio.sleep(0.2)
        assert not loop._background_tasks
        assert records == []
    finally:
        logger.remove(sink_id)


@pytest.mark.asyncio
async def test_background_failure_retrieved_and_logged(
    loop_factory,
) -> None:
    loop = loop_factory(patch_deps=True)
    running = asyncio.get_running_loop()
    loop_errors: list[str] = []
    old_handler = running.get_exception_handler()
    running.set_exception_handler(
        lambda _loop, ctx: loop_errors.append(str(ctx.get("message")))
    )
    records: list[str] = []
    sink_id = logger.add(records.append, level="ERROR")
    try:
        async def boom() -> None:
            raise RuntimeError("background failure")

        loop.schedule_background(boom())
        await asyncio.sleep(0.2)
        gc.collect()
        await asyncio.sleep(0.2)
        assert not loop._background_tasks
        assert loop_errors == []
        assert any("background task" in r and "failed" in r for r in records)
    finally:
        logger.remove(sink_id)
        running.set_exception_handler(old_handler)


@pytest.mark.asyncio
async def test_background_cancelled_removed_silently(
    loop_factory,
) -> None:
    loop = loop_factory(patch_deps=True)
    records: list[str] = []
    sink_id = logger.add(records.append, level="ERROR")
    try:
        loop.schedule_background(asyncio.sleep(60))
        (task,) = tuple(loop._background_tasks)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.2)
        assert not loop._background_tasks
        assert records == []
    finally:
        logger.remove(sink_id)
