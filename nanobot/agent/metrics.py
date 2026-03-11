"""In-memory metrics collector with periodic disk flush.

Replaces the read-modify-write-every-call pattern in MemoryStore with
an in-memory ``Counter`` that flushes to ``metrics.json`` periodically
(every *flush_interval_s* seconds) or on explicit ``flush()`` / ``close()``.

Thread/async-safe via ``asyncio.Lock``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from loguru import logger


class MetricsCollector:
    """Accumulates metric deltas in memory, writes to disk in batches."""

    def __init__(
        self,
        metrics_file: Path,
        *,
        flush_interval_s: float = 60.0,
        defaults: dict[str, Any] | None = None,
    ) -> None:
        self._path = metrics_file
        self._flush_interval = flush_interval_s
        self._defaults = defaults or {}
        self._counters: dict[str, int | float | str] = {}
        self._dirty = False
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._loaded = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background flush loop (call from an async context)."""
        if self._task is None or self._task.done():
            self._task = asyncio.ensure_future(self._flush_loop())

    async def close(self) -> None:
        """Flush and stop the background loop."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.flush()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(self, key: str, delta: int = 1) -> None:
        """Increment a counter by *delta* (in-memory only)."""
        self._ensure_loaded()
        self._counters[key] = int(self._counters.get(key, 0)) + int(delta)
        self._dirty = True

    def record_many(self, deltas: dict[str, int]) -> None:
        """Increment multiple counters at once."""
        self._ensure_loaded()
        for key, delta in deltas.items():
            self._counters[key] = int(self._counters.get(key, 0)) + int(delta)
        self._dirty = True

    def set_fields(self, fields: dict[str, Any]) -> None:
        """Set arbitrary key-value pairs (overwrites, not increments)."""
        self._ensure_loaded()
        self._counters.update(fields)
        self._dirty = True

    def set_max(self, key: str, value: int | float) -> None:
        """Set *key* to *value* only if it exceeds the current value."""
        self._ensure_loaded()
        current = self._counters.get(key, 0)
        if isinstance(current, (int, float)) and value > current:
            self._counters[key] = value
            self._dirty = True

    def get(self, key: str, default: Any = 0) -> Any:
        """Read a single metric value."""
        self._ensure_loaded()
        return self._counters.get(key, default)

    def snapshot(self) -> dict[str, Any]:
        """Return a copy of all current metrics."""
        self._ensure_loaded()
        return dict(self._counters)

    async def flush(self) -> None:
        """Write accumulated metrics to disk if dirty."""
        async with self._lock:
            if not self._dirty:
                return
            self._counters["last_updated"] = _utc_now_iso()
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self._path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self._counters, indent=2, default=str))
                tmp.replace(self._path)
                self._dirty = False
            except OSError as exc:
                logger.warning("Failed to flush metrics to {}: {}", self._path, exc)

    def flush_sync(self) -> None:
        """Synchronous flush — for use in non-async shutdown hooks."""
        if not self._dirty:
            return
        self._counters["last_updated"] = _utc_now_iso()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._counters, indent=2, default=str))
            tmp.replace(self._path)
            self._dirty = False
        except OSError as exc:
            logger.warning("Failed to flush metrics to {}: {}", self._path, exc)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        """Lazy-load from disk on first access."""
        if self._loaded:
            return
        data: dict[str, Any] = {}
        if self._path.exists():
            try:
                raw = self._path.read_text(encoding="utf-8")
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    data = parsed
            except (json.JSONDecodeError, OSError):
                logger.warning("Failed to parse metrics file, starting fresh")
        # Merge defaults for any missing keys
        merged = {**self._defaults, **data}
        self._counters = merged
        self._loaded = True

    async def _flush_loop(self) -> None:
        """Background loop that flushes every *flush_interval_s* seconds."""
        try:
            while True:
                await asyncio.sleep(self._flush_interval)
                await self.flush()
        except asyncio.CancelledError:
            return


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------
# Routing metric key constants
# ------------------------------------------------------------------

ROUTING_CLASSIFICATIONS = "routing_classifications"
ROUTING_DELEGATIONS = "routing_delegations"
ROUTING_CYCLES_BLOCKED = "routing_cycles_blocked"
ROUTING_CLASSIFY_LATENCY_SUM_MS = "routing_classify_latency_sum_ms"
ROUTING_CLASSIFY_LATENCY_MAX_MS = "routing_classify_latency_max_ms"
DELEGATION_LATENCY_SUM_MS = "delegation_latency_sum_ms"
DELEGATION_LATENCY_MAX_MS = "delegation_latency_max_ms"


def role_invocations_key(role_name: str) -> str:
    """Return the metric key for per-role invocation count."""
    return f"role_invocations:{role_name}"


def role_tool_calls_key(role_name: str) -> str:
    """Return the metric key for per-role tool-call count."""
    return f"role_tool_calls:{role_name}"
