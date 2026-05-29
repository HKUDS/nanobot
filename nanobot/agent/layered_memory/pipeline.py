"""L1→L2→L3 pipeline scheduler (LM2-B skeleton; L1 extract in LM2-C)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from loguru import logger

from nanobot.config.schema import LayeredMemoryConfig, LayeredMemoryPipelineConfig

L1JobHandler = Callable[..., Awaitable[None]]
L2JobHandler = Callable[..., Awaitable[None]]


class PipelineTriggerReason(str, Enum):
    THRESHOLD = "threshold"
    IDLE = "idle"
    SHUTDOWN = "shutdown"


class L2TriggerReason(str, Enum):
    AFTER_L1 = "after_l1"
    SHUTDOWN = "shutdown"


@dataclass
class L1TriggerEvent:
    session_key: str
    reason: PipelineTriggerReason
    turn_ids: tuple[str, ...]
    chunk: int


@dataclass
class _SessionPipelineState:
    turns_since_last_l1: int = 0
    warmup_stage: int = 0
    current_threshold: int = 1
    pending_turn_ids: list[str] = field(default_factory=list)
    last_activity: float = field(default_factory=time.monotonic)
    idle_task: asyncio.Task[None] | None = None
    l2_timer: asyncio.Task[None] | None = None
    l2_scheduled_at: float = 0.0
    l2_pending: bool = False
    last_l2_at: float = 0.0


def warmup_threshold(*, warmup_stage: int, every_n: int, enable_warmup: bool) -> int:
    """Next L1 trigger after ``warmup_stage`` prior threshold fires (1→2→4→…→every_n)."""
    if not enable_warmup:
        return every_n
    return min(max(1, 1 << warmup_stage), every_n)


class SerialQueue:
    """Run async jobs one at a time (L1 extraction must not overlap)."""

    __slots__ = ("_lock",)

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    async def run(self, coro: Awaitable[None]) -> None:
        async with self._lock:
            await coro


class MemoryPipelineManager:
    """Buffer turn captures and schedule L1 jobs by threshold or idle timeout."""

    __slots__ = (
        "_config",
        "_l1_handler",
        "_l2_handler",
        "_pipeline_cfg",
        "_queue",
        "_sessions",
    )

    def __init__(
        self,
        config: LayeredMemoryConfig,
        *,
        l1_handler: L1JobHandler | None = None,
        l2_handler: L2JobHandler | None = None,
    ) -> None:
        self._config = config
        self._pipeline_cfg = config.pipeline
        self._sessions: dict[str, _SessionPipelineState] = {}
        self._queue = SerialQueue()
        self._l1_handler = l1_handler or self._default_l1_handler
        self._l2_handler = l2_handler or self._default_l2_handler

    @property
    def pipeline_config(self) -> LayeredMemoryPipelineConfig:
        return self._pipeline_cfg

    def enabled(self, *, is_subagent: bool = False) -> bool:
        return self._config.capture_enabled(is_subagent=is_subagent)

    async def notify_turn(
        self,
        session_key: str,
        *,
        turn_id: str | None = None,
        is_subagent: bool = False,
    ) -> None:
        """Called after a successful L0 capture for one user turn."""
        if not self.enabled(is_subagent=is_subagent):
            return
        state = self._session_state(session_key)
        state.last_activity = time.monotonic()
        if turn_id:
            state.pending_turn_ids.append(turn_id)
        state.turns_since_last_l1 += 1
        self._reschedule_idle_timer(session_key, state)

        if state.turns_since_last_l1 >= state.current_threshold:
            await self._trigger_l1(
                session_key,
                state,
                reason=PipelineTriggerReason.THRESHOLD,
            )

    async def flush_session(
        self,
        session_key: str,
        *,
        reason: PipelineTriggerReason = PipelineTriggerReason.SHUTDOWN,
    ) -> None:
        """Flush pending turns for one session (graceful shutdown)."""
        state = self._sessions.get(session_key)
        if state is None or state.turns_since_last_l1 <= 0:
            return
        await self._trigger_l1(session_key, state, reason=reason)

    async def flush_all(
        self,
        *,
        reason: PipelineTriggerReason = PipelineTriggerReason.SHUTDOWN,
    ) -> None:
        for session_key in list(self._sessions):
            await self.flush_session(session_key, reason=reason)

    async def close(self) -> None:
        """Cancel idle timers and flush pending buffered turns."""
        for session_key, state in list(self._sessions.items()):
            self._cancel_idle_task(state)
            self._cancel_l2_timer(state)
            if state.l2_pending:
                await self._queue.run(
                    self._run_l2_job(session_key, reason=L2TriggerReason.SHUTDOWN),
                )
        await self.flush_all(reason=PipelineTriggerReason.SHUTDOWN)
        self._sessions.clear()

    def session_turns_pending(self, session_key: str) -> int:
        state = self._sessions.get(session_key)
        return state.turns_since_last_l1 if state is not None else 0

    def session_threshold(self, session_key: str) -> int | None:
        state = self._sessions.get(session_key)
        return state.current_threshold if state is not None else None

    def _session_state(self, session_key: str) -> _SessionPipelineState:
        state = self._sessions.get(session_key)
        if state is not None:
            return state
        cfg = self._pipeline_cfg
        initial = warmup_threshold(
            warmup_stage=0,
            every_n=cfg.every_n_conversations,
            enable_warmup=cfg.enable_warmup,
        )
        state = _SessionPipelineState(current_threshold=initial)
        self._sessions[session_key] = state
        return state

    async def _trigger_l1(
        self,
        session_key: str,
        state: _SessionPipelineState,
        *,
        reason: PipelineTriggerReason,
    ) -> None:
        if state.turns_since_last_l1 <= 0:
            return
        turn_ids = tuple(state.pending_turn_ids)
        chunk = state.turns_since_last_l1
        event = L1TriggerEvent(
            session_key=session_key,
            reason=reason,
            turn_ids=turn_ids,
            chunk=chunk,
        )
        state.turns_since_last_l1 = 0
        state.pending_turn_ids.clear()
        state.warmup_stage += 1
        state.current_threshold = warmup_threshold(
            warmup_stage=state.warmup_stage,
            every_n=self._pipeline_cfg.every_n_conversations,
            enable_warmup=self._pipeline_cfg.enable_warmup,
        )
        self._cancel_idle_task(state)
        logger.info(
            "layered_memory l1_trigger reason={} session={} chunk={}",
            reason.value,
            session_key,
            chunk,
        )
        await self._queue.run(self._run_l1_job(event))

    async def _run_l1_job(self, event: L1TriggerEvent) -> None:
        try:
            await self._l1_handler(
                event.session_key,
                reason=event.reason,
                turn_ids=event.turn_ids,
                chunk=event.chunk,
            )
            self._schedule_l2_after_l1(event.session_key)
        except Exception:
            logger.exception(
                "layered_memory l1_job failed session={} reason={}",
                event.session_key,
                event.reason.value,
            )

    def _schedule_l2_after_l1(self, session_key: str) -> None:
        cfg = self._pipeline_cfg
        if cfg.l2_delay_after_l1_seconds < 0:
            return
        state = self._sessions.get(session_key)
        if state is None:
            return

        now = time.monotonic()
        fire_at = now + cfg.l2_delay_after_l1_seconds
        if state.last_l2_at > 0:
            since_last = now - state.last_l2_at
            if since_last >= cfg.l2_max_interval_seconds:
                fire_at = now
            else:
                min_next = state.last_l2_at + cfg.l2_min_interval_seconds
                if min_next > fire_at:
                    fire_at = min_next

        if state.l2_scheduled_at > 0 and fire_at > state.l2_scheduled_at:
            return

        state.l2_scheduled_at = fire_at
        state.l2_pending = True
        self._cancel_l2_timer(state)

        async def _l2_fire() -> None:
            delay = max(0.0, fire_at - time.monotonic())
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                return
            current = self._sessions.get(session_key)
            if current is None or current is not state:
                return
            active_window = cfg.session_active_window_hours * 3600
            if time.monotonic() - state.last_activity > active_window:
                logger.debug("layered_memory l2_skip_cold session={}", session_key)
                state.l2_pending = False
                state.l2_scheduled_at = 0.0
                return
            state.l2_scheduled_at = 0.0
            await self._queue.run(
                self._run_l2_job(session_key, reason=L2TriggerReason.AFTER_L1),
            )

        state.l2_timer = asyncio.create_task(_l2_fire())
        logger.debug(
            "layered_memory l2_scheduled session={} fire_in_s={:.1f}",
            session_key,
            max(0.0, fire_at - now),
        )

    async def _run_l2_job(self, session_key: str, *, reason: L2TriggerReason) -> None:
        state = self._sessions.get(session_key)
        try:
            await self._l2_handler(session_key, reason=reason)
        except Exception:
            logger.exception(
                "layered_memory l2_job failed session={} reason={}",
                session_key,
                reason.value,
            )
        else:
            if state is not None:
                state.last_l2_at = time.monotonic()
                state.l2_pending = False

    async def _default_l1_handler(
        self,
        session_key: str,
        *,
        reason: PipelineTriggerReason,
        turn_ids: tuple[str, ...],
        chunk: int,
    ) -> None:
        """LM2-C replaces this with real L1 extraction."""
        logger.debug(
            "layered_memory l1_job_stub session={} reason={} chunk={} turns={}",
            session_key,
            reason.value,
            chunk,
            len(turn_ids),
        )

    async def _default_l2_handler(
        self,
        session_key: str,
        *,
        reason: L2TriggerReason,
    ) -> None:
        """LM3-A replaces this with real L2 scene extraction."""
        logger.debug(
            "layered_memory l2_job_stub session={} reason={}",
            session_key,
            reason.value,
        )

    def _reschedule_idle_timer(self, session_key: str, state: _SessionPipelineState) -> None:
        timeout = self._pipeline_cfg.l1_idle_timeout_seconds
        if timeout <= 0:
            return
        self._cancel_idle_task(state)

        async def _idle_fire() -> None:
            try:
                await asyncio.sleep(timeout)
            except asyncio.CancelledError:
                return
            current = self._sessions.get(session_key)
            if current is None or current is not state:
                return
            if state.turns_since_last_l1 <= 0:
                return
            await self._trigger_l1(
                session_key,
                state,
                reason=PipelineTriggerReason.IDLE,
            )

        state.idle_task = asyncio.create_task(_idle_fire())

    @staticmethod
    def _cancel_idle_task(state: _SessionPipelineState) -> None:
        task = state.idle_task
        if task is not None and not task.done():
            task.cancel()
        state.idle_task = None

    @staticmethod
    def _cancel_l2_timer(state: _SessionPipelineState) -> None:
        task = state.l2_timer
        if task is not None and not task.done():
            task.cancel()
        state.l2_timer = None
