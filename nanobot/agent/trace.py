"""LLM request/response trace logger.

Appends one JSONL line per LLM call to the configured log directory.
Injected as an AgentHook — zero coupling to provider or runner internals.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.utils.helpers import safe_filename


class TraceHook(AgentHook):
    """Record every LLM call as a JSONL trace entry."""

    __slots__ = ("_log_dir", "_log_path", "_session_key", "_call_t0", "_call_kwargs")

    def __init__(self, llm_logs_dir: Path | None = None, *, traces_dir: Path | None = None) -> None:
        # New callers use llm_logs_dir; legacy callers use traces_dir.
        self._log_dir = llm_logs_dir or traces_dir or Path(".")
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._log_path: Path | None = None
        self._session_key: str = "unknown"
        self._call_t0: float = 0
        self._call_kwargs: dict[str, Any] = {}

    @property
    def session_key(self) -> str:
        return self._session_key

    @session_key.setter
    def session_key(self, value: str) -> None:
        self._session_key = value

    def set_log_path(self, path: Path) -> None:
        """Set exact log file path (paired 1:1 with the session file)."""
        self._log_path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    async def before_iteration(self, context: AgentHookContext) -> None:
        """Snapshot request state and start timer."""
        self._call_t0 = time.monotonic()
        self._call_kwargs = {
            "message_count": len(context.messages),
            "messages": self._sanitize_messages(context.messages),
        }

    async def after_iteration(self, context: AgentHookContext) -> None:
        """Build trace entry and append to file."""
        from datetime import datetime, timezone

        elapsed_ms = int((time.monotonic() - self._call_t0) * 1000)
        resp = context.response

        entry: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_key": self._session_key,
            "iteration": context.iteration,
            "request": self._call_kwargs,
            "response": {
                "content": (resp.content or "")[:2000] if resp else None,
                "tool_calls": [
                    {"name": tc.name, "arguments": tc.arguments}
                    for tc in (context.tool_calls or [])
                ],
                "finish_reason": resp.finish_reason if resp else None,
                "usage": dict(context.usage),
            },
            "elapsed_ms": elapsed_ms,
        }

        if self._log_path:
            path = self._log_path
        else:
            path = self._log_dir / f"{safe_filename(self._session_key.replace(':', '_'))}.jsonl"

        line = json.dumps(entry, ensure_ascii=False, default=str)
        try:
            await asyncio.to_thread(self._append_line, path, line)
        except Exception:
            logger.warning("Failed to write trace entry to {}", path)

    @staticmethod
    def _append_line(path: Path, line: str) -> None:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    @staticmethod
    def _sanitize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Replace base64 image payloads with placeholders."""
        out: list[dict[str, Any]] = []
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, list):
                sanitized: list[dict[str, Any]] = []
                for block in content:
                    if (
                        isinstance(block, dict)
                        and block.get("type") == "image_url"
                        and isinstance(block.get("image_url"), dict)
                        and str(block["image_url"].get("url", "")).startswith("data:")
                    ):
                        path = (block.get("_meta") or {}).get("path", "")
                        sanitized.append({"type": "text", "text": f"[image: {path}]" if path else "[image]"})
                    else:
                        sanitized.append(block)
                out.append({**msg, "content": sanitized})
            else:
                out.append(msg)
        return out
