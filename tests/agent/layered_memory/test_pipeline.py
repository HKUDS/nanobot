"""Tests for MemoryPipelineManager (LM2-B)."""

from __future__ import annotations

import asyncio

import pytest

from nanobot.agent.layered_memory.pipeline import (
    MemoryPipelineManager,
    PipelineTriggerReason,
    SerialQueue,
    warmup_threshold,
)
from nanobot.config.schema import LayeredMemoryCaptureConfig, LayeredMemoryConfig


@pytest.fixture
def pipeline_cfg() -> LayeredMemoryConfig:
    return LayeredMemoryConfig(
        enable=True,
        capture=LayeredMemoryCaptureConfig(enable=True),
    )


def test_warmup_threshold_sequence() -> None:
    every_n = 5
    assert warmup_threshold(warmup_stage=0, every_n=every_n, enable_warmup=True) == 1
    assert warmup_threshold(warmup_stage=1, every_n=every_n, enable_warmup=True) == 2
    assert warmup_threshold(warmup_stage=2, every_n=every_n, enable_warmup=True) == 4
    assert warmup_threshold(warmup_stage=3, every_n=every_n, enable_warmup=True) == 5
    assert warmup_threshold(warmup_stage=4, every_n=every_n, enable_warmup=True) == 5
    assert warmup_threshold(warmup_stage=0, every_n=every_n, enable_warmup=False) == 5


@pytest.mark.asyncio
async def test_warmup_triggers_at_1_2_4(pipeline_cfg: LayeredMemoryConfig) -> None:
    pipeline_cfg.pipeline.every_n_conversations = 5
    pipeline_cfg.pipeline.enable_warmup = True
    events: list[tuple[str, PipelineTriggerReason, int]] = []

    async def handler(
        session_key: str,
        *,
        reason: PipelineTriggerReason,
        turn_ids: tuple[str, ...],
        chunk: int,
    ) -> None:
        events.append((session_key, reason, chunk))

    mgr = MemoryPipelineManager(pipeline_cfg, l1_handler=handler)
    for i in range(1, 8):
        await mgr.notify_turn("cli:direct", turn_id=f"t{i}")
    assert [chunk for _, reason, chunk in events if reason == PipelineTriggerReason.THRESHOLD] == [
        1,
        2,
        4,
    ]
    assert mgr.session_threshold("cli:direct") == 5


@pytest.mark.asyncio
async def test_every_n_without_warmup(pipeline_cfg: LayeredMemoryConfig) -> None:
    pipeline_cfg.pipeline.every_n_conversations = 3
    pipeline_cfg.pipeline.enable_warmup = False
    chunks: list[int] = []

    async def handler(
        session_key: str,
        *,
        reason: PipelineTriggerReason,
        turn_ids: tuple[str, ...],
        chunk: int,
    ) -> None:
        chunks.append(chunk)

    mgr = MemoryPipelineManager(pipeline_cfg, l1_handler=handler)
    for i in range(6):
        await mgr.notify_turn("sess", turn_id=f"turn-{i}")
    assert chunks == [3, 3]


@pytest.mark.asyncio
async def test_idle_timeout_triggers(pipeline_cfg: LayeredMemoryConfig) -> None:
    pipeline_cfg.pipeline.every_n_conversations = 100
    pipeline_cfg.pipeline.enable_warmup = False
    pipeline_cfg.pipeline.l1_idle_timeout_seconds = 0.05
    reasons: list[PipelineTriggerReason] = []

    async def handler(
        session_key: str,
        *,
        reason: PipelineTriggerReason,
        turn_ids: tuple[str, ...],
        chunk: int,
    ) -> None:
        reasons.append(reason)

    mgr = MemoryPipelineManager(pipeline_cfg, l1_handler=handler)
    await mgr.notify_turn("idle:sess", turn_id="only-one")
    await asyncio.sleep(0.08)
    assert PipelineTriggerReason.IDLE in reasons


@pytest.mark.asyncio
async def test_serial_queue_runs_jobs_in_order() -> None:
    queue = SerialQueue()
    order: list[int] = []

    async def job(n: int, delay: float) -> None:
        order.append(n)
        await asyncio.sleep(delay)
        order.append(n + 100)

    await asyncio.gather(
        queue.run(job(1, 0.03)),
        queue.run(job(2, 0.01)),
    )
    assert order == [1, 101, 2, 102]


@pytest.mark.asyncio
async def test_flush_all_on_shutdown(pipeline_cfg: LayeredMemoryConfig) -> None:
    pipeline_cfg.pipeline.every_n_conversations = 10
    pipeline_cfg.pipeline.enable_warmup = False
    reasons: list[PipelineTriggerReason] = []

    async def handler(
        session_key: str,
        *,
        reason: PipelineTriggerReason,
        turn_ids: tuple[str, ...],
        chunk: int,
    ) -> None:
        reasons.append(reason)

    mgr = MemoryPipelineManager(pipeline_cfg, l1_handler=handler)
    await mgr.notify_turn("sess", turn_id="t1")
    await mgr.notify_turn("sess", turn_id="t2")
    await mgr.close()
    assert PipelineTriggerReason.SHUTDOWN in reasons


@pytest.mark.asyncio
async def test_notify_noop_when_capture_disabled() -> None:
    cfg = LayeredMemoryConfig(enable=True, capture=LayeredMemoryCaptureConfig(enable=False))
    called = False

    async def handler(
        session_key: str,
        *,
        reason: PipelineTriggerReason,
        turn_ids: tuple[str, ...],
        chunk: int,
    ) -> None:
        nonlocal called
        called = True

    mgr = MemoryPipelineManager(cfg, l1_handler=handler)
    await mgr.notify_turn("sess", turn_id="t1")
    assert called is False
