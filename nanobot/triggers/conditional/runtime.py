"""ConditionalTriggerRuntime — single asyncio manager for all monitors.

Sits alongside CronService / Heartbeat / LocalTriggerQueue in gateway_runtime.py.

Key invariants:
- One task per monitor, bounded by monitor timeout.
- monitor.evaluate() is pure Python; never wakes LLM unless should_wake.
- Hit path: dedupe + cooldown check → LocalTriggerStore.enqueue() only.
- All I/O isolation: one monitor failure never kills siblings.
- Restart recovery: ConditionalStateStore keeps last_check/trigger/dedupe/cooldown.
- Backoff on consecutive failures, no spam.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from nanobot.triggers.conditional.state import ConditionalStateStore, MonitorStateRecord
from nanobot.triggers.conditional.types import ConditionMonitor, MonitorAuditEvent, TriggerDecision
from nanobot.triggers.local_store import LocalTriggerStore


def _now_ms() -> int:
    return int(time.time() * 1000)


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


class ConditionalTriggerRuntime:
    def __init__(
        self,
        *,
        workspace_path,
        trigger_store: LocalTriggerStore,
        state_store: ConditionalStateStore | None = None,
        monitors: dict[str, ConditionMonitor] | None = None,
    ):
        from pathlib import Path

        self.workspace_path = Path(workspace_path)
        self.trigger_store = trigger_store
        self.state_store = state_store or ConditionalStateStore(self.workspace_path)
        self.monitors: dict[str, ConditionMonitor] = dict(monitors or {})
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._stop = asyncio.Event()
        self._audit_log: list[MonitorAuditEvent] = []
        self._audit_cap = 200

    def set_monitors(self, monitors: dict[str, ConditionMonitor]) -> None:
        self.monitors = dict(monitors)

    def audit_tail(self, limit: int = 50) -> list[MonitorAuditEvent]:
        return list(self._audit_log[-limit:])

    async def run(self) -> None:
        """Entrypoint — mirrors run_local_trigger_queue: never returns until cancelled."""
        logger.info("ConditionalTriggerRuntime started ({} monitors)", len(self.monitors))
        self.state_store.ensure()
        # Recover next_due from durable state so restart does not burst
        # (monitors with no prior state start at now + interval).
        self._stop.clear()
        loop = asyncio.get_running_loop()
        for mid, mon in list(self.monitors.items()):
            if not getattr(mon.config, "enabled", True):
                continue
            self._tasks[mid] = loop.create_task(self._run_monitor(mid, mon), name=f"conditional:{mid}")

        try:
            await self._stop.wait()
        except asyncio.CancelledError:
            pass
        finally:
            for t in list(self._tasks.values()):
                if not t.done():
                    t.cancel()
            if self._tasks:
                await asyncio.gather(*self._tasks.values(), return_exceptions=True)
            logger.info("ConditionalTriggerRuntime stopped")

    def stop(self) -> None:
        self._stop.set()

    async def _run_monitor(self, monitor_id: str, monitor: ConditionMonitor) -> None:
        interval = float(getattr(monitor.config, "interval_s", 2700))
        timeout = float(getattr(monitor.config, "timeout_s", 15))
        max_backoff = float(getattr(monitor.config, "max_backoff_s", 1800))
        initial_backoff = float(getattr(monitor.config, "initial_backoff_s", 30))
        factor = float(getattr(monitor.config, "backoff_factor", 2.0))

        # Stagger start so N monitors don't align on gateway boot
        await asyncio.sleep(min(interval * 0.05, 5.0) * (hash(monitor_id) % 7) / 7.0)

        # Seed next_due from state if present
        state = self.state_store.get(monitor_id)
        if state and state.next_due_at_ms and state.next_due_at_ms > _now_ms():
            delay = max(0, (state.next_due_at_ms - _now_ms()) / 1000.0)
            if delay > 0:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                    return
                except asyncio.TimeoutError:
                    pass

        consecutive_failures = int(state.consecutive_failures) if state else 0

        while not self._stop.is_set():
            tick_start = _now_ms()
            try:
                await self._tick_once(monitor, timeout_s=timeout)
                consecutive_failures = 0
                # persist next_due for restart recovery
                self.state_store.touch_check(
                    monitor_id,
                    now_ms=tick_start,
                    next_due_at_ms=int(tick_start + interval * 1000),
                    reset_failures=True,
                )
                sleep_s = interval
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                consecutive_failures += 1
                err = f"{exc.__class__.__name__}: {exc}"[:1500]
                logger.exception("Conditional monitor {} failed", monitor_id)
                self._emit_audit(MonitorAuditEvent(
                    monitor_id=monitor_id,
                    at_ms=tick_start,
                    should_wake=False,
                    error=err,
                    duration_ms=_now_ms() - tick_start,
                ))
                self.state_store.touch_check(
                    monitor_id,
                    now_ms=tick_start,
                    next_due_at_ms=int(tick_start + min(max_backoff, initial_backoff * (factor ** (consecutive_failures - 1))) * 1000),
                    error=err,
                    increment_failure=True,
                )
                # exponential backoff, capped
                backoff = min(max_backoff, initial_backoff * (factor ** (consecutive_failures - 1)))
                sleep_s = backoff
                if consecutive_failures >= 5:
                    logger.warning("Conditional monitor {} backing off {}s (failures={})", monitor_id, backoff, consecutive_failures)

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=sleep_s)
                return
            except asyncio.TimeoutError:
                continue

    async def _tick_once(self, monitor: ConditionMonitor, *, timeout_s: float) -> None:
        mid = monitor.id
        start = _now_ms()
        now = _now_dt()

        # 1) evaluate under timeout isolation
        try:
            decision = await asyncio.wait_for(monitor.evaluate(now), timeout=timeout_s)
        except asyncio.TimeoutError as e:
            raise TimeoutError(f"monitor {mid} evaluate timed out after {timeout_s}s") from e

        elapsed = _now_ms() - start
        if decision is None or not decision.should_wake:
            reason = (decision.reason if decision else "") or "should_wake=false"
            self._emit_audit(MonitorAuditEvent(
                monitor_id=mid,
                at_ms=start,
                should_wake=False,
                reason=reason,
                evidence=dict(decision.evidence or {}) if decision and decision.evidence else None,
                duration_ms=elapsed,
                skipped_reason="not_triggered",
            ))
            logger.debug("Conditional {} not triggered: {} ({}ms)", mid, reason, elapsed)
            return

        # 2) cooldown / dedupe gate from durable state
        state = self.state_store.get(mid)
        if state and state.cooldown_until_ms and _now_ms() < state.cooldown_until_ms:
            self._emit_audit(MonitorAuditEvent(
                monitor_id=mid,
                at_ms=start,
                should_wake=False,
                trigger_id=decision.trigger_id,
                dedupe_key=decision.dedupe_key,
                reason="cooldown",
                duration_ms=elapsed,
                skipped_reason="cooldown",
            ))
            logger.info("Conditional {} hit but in cooldown until {}", mid, state.cooldown_until_ms)
            return
        if decision.dedupe_key and state and state.last_dedupe_key == decision.dedupe_key:
            self._emit_audit(MonitorAuditEvent(
                monitor_id=mid,
                at_ms=start,
                should_wake=False,
                trigger_id=decision.trigger_id,
                dedupe_key=decision.dedupe_key,
                reason="dedupe",
                duration_ms=elapsed,
                skipped_reason="dedupe",
            ))
            logger.info("Conditional {} hit but deduped key={}", mid, decision.dedupe_key)
            return
        if decision.cooldown_until_ms and decision.cooldown_until_ms <= _now_ms():
            # stale cooldown — ignore
            pass

        # 3) enqueue into local trigger inbox (retryable errors bubble to _run_monitor)
        try:
            delivery = self.trigger_store.enqueue(decision.trigger_id, decision.content)
        except Exception as e:
            # invalid trigger id / disabled — record audit and don't retry enqueue loop
            self._emit_audit(MonitorAuditEvent(
                monitor_id=mid,
                at_ms=start,
                should_wake=True,
                trigger_id=decision.trigger_id,
                dedupe_key=decision.dedupe_key,
                reason=decision.reason,
                evidence=dict(decision.evidence or {}) if decision.evidence else None,
                error=f"enqueue failed: {e}",
                duration_ms=_now_ms() - start,
            ))
            logger.warning("Conditional {} enqueue failed for {}: {}", mid, decision.trigger_id, e)
            return

        # 4) durably record trigger + audit
        self.state_store.record_trigger(
            mid,
            now_ms=_now_ms(),
            dedupe_key=decision.dedupe_key,
            cooldown_until_ms=decision.cooldown_until_ms,
            next_due_at_ms=int(_now_ms() + float(monitor.config.interval_s) * 1000),
        )
        self._emit_audit(MonitorAuditEvent(
            monitor_id=mid,
            at_ms=start,
            should_wake=True,
            trigger_id=decision.trigger_id,
            dedupe_key=decision.dedupe_key,
            reason=decision.reason,
            evidence=dict(decision.evidence or {}) if decision.evidence else None,
            duration_ms=_now_ms() - start,
            enqueued=True,
        ))
        logger.info("Conditional {} → enqueued {} (delivery {})", mid, decision.trigger_id, delivery.id)

    def _emit_audit(self, event: MonitorAuditEvent) -> None:
        self._audit_log.append(event)
        if len(self._audit_log) > self._audit_cap:
            self._audit_log = self._audit_log[-self._audit_cap:]

    # Incremental hot-reload (config change) — caller diffs ids
    def sync_monitors(self, desired: dict[str, ConditionMonitor]) -> None:
        """Incrementally start/stop monitors without restarting runtime."""
        loop = asyncio.get_running_loop()
        to_remove = set(self.monitors.keys()) - set(desired.keys())
        to_add = set(desired.keys()) - set(self.monitors.keys())
        for mid in to_remove:
            t = self._tasks.pop(mid, None)
            if t and not t.done():
                t.cancel()
            self.monitors.pop(mid, None)
            logger.info("Conditional runtime removed monitor {}", mid)
        for mid in to_add:
            mon = desired[mid]
            self.monitors[mid] = mon
            if getattr(mon.config, "enabled", True):
                self._tasks[mid] = loop.create_task(self._run_monitor(mid, mon), name=f"conditional:{mid}")
                logger.info("Conditional runtime added monitor {}", mid)
