"""ScriptSignalMonitor — generic signal-file watcher.

External detection scripts (market data, health checks, digests, etc., pure
Python, 0 token) run on their own schedule and write a JSON signal file to
{workspace}/signals/pending/ when their condition matches.  This monitor
scans the pending directory on each tick, validates the payload, and wakes
the LLM via LocalTriggerStore → run_local_trigger_queue → agent turn.

Signal file schema (JSON, UTF-8):
    {
      "id": "unique-signal-id",        # required, unique
      "trigger_id": "trg_XXXXXXXX",    # required, must exist and be enabled
      "content": "full message for the LLM",  # required, non-empty
      "dedupe_key": "optional",        # optional, prevents duplicates
      "cooldown_s": 3600,              # optional, cooldown seconds after hit
      "source": "market-monitor",     # optional, for auditing
      "created_at": 1787316222         # optional, epoch seconds (defaults to file mtime)
    }

Directory semantics:
    pending/    to be processed (external scripts only write here)
    processed/  successfully enqueued into the trigger inbox
    failed/     validation failures (bad JSON / missing fields / trigger missing)
    expired/    older than max_age_s (prevent stale signals from triggering)

Design constraints (aligned with the ConditionMonitor protocol):
- evaluate() is pure Python with no network I/O; zero LLM cost when not waking.
- At most one signal is consumed per tick (oldest first); interval_s controls throughput.
- Bad files are moved to failed/ immediately and never retried; transient
errors stay in pending for the next tick.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nanobot.triggers.conditional.types import MonitorConfig, TriggerDecision


class ScriptSignalMonitor:
    """Scan {workspace}/signals/pending/*.json and wake on match."""

    id = "script_signal"
    name = "Script signal watcher"

    def __init__(
        self,
        workspace_path: Path,
        *,
        interval_s: float = 60.0,
        timeout_s: float = 10.0,
        max_age_s: float = 21600.0,
        enabled: bool = True,
    ):
        self.workspace_path = Path(workspace_path)
        self.config = MonitorConfig(
            interval_s=interval_s,
            timeout_s=timeout_s,
            enabled=enabled,
        )
        self.max_age_s = float(max_age_s)

    # ---------- paths ----------

    @property
    def _dir_pending(self) -> Path:
        return self.workspace_path / "signals" / "pending"

    @property
    def _dir_processed(self) -> Path:
        return self.workspace_path / "signals" / "processed"

    @property
    def _dir_failed(self) -> Path:
        return self.workspace_path / "signals" / "failed"

    @property
    def _dir_expired(self) -> Path:
        return self.workspace_path / "signals" / "expired"

    def _ensure_dirs(self) -> None:
        for d in (self._dir_pending, self._dir_processed, self._dir_failed, self._dir_expired):
            d.mkdir(parents=True, exist_ok=True)

    # ---------- helpers ----------

    def _move(self, src: Path, dest_dir: Path, tag: str) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{int(time.time())}-{tag}-{src.name}"
        try:
            os.replace(src, dest)
        except OSError:
            dest = dest_dir / f"{int(time.time()*1000)}-{src.name}"
            os.replace(src, dest)
        return dest

    def _load_trigger(self, trigger_id: str) -> dict[str, Any] | None:
        """Read-only check that the trigger exists and is enabled (camelCase store)."""
        path = self.workspace_path / "triggers" / "triggers.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        items = data if isinstance(data, list) else data.get("triggers") or []
        for t in items:
            if isinstance(t, dict) and t.get("id") == trigger_id:
                return t
        return None

    # ---------- evaluate ----------

    async def evaluate(self, now: datetime) -> TriggerDecision | None:
        try:
            self._ensure_dirs()
            files = sorted(self._dir_pending.glob("*.json"), key=lambda p: p.stat().st_mtime)
        except Exception as e:
            return TriggerDecision(should_wake=False, reason=f"scan_failed: {e}")

        now_ts = time.time()
        for f in files:
            # ---- stale signal → expired ----
            try:
                age = now_ts - f.stat().st_mtime
            except OSError:
                continue
            if age > self.max_age_s:
                try:
                    self._move(f, self._dir_expired, "expired")
                except OSError:
                    pass
                continue

            # ---- parse ----
            try:
                raw = json.loads(f.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("signal root must be a JSON object")
            except Exception as e:
                try:
                    self._move(f, self._dir_failed, "badjson")
                except OSError:
                    pass
                return TriggerDecision(should_wake=False, reason=f"bad signal moved to failed: {e}")

            sig_id = str(raw.get("id") or "").strip()
            trigger_id = str(raw.get("trigger_id") or "").strip()
            content = str(raw.get("content") or "").strip()

            # ---- field validation (fail → failed/, no retry) ----
            problems: list[str] = []
            if not sig_id:
                problems.append("missing id")
            if not trigger_id.startswith("trg_"):
                problems.append("invalid trigger_id")
            if not content:
                problems.append("missing content")
            if problems:
                try:
                    self._move(f, self._dir_failed, "schema")
                except OSError:
                    pass
                return TriggerDecision(
                    should_wake=False,
                    reason=f"signal {sig_id or f.name} invalid ({'; '.join(problems)}) — moved to failed",
                )

            # ---- trigger existence check (missing/disabled → failed/, no retry) ----
            trig = self._load_trigger(trigger_id)
            if trig is None:
                try:
                    self._move(f, self._dir_failed, "no-trigger")
                except OSError:
                    pass
                return TriggerDecision(
                    should_wake=False,
                    reason=f"signal {sig_id}: trigger {trigger_id} not found — moved to failed",
                )
            if not trig.get("enabled", True):
                try:
                    self._move(f, self._dir_failed, "disabled-trigger")
                except OSError:
                    pass
                return TriggerDecision(
                    should_wake=False,
                    reason=f"signal {sig_id}: trigger {trigger_id} disabled — moved to failed",
                )

            # ---- valid signal: move to processed, then wake ----
            try:
                self._move(f, self._dir_processed, "ok")
            except OSError:
                return TriggerDecision(should_wake=False, reason=f"signal {sig_id}: move failed, retry next tick")

            cooldown_until_ms = None
            cooldown_s = raw.get("cooldown_s")
            if isinstance(cooldown_s, (int, float)) and cooldown_s > 0:
                cooldown_until_ms = int(now.timestamp() * 1000 + cooldown_s * 1000)

            return TriggerDecision(
                should_wake=True,
                trigger_id=trigger_id,
                content=content,
                dedupe_key=str(raw["dedupe_key"]) if raw.get("dedupe_key") else None,
                cooldown_until_ms=cooldown_until_ms,
                evidence={
                    "signal_id": sig_id,
                    "source": str(raw.get("source") or "unknown"),
                    "file": f.name,
                },
                reason=f"signal hit: {sig_id}",
            )

        return None
