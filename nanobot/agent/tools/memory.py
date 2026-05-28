"""Memory query tools: search and retrieve daily notes.

Daily notes (memory/YYYY-MM-DD.md) hold the verbatim consolidated message
window from each consolidation. They back up MEMORY.md / HISTORY.md against
lossy summarisation — see vault/typed-memory-port-from-openclaw.md.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from nanobot.agent.memory import MemoryStore
from nanobot.agent.tools.base import Tool

_MAX_RESULT_CHARS = 16_000
_MAX_FILE_CHARS = 20_000


def _truncate(text: str, cap: int, label: str) -> str:
    if len(text) <= cap:
        return text
    return text[:cap] + f"\n\n[Truncated — {label} exceeds {cap:,} chars]"


class MemorySearchTool(Tool):
    """Grep across daily notes within a rolling window."""

    def __init__(self, workspace: Path):
        self._workspace = workspace

    @property
    def name(self) -> str:
        return "memory_search"

    @property
    def description(self) -> str:
        return (
            "Search the verbatim daily notes (memory/YYYY-MM-DD.md) for a "
            "case-insensitive substring or regex. Use this to recall specifics "
            "that the LLM summariser may have smoothed out of MEMORY.md / "
            "HISTORY.md — e.g. exact dates of past crises, things the user "
            "mentioned once, tool-call details. Returns line-level matches "
            "with date stamps."
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
                    "description": "Search window in calendar days (default 30, max 365).",
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str, days: int = 30, **kwargs: Any) -> str:
        days = max(1, min(int(days), 365))
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error:
            pattern = re.compile(re.escape(query), re.IGNORECASE)

        store = MemoryStore(self._workspace)
        files = store.list_daily_files(days=days)
        if not files:
            return f"No daily notes in the last {days} days."

        matches: list[str] = []
        for path in files:
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except Exception as e:
                matches.append(f"{path.name}: [read error: {e}]")
                continue
            for i, line in enumerate(lines, 1):
                if pattern.search(line):
                    matches.append(f"{path.name}:{i}: {line.rstrip()}")

        if not matches:
            return f"No matches for {query!r} in the last {days} days ({len(files)} daily notes searched)."

        header = f"{len(matches)} match(es) for {query!r} across {len(files)} daily notes:"
        body = "\n".join(matches)
        return _truncate(f"{header}\n{body}", _MAX_RESULT_CHARS, "search results")


class MemoryGetTool(Tool):
    """Return one daily note in full."""

    def __init__(self, workspace: Path):
        self._workspace = workspace

    @property
    def name(self) -> str:
        return "memory_get"

    @property
    def description(self) -> str:
        return (
            "Retrieve one daily-notes file (memory/YYYY-MM-DD.md) in full. "
            "Pair with memory_search to first find which day a fact came up, "
            "then pull that day's full context. Accepts ISO date "
            "(YYYY-MM-DD), 'today', or 'yesterday'."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "ISO date YYYY-MM-DD, or 'today', or 'yesterday'.",
                }
            },
            "required": ["date"],
        }

    async def execute(self, date: str, **kwargs: Any) -> str:
        store = MemoryStore(self._workspace)
        today = datetime.now().date()
        if date.lower() == "today":
            d = today
        elif date.lower() == "yesterday":
            d = today.fromordinal(today.toordinal() - 1)
        else:
            try:
                d = datetime.strptime(date.strip(), "%Y-%m-%d").date()
            except ValueError:
                return f"Error: invalid date {date!r}. Use YYYY-MM-DD, 'today', or 'yesterday'."

        path = store.memory_dir / f"{d.isoformat()}.md"
        if not path.exists():
            return f"No daily note for {d.isoformat()}."
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            return f"Error reading {path.name}: {e}"
        return _truncate(content, _MAX_FILE_CHARS, f"daily note {d.isoformat()}")
