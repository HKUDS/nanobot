"""Consolidation pipeline — extracts structured memory from old conversation turns.

``ConsolidationPipeline`` encapsulates the full consolidate workflow that was
previously spread across six methods on ``MemoryStore``.  The pipeline:

1. Selects messages eligible for consolidation (``_select_messages``).
2. Formats them as text lines (``_format_conversation_lines``).
3. Calls the LLM with a ``save_memory`` tool to produce a history entry.
4. Runs structured extraction (events + profile updates).
5. Rebuilds MEMORY.md and updates the session pointer.

``MemoryStore`` delegates to this class via a one-line wrapper.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.context.prompt_loader import prompts
from nanobot.observability.tracing import bind_trace

from ._text import _utc_now_iso
from .constants import _CONSOLIDATE_MEMORY_TOOL

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import Session

    from .persistence.profile_io import ProfileStore as ProfileManager
    from .persistence.snapshot import MemorySnapshot
    from .write.conflicts import ConflictManager
    from .write.extractor import MemoryExtractor
    from .write.ingester import EventIngester


class ConsolidationPipeline:
    """Multi-stage pipeline that consolidates old conversation messages into
    persistent memory (HISTORY.md, events.jsonl, profile.json, MEMORY.md).
    """

    def __init__(
        self,
        *,
        extractor: MemoryExtractor,
        ingester: EventIngester,
        profile_mgr: ProfileManager,
        conflict_mgr: ConflictManager,
        snapshot: MemorySnapshot,
        memory_file: Path,
        history_file: Path,
        rollout: dict[str, Any] | None = None,
    ) -> None:
        self._extractor = extractor
        self._ingester = ingester
        self._profile_mgr = profile_mgr
        self._conflict_mgr = conflict_mgr
        self._snapshot = snapshot
        self._memory_file = memory_file
        self._history_file = history_file
        self._rollout: dict[str, Any] = rollout or {}

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    def _select_messages_for_consolidation(
        self,
        session: Session,
        *,
        archive_all: bool,
        memory_window: int,
    ) -> tuple[list[dict[str, Any]], int, int] | None:
        if archive_all:
            old_messages = session.messages
            keep_count = 0
            source_start = 0
            logger.info("Memory consolidation (archive_all): {} messages", len(session.messages))
            return old_messages, keep_count, source_start

        keep_count = memory_window // 2
        if len(session.messages) <= keep_count:
            return None
        if len(session.messages) - session.last_consolidated <= 0:
            return None
        old_messages = session.messages[session.last_consolidated : -keep_count]
        source_start = session.last_consolidated
        if not old_messages:
            return None
        logger.info(
            "Memory consolidation: {} to consolidate, {} keep", len(old_messages), keep_count
        )
        return old_messages, keep_count, source_start

    @staticmethod
    def _format_conversation_lines(old_messages: list[dict[str, Any]]) -> list[str]:
        lines = []
        for m in old_messages:
            if not m.get("content"):
                continue
            tools = f" [tools: {', '.join(m['tools_used'])}]" if m.get("tools_used") else ""
            lines.append(
                f"[{m.get('timestamp', '?')[:16]}] {m['role'].upper()}{tools}: {m['content']}"
            )
        return lines

    @staticmethod
    def _build_single_tool_prompt(current_memory: str, lines: list[str]) -> str:
        return (
            "Process this conversation and call the consolidate_memory tool with:\n"
            "1. A history_entry summarizing key events, decisions, and topics "
            "(2-5 sentences).\n"
            "2. Structured events for long-term memory.\n"
            "3. Any profile updates.\n\n"
            f"## Current Long-term Memory\n{current_memory or '(empty)'}\n\n"
            f"## Conversation to Process\n{chr(10).join(lines)}"
        )

    def _finalize_consolidation(
        self, session: Session, *, archive_all: bool, keep_count: int
    ) -> None:
        session.last_consolidated = 0 if archive_all else len(session.messages) - keep_count
        logger.info(
            "Memory consolidation done: {} messages, last_consolidated={}",
            len(session.messages),
            session.last_consolidated,
        )

    # ------------------------------------------------------------------
    # Single-tool consolidation path (Task 6)
    # ------------------------------------------------------------------

    async def _consolidate_single_tool(
        self,
        session: Session,
        provider: LLMProvider,
        model: str,
        lines: list[str],
        old_messages: list[dict[str, Any]],
        current_memory: str,
        *,
        source_start: int,
        archive_all: bool,
        keep_count: int,
        enable_contradiction_check: bool,
    ) -> bool:
        """Single LLM call that produces history_entry + events + profile_updates."""
        prompt = self._build_single_tool_prompt(current_memory, lines)

        response = await provider.chat(
            messages=[
                {
                    "role": "system",
                    "content": prompts.get("consolidation"),
                },
                {"role": "user", "content": prompt},
            ],
            tools=_CONSOLIDATE_MEMORY_TOOL,
            model=model,
        )

        # -- Parse tool call arguments --
        args: dict[str, Any] = {}
        if response.has_tool_calls:
            parsed = self._extractor.parse_tool_args(response.tool_calls[0].arguments)
            if parsed:
                args = parsed

        # -- History entry (fallback: first few lines) --
        history_entry = args.get("history_entry")
        if not history_entry or not isinstance(history_entry, str):
            history_entry = " ".join(lines[:3]) if lines else ""
            logger.warning("consolidate_memory: history_entry missing, generated from first lines")
        if history_entry:
            with open(self._history_file, "a", encoding="utf-8") as _f:
                _f.write(history_entry.rstrip() + "\n\n")

        # -- Events (fallback: heuristic extractor) --
        raw_events = args.get("events")
        events: list[dict[str, Any]] = []
        profile_updates: dict[str, list[str]] = self._extractor.default_profile_updates()

        if isinstance(raw_events, list) and raw_events:
            for item in raw_events:
                if not isinstance(item, dict):
                    continue
                source_span = item.get("source_span")
                if (
                    not isinstance(source_span, list)
                    or len(source_span) != 2
                    or not all(isinstance(x, int) for x in source_span)
                ):
                    source_span = [
                        source_start,
                        source_start + max(len(old_messages) - 1, 0),
                    ]
                event = self._extractor.coerce_event(item, source_span=source_span)
                if event:
                    events.append(event)
                if len(events) >= 40:
                    break

            # Parse profile updates from the same tool call
            raw_updates = args.get("profile_updates")
            if isinstance(raw_updates, dict):
                for key in profile_updates:
                    profile_updates[key] = self._extractor.to_str_list(raw_updates.get(key))
        else:
            logger.warning(
                "consolidate_memory: events missing or malformed, "
                "falling back to heuristic extraction"
            )
            events, profile_updates = self._extractor.heuristic_extract_events(
                old_messages, source_start=source_start
            )

        # -- Apply results (same as two-call path) --
        events_written = self._ingester.append_events(events)
        await self._ingester._ingest_graph_triples(events)

        event_ids = [e.get("id", "") for e in events if e.get("id")]
        profile = self._profile_mgr.read_profile()
        profile_added, _, profile_touched = self._profile_mgr._apply_profile_updates(
            profile,
            profile_updates,
            enable_contradiction_check=enable_contradiction_check,
            source_event_ids=event_ids,
        )
        if events_written > 0 or profile_added > 0 or profile_touched > 0:
            profile["last_verified_at"] = _utc_now_iso()
            self._profile_mgr.write_profile(profile)

        if profile_added > 0:
            self._conflict_mgr.auto_resolve_conflicts(max_items=10)

        self._snapshot.rebuild_memory_snapshot(write=True)

        self._finalize_consolidation(
            session,
            archive_all=archive_all,
            keep_count=keep_count,
        )
        return True

    # ------------------------------------------------------------------
    # Main pipeline
    # ------------------------------------------------------------------

    async def consolidate(
        self,
        session: Session,
        provider: LLMProvider,
        model: str,
        *,
        archive_all: bool = False,
        memory_window: int = 50,
        memory_mode: str | None = None,
        enable_contradiction_check: bool = True,
    ) -> bool:
        """Consolidate old messages into MEMORY.md + HISTORY.md via LLM tool call.

        Returns True on success (including no-op), False on failure.
        """
        t0 = time.monotonic()
        selection = self._select_messages_for_consolidation(
            session,
            archive_all=archive_all,
            memory_window=memory_window,
        )
        if selection is None:
            return True
        old_messages, keep_count, source_start = selection

        lines = self._format_conversation_lines(old_messages)

        try:
            current_memory = self._memory_file.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            current_memory = ""

        try:
            result = await self._consolidate_single_tool(
                session,
                provider,
                model,
                lines,
                old_messages,
                current_memory,
                source_start=source_start,
                archive_all=archive_all,
                keep_count=keep_count,
                enable_contradiction_check=enable_contradiction_check,
            )
            bind_trace().debug(
                "Memory consolidate (single-tool) duration_ms={:.0f}",
                (time.monotonic() - t0) * 1000,
            )
            return result
        except Exception:  # crash-barrier: multi-stage consolidation must not crash
            logger.exception("Memory consolidation failed")
            return False
