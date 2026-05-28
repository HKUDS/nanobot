"""Session search: grep across all of this agent's session jsonl files.

Sessions are persisted per-channel under `workspace/sessions/<key>.jsonl`. Each
session is a separate context window for the LLM — Iroh's chat with Glyn and
Iroh's chat with Steve are different sessions and don't share working memory.
MEMORY.md / HISTORY.md are shared across sessions but updated only via the
(slow, lossy) consolidation cycle.

This tool closes the gap: lets the agent grep what it saw or did in *other*
sessions at any time, regardless of whether consolidation has fired.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool

_MAX_RESULT_CHARS = 16_000
_DEFAULT_DAYS = 30


def _truncate(text: str, cap: int, label: str) -> str:
    if len(text) <= cap:
        return text
    return text[:cap] + f"\n\n[Truncated — {label} exceeds {cap:,} chars]"


def _content_text(obj: dict[str, Any]) -> str:
    """Best-effort string view of one message line, including tool-call args."""
    content = obj.get("content")
    if isinstance(content, str) and content:
        return content
    parts: list[str] = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                t = item.get("text") or item.get("content")
                if isinstance(t, str):
                    parts.append(t)
    if tool_calls := obj.get("tool_calls"):
        for tc in tool_calls:
            fn = (tc or {}).get("function") or {}
            name = fn.get("name") or "?"
            args = fn.get("arguments") or ""
            parts.append(f"tool:{name}({args})")
    return " ".join(p for p in parts if p)


class SessionSearchTool(Tool):
    """Grep across this agent's session jsonl files."""

    def __init__(self, workspace: Path):
        self._workspace = workspace

    @property
    def name(self) -> str:
        return "session_search"

    @property
    def description(self) -> str:
        return (
            "Search across ALL session transcripts for this agent — "
            "including sessions you're not currently in. Use this when "
            "another channel/user reported something you don't have in your "
            "current context (e.g. someone asks 'how is Glyn doing today?' "
            "and you need to recall what Glyn said in a different session). "
            "Case-insensitive substring or regex. Returns session_key + "
            "timestamp + role + content for each match, newest sessions first."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Pattern to search for. Case-insensitive. Plain substring or regex.",
                },
                "days": {
                    "type": "integer",
                    "description": (
                        f"Only consider messages newer than this many days "
                        f"(default {_DEFAULT_DAYS}, max 365)."
                    ),
                },
                "session": {
                    "type": "string",
                    "description": (
                        "Optional: restrict to one session key (e.g. "
                        "'telegram_8341580836'). Omit to search all sessions."
                    ),
                },
            },
            "required": ["query"],
        }

    async def execute(
        self,
        query: str,
        days: int = _DEFAULT_DAYS,
        session: str | None = None,
        **kwargs: Any,
    ) -> str:
        days = max(1, min(int(days), 365))
        cutoff = datetime.now() - timedelta(days=days)

        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error:
            pattern = re.compile(re.escape(query), re.IGNORECASE)

        sessions_dir = self._workspace / "sessions"
        if not sessions_dir.is_dir():
            return "No sessions directory yet."

        files = sorted(sessions_dir.glob("*.jsonl"))
        if session:
            files = [p for p in files if p.stem == session]
            if not files:
                return f"No session matching {session!r}."

        # Sort newest first by mtime so the most recent context surfaces first
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        matches: list[str] = []
        for path in files:
            session_key = path.stem
            try:
                with open(path, encoding="utf-8") as f:
                    for raw in f:
                        raw = raw.strip()
                        if not raw:
                            continue
                        try:
                            obj = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        # Filter by timestamp window
                        ts = obj.get("timestamp")
                        if isinstance(ts, str):
                            try:
                                t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                                if t.tzinfo:
                                    t = t.replace(tzinfo=None)
                                if t < cutoff:
                                    continue
                            except ValueError:
                                pass
                        text = _content_text(obj)
                        if not text or not pattern.search(text):
                            continue
                        role = obj.get("role") or "?"
                        ts_short = (ts or "?")[:16] if isinstance(ts, str) else "?"
                        snippet = text.replace("\n", " ")
                        if len(snippet) > 300:
                            snippet = snippet[:300] + "…"
                        matches.append(
                            f"[{session_key}] [{ts_short}] {role.upper()}: {snippet}"
                        )
            except Exception as e:  # noqa: BLE001 — defensive
                matches.append(f"[{session_key}] [read error: {e}]")

        if not matches:
            scope = f" in session {session}" if session else ""
            return (
                f"No matches for {query!r}{scope} in the last {days} days "
                f"({len(files)} session file(s) searched)."
            )

        header = (
            f"{len(matches)} match(es) for {query!r} across "
            f"{len(files)} session file(s):"
        )
        body = "\n".join(matches)
        return _truncate(f"{header}\n{body}", _MAX_RESULT_CHARS, "search results")
