"""Usage log: append-only JSONL record of tool calls and agent turns."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class UsageLog:
    """Writes usage.jsonl at the workspace root.

    Three event types:
      tool_call — one record per tool execution, with timing and ok flag.
      llm_call  — one record per LLM provider call, with token and context stats.
      turn      — one record per agent turn, summarising tools used.

    Failures are silently swallowed — usage logging must never break the agent.
    """

    def __init__(self, workspace: Path):
        self._file = workspace / "usage.jsonl"

    def _write(self, record: dict[str, Any]) -> None:
        try:
            with open(self._file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def log_tool_call(
        self,
        session: str,
        tool: str,
        args: dict[str, Any] | None,
        duration_ms: int,
        ok: bool,
    ) -> None:
        """Record a single tool execution."""
        # First string arg value — enough to identify target (path, query, command)
        # without storing full content.
        arg = next((v for v in (args or {}).values() if isinstance(v, str)), None)
        self._write({
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": "tool_call",
            "session": session,
            "tool": tool,
            "arg": arg,
            "duration_ms": duration_ms,
            "ok": ok,
        })

    def log_llm_call(
        self,
        session: str,
        iteration: int,
        sys_chars: int,
        hist_chars: int,
        tool_definitions: int,
        prompt_tokens: int | None,
        completion_tokens: int | None,
    ) -> None:
        """Record a single LLM provider call with context size and token usage."""
        self._write({
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": "llm_call",
            "session": session,
            "iteration": iteration,
            "sys_chars": sys_chars,
            "hist_chars": hist_chars,
            "tool_definitions": tool_definitions,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        })

    def log_turn(self, session: str, tools_used: list[str]) -> None:
        """Record a completed agent turn."""
        self._write({
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": "turn",
            "session": session,
            "tools": tools_used,
            "tool_calls": len(tools_used),
        })
