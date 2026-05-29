"""Lightweight runtime health state for gateway pipeline checks."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

_DEFAULT_STATE_PATH = "/tmp/nanobot-runtime-health.json"


def _env_path(name: str, default: str) -> Path:
    return Path(os.getenv(name, default)).expanduser()


class RuntimeHealthState:
    """Track gateway pipeline liveness without doing work in the healthcheck."""

    def __init__(self, path: Path | None = None, *, min_write_interval_s: float = 5.0) -> None:
        self.path = path or _env_path("NANOBOT_RUNTIME_HEALTH_PATH", _DEFAULT_STATE_PATH)
        self._min_write_interval_s = min_write_interval_s
        self._last_write = 0.0
        self._active_dispatches: dict[str, float] = {}
        self._state: dict[str, Any] = {
            "status": "starting",
            "pid": os.getpid(),
            "active_dispatches": 0,
            "outbound_active": 0,
            "inbound_queue": 0,
            "outbound_queue": 0,
        }

    def mark_gateway_starting(self) -> None:
        self._update(status="starting", force=True)

    def mark_agent_tick(self, *, inbound_queue: int, outbound_queue: int) -> None:
        self._update(
            status="ok",
            last_agent_tick=time.time(),
            inbound_queue=inbound_queue,
            outbound_queue=outbound_queue,
        )

    def mark_inbound_received(self, *, inbound_queue: int, outbound_queue: int) -> None:
        now = time.time()
        self._update(
            status="ok",
            last_agent_tick=now,
            last_inbound_at=now,
            inbound_queue=inbound_queue,
            outbound_queue=outbound_queue,
            force=True,
        )

    def mark_dispatch_start(self, dispatch_id: str) -> None:
        self._active_dispatches[dispatch_id] = time.time()
        self._write_dispatch_state(force=True)

    def mark_dispatch_end(self, dispatch_id: str) -> None:
        self._active_dispatches.pop(dispatch_id, None)
        self._write_dispatch_state(force=True)

    def mark_outbound_send_start(self, *, channel: str) -> None:
        self._update(
            status="ok",
            outbound_active=1,
            outbound_channel=channel,
            outbound_send_started_at=time.time(),
            force=True,
        )

    def mark_outbound_send_ok(self, *, channel: str) -> None:
        self._update(
            status="ok",
            outbound_active=0,
            last_outbound_ok_at=time.time(),
            outbound_channel=channel,
            last_outbound_error="",
            force=True,
        )

    def mark_outbound_send_error(self, *, channel: str, error: str) -> None:
        self._update(
            status="error",
            outbound_active=0,
            outbound_channel=channel,
            last_outbound_error=error,
            last_outbound_error_at=time.time(),
            force=True,
        )

    def _write_dispatch_state(self, *, force: bool) -> None:
        oldest = min(self._active_dispatches.values()) if self._active_dispatches else None
        self._update(
            status="ok",
            active_dispatches=len(self._active_dispatches),
            oldest_dispatch_started_at=oldest,
            force=force,
        )

    def _update(self, *, force: bool = False, **values: Any) -> None:
        now = time.time()
        self._state.update(values)
        self._state["updated_at"] = now
        self._state["pid"] = os.getpid()
        if force or now - self._last_write >= self._min_write_interval_s:
            self._write()
            self._last_write = now

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=self.path.parent,
            text=True,
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._state, f, ensure_ascii=False, indent=2, sort_keys=True)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.path)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise
