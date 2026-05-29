"""Structured observability helpers for layered memory (design §10)."""

from __future__ import annotations

from loguru import logger

from nanobot.config.schema import LayeredMemoryConfig


def log_layered_memory_startup(config: LayeredMemoryConfig) -> None:
    if not config.enable:
        return
    logger.info(
        "layered_memory enabled offload={} capture={} recall={} pipeline_every_n={}",
        config.offload.enable,
        config.capture.enable,
        config.recall.enable,
        config.pipeline.every_n_conversations,
    )


def log_recall_result(
    *,
    session_key: str,
    strategy: str,
    hits: int,
    elapsed_ms: int,
    chars: int = 0,
) -> None:
    logger.info(
        "layered_memory recall session={} strategy={} hits={} ms={} chars={}",
        session_key,
        strategy,
        hits,
        elapsed_ms,
        chars,
    )


def log_recall_timeout(*, session_key: str, strategy: str, timeout_ms: int) -> None:
    logger.warning(
        "layered_memory recall timeout session={} strategy={} timeout_ms={}",
        session_key,
        strategy,
        timeout_ms,
    )
