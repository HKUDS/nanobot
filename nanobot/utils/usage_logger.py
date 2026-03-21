"""Lightweight JSONL logger for LLM token usage tracking."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from nanobot.utils.helpers import ensure_dir


class UsageLogger:
    """Append-only JSONL logger for per-request LLM token usage.

    Each call to ``log()`` appends a single JSON line to
    ``<workspace>/logs/usage.jsonl``.  The format is intentionally flat
    so that downstream tools (pandas, jq, grep) can consume it without
    a schema.
    """

    _FILENAME = "usage.jsonl"

    def __init__(self, workspace: Path) -> None:
        self._log_dir = workspace / "logs"
        self._path = self._log_dir / self._FILENAME

    def log(
        self,
        model: str,
        usage: dict[str, int],
        session_id: str | None = None,
        provider: str | None = None,
    ) -> None:
        """Append a usage record.  No-op when *usage* is empty."""
        if not usage:
            return

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }
        if session_id:
            record["session_id"] = session_id
        if provider:
            record["provider"] = provider

        try:
            ensure_dir(self._log_dir)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            logger.exception("Failed to write usage log")
