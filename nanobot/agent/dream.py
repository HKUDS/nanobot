"""Dream service: async background memory consolidation.

Inspired by Claude Code's Auto-Dream mechanism — a background agent that
consolidates cross-session memory during low-pressure periods (no active
user conversation), like human sleep-based memory consolidation.

Four phases:
  1. Orient  — scan memory directory, read MEMORY.md index
  2. Gather  — find new signal from HISTORY.md since last dream
  3. Consolidate — merge/delete/update MEMORY.md facts
  4. Prune   — keep MEMORY.md concise (<200 lines)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider

_MAX_MEMORY_LINES = 200
_MAX_HISTORY_CONTEXT_CHARS = 16_000

_DREAM_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "save_dream_result",
            "description": "Save the consolidated memory after dream processing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "updated_memory": {
                        "type": "string",
                        "description": (
                            "Full updated MEMORY.md content as markdown. "
                            "Merge new insights, delete contradicted facts, "
                            "convert relative dates to absolute, keep under 200 lines."
                        ),
                    },
                    "changes_summary": {
                        "type": "string",
                        "description": "Brief summary of what changed and why.",
                    },
                },
                "required": ["updated_memory", "changes_summary"],
            },
        },
    }
]


class DreamService:
    """Background memory consolidation that runs outside active conversations.

    Designed to be triggered by cron (e.g., daily at 3 AM) or after N sessions.
    """

    def __init__(self, workspace: Path, provider: LLMProvider, model: str):
        self.workspace = workspace
        self.provider = provider
        self.model = model
        self.memory_dir = workspace / "memory"
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"
        self.dreams_dir = self.memory_dir / "dreams"
        self._last_dream_file = self.dreams_dir / ".last_dream"

    def should_dream(self, *, min_interval_hours: int = 24) -> bool:
        """Check gate conditions for dreaming."""
        if not self.history_file.exists():
            return False

        # Time gate: at least N hours since last dream
        if self._last_dream_file.exists():
            try:
                last = datetime.fromisoformat(
                    self._last_dream_file.read_text().strip()
                )
                elapsed = (datetime.now(timezone.utc) - last).total_seconds() / 3600
                if elapsed < min_interval_hours:
                    logger.debug(
                        "Dream gate: only {:.1f}h since last dream (need {}h)",
                        elapsed, min_interval_hours,
                    )
                    return False
            except (ValueError, OSError):
                pass  # Corrupted timestamp, allow dream

        return True

    async def dream(self) -> str | None:
        """Run the 4-phase dream consolidation.

        Returns a summary of changes, or None if nothing changed.
        """
        logger.info("Dream starting: consolidating cross-session memory")

        # Phase 1: Orient
        current_memory = ""
        if self.memory_file.exists():
            current_memory = self.memory_file.read_text(encoding="utf-8")

        # Phase 2: Gather — read recent history entries
        recent_history = self._gather_recent_history()
        if not recent_history.strip():
            logger.info("Dream: no new history to process")
            self._record_dream_time()
            return None

        # Phase 3 & 4: Consolidate & Prune via LLM
        prompt = self._build_dream_prompt(current_memory, recent_history)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a memory consolidation agent performing a 'dream' — "
                    "an offline review and cleanup of persistent memory.\n\n"
                    "Rules:\n"
                    "- Merge redundant entries into one concise fact\n"
                    "- Delete facts contradicted by newer information\n"
                    "- Convert relative dates ('yesterday', 'last week') to absolute dates\n"
                    "- Keep the total under 200 lines\n"
                    "- Preserve structure (headings, sections)\n"
                    "- Do NOT invent facts — only consolidate what exists\n"
                    "- If a fact appeared in history that isn't in memory yet, add it\n"
                    "- If nothing meaningful changed, return the memory as-is\n"
                ),
            },
            {"role": "user", "content": prompt},
        ]

        try:
            response = await self.provider.chat_with_retry(
                messages=messages,
                tools=_DREAM_TOOL,
                model=self.model,
                tool_choice={"type": "function", "function": {"name": "save_dream_result"}},
            )

            if not response.has_tool_calls:
                logger.warning("Dream: LLM did not call save_dream_result")
                self._record_dream_time()
                return None

            args = response.tool_calls[0].arguments
            if isinstance(args, str):
                args = json.loads(args)

            updated = args.get("updated_memory", "")
            summary = args.get("changes_summary", "no changes")

            if updated and updated != current_memory:
                self.memory_file.write_text(updated, encoding="utf-8")
                logger.info("Dream: memory updated — {}", summary)
            else:
                logger.info("Dream: no meaningful changes — {}", summary)

            # Record dream proposal for audit
            self._save_dream_proposal(summary, updated)
            self._record_dream_time()
            return summary

        except Exception:
            logger.exception("Dream consolidation failed")
            self._record_dream_time()
            return None

    def _gather_recent_history(self) -> str:
        """Read recent history entries, capped at a reasonable size."""
        if not self.history_file.exists():
            return ""
        content = self.history_file.read_text(encoding="utf-8")
        # Take last N chars to stay within token budget
        if len(content) > _MAX_HISTORY_CONTEXT_CHARS:
            content = content[-_MAX_HISTORY_CONTEXT_CHARS:]
            # Find first complete entry
            idx = content.find("\n[")
            if idx > 0:
                content = content[idx:]
        return content

    def _build_dream_prompt(self, memory: str, history: str) -> str:
        """Build the dream consolidation prompt."""
        memory_section = memory if memory else "(empty — no existing memory)"
        line_count = len(memory.splitlines()) if memory else 0

        return f"""## Current MEMORY.md ({line_count} lines)

{memory_section}

## Recent HISTORY.md Entries (new since last review)

{history}

## Instructions

1. **Orient**: Review the current memory structure and sections
2. **Gather**: Identify new facts, patterns, and corrections from history
3. **Consolidate**: Merge new insights into memory, delete contradicted facts, update stale entries
4. **Prune**: Ensure the result is under {_MAX_MEMORY_LINES} lines — compress verbose entries, remove low-value details

Call save_dream_result with the updated memory and a brief summary of changes."""

    def _record_dream_time(self) -> None:
        """Record the timestamp of this dream."""
        self.dreams_dir.mkdir(parents=True, exist_ok=True)
        self._last_dream_file.write_text(
            datetime.now(timezone.utc).isoformat()
        )

    def _save_dream_proposal(self, summary: str, content: str) -> None:
        """Save dream output for audit/review."""
        self.dreams_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        proposal = self.dreams_dir / f"dream-{ts}-result.md"
        proposal.write_text(
            f"# Dream Result — {ts}\n\n"
            f"## Summary\n{summary}\n\n"
            f"## Updated Memory\n{content}\n",
            encoding="utf-8",
        )
