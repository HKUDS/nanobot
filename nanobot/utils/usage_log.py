"""Lightweight per-call token and cost usage logger.

Writes one JSONL record per LLM API call to ``{workspace}/usage/log.jsonl``
so users can inspect cumulative consumption across sessions and over time.

The logger is optional and off by default — enable with ``usage_log: true``
in the agent config section.  Only the last 90 days are retained.
"""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from contextlib import suppress
from pathlib import Path
from typing import Any

from loguru import logger


_USAGE_LOG_DIR = "usage"
_USAGE_LOG_FILE = "log.jsonl"
_MAX_DAYS = 90


class UsageLog:
    """Append-only JSONL usage store for a single workspace."""

    def __init__(self, workspace: Path) -> None:
        self._path = workspace / _USAGE_LOG_DIR / _USAGE_LOG_FILE
        self._path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(
        self,
        *,
        model: str,
        provider: str,
        session_id: str,
        usage: dict[str, int],
        timestamp: float | None = None,
    ) -> None:
        """Append a single usage record."""
        record = {
            "timestamp": timestamp or time.time(),
            "model": model,
            "provider": provider,
            "session_id": session_id,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "cached_tokens": usage.get("cached_tokens", 0),
        }
        try:
            with open(self._path, "a") as f:
                f.write(json.dumps(record, sort_keys=True) + "\n")
        except OSError as exc:
            logger.warning("Failed to write usage log: {}", exc)

    def insights(self, days: int = 7) -> dict[str, Any]:
        """Aggregate usage over the last *days*.

        Returns a dict with keys:
          ``turns``, ``total_tokens``, ``prompt_tokens``,
          ``completion_tokens``, ``cached_tokens``, ``models`` (per-model break‑down),
          ``daily`` (per‑day series).
        """
        if not self._path.exists():
            return {"turns": 0, "total_tokens": 0, "prompt_tokens": 0,
                    "completion_tokens": 0, "cached_tokens": 0,
                    "models": {}, "daily": {}}

        cutoff = time.time() - days * 86400
        total: dict[str, int] = defaultdict(int)
        models: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        daily: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        turns = 0

        with suppress(Exception):
            with open(self._path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    ts = rec.get("timestamp", 0)
                    if ts < cutoff:
                        continue
                    turns += 1
                    total["prompt_tokens"] += rec.get("prompt_tokens", 0)
                    total["completion_tokens"] += rec.get("completion_tokens", 0)
                    total["total_tokens"] += rec.get("total_tokens", 0)
                    total["cached_tokens"] += rec.get("cached_tokens", 0)

                    model_name = rec.get("model", "unknown")
                    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        models[model_name][k] += rec.get(k, 0)

                    day_key = time.strftime("%Y-%m-%d", time.gmtime(ts))
                    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        daily[day_key][k] += rec.get(k, 0)

        return {
            "turns": turns,
            "total_tokens": total.get("total_tokens", 0),
            "prompt_tokens": total.get("prompt_tokens", 0),
            "completion_tokens": total.get("completion_tokens", 0),
            "cached_tokens": total.get("cached_tokens", 0),
            "models": dict(models),
            "daily": dict(daily),
        }

    def rotate(self) -> None:
        """Remove records older than ``_MAX_DAYS`` in-place."""
        if not self._path.exists():
            return
        cutoff = time.time() - _MAX_DAYS * 86400
        tmp = self._path.with_suffix(".jsonl.tmp")
        kept = 0
        removed = 0
        with suppress(Exception):
            with open(self._path) as f_in, open(tmp, "w") as f_out:
                for line in f_in:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    if rec.get("timestamp", 0) >= cutoff:
                        f_out.write(line + "\n")
                        kept += 1
                    else:
                        removed += 1
            os.replace(tmp, self._path)
        if removed:
            logger.debug("Usage log rotated: kept {} records, removed {}", kept, removed)
