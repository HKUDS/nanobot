"""Consolidation pipeline — extracts structured memory from old conversation turns.

``ConsolidationPipeline`` encapsulates the full consolidate workflow that was
previously spread across six methods on ``MemoryStore``.  The pipeline:

1. Selects messages eligible for consolidation (``_select_messages``).
2. Formats them as text lines (``_format_conversation_lines``).
3. Calls the LLM with a ``save_memory`` tool to produce a history entry.
4. Runs structured extraction (events + profile updates).
5. Syncs events to mem0 and optionally ingests raw turns.
6. Rebuilds MEMORY.md and updates the session pointer.

``MemoryStore`` delegates to this class via a one-line wrapper.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.prompt_loader import prompts
from nanobot.agent.tracing import bind_trace

from .constants import _SAVE_MEMORY_TOOL
from .helpers import _contains_any, _utc_now_iso
from .ingester import EventIngester

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import Session

    from .conflicts import ConflictManager
    from .extractor import MemoryExtractor
    from .mem0_adapter import _Mem0Adapter
    from .persistence import MemoryPersistence
    from .profile_io import ProfileStore as ProfileManager
    from .snapshot import MemorySnapshot


class ConsolidationPipeline:
    """Multi-stage pipeline that consolidates old conversation messages into
    persistent memory (HISTORY.md, events.jsonl, profile.json, MEMORY.md).
    """

    def __init__(
        self,
        *,
        persistence: MemoryPersistence,
        extractor: MemoryExtractor,
        ingester: EventIngester,
        profile_mgr: ProfileManager,
        conflict_mgr: ConflictManager,
        snapshot: MemorySnapshot,
        mem0: _Mem0Adapter,
        mem0_raw_turn_ingestion: bool,
        memory_file: Path,
        history_file: Path,
    ) -> None:
        self._persistence = persistence
        self._extractor = extractor
        self._ingester = ingester
        self._profile_mgr = profile_mgr
        self._conflict_mgr = conflict_mgr
        self._snapshot = snapshot
        self._mem0 = mem0
        self._mem0_raw_turn_ingestion = mem0_raw_turn_ingestion
        self._memory_file = memory_file
        self._history_file = history_file

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
    def _build_consolidation_prompt(current_memory: str, lines: list[str]) -> str:
        return f"""Process this conversation and call the save_memory tool with a history_entry summarizing key events, decisions, and topics.

## Current Long-term Memory
{current_memory or "(empty)"}

## Conversation to Process
{chr(10).join(lines)}"""

    def _apply_save_memory_tool_result(self, *, args: dict[str, Any], current_memory: str) -> None:
        if entry := args.get("history_entry"):
            if not isinstance(entry, str):
                entry = json.dumps(entry, ensure_ascii=False)
            self._persistence.append_text(self._history_file, entry.rstrip() + "\n\n")
        # memory_update is intentionally ignored (LAN-206): MEMORY.md is now a
        # pure projection rebuilt deterministically via rebuild_memory_snapshot().

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

        current_memory = self._persistence.read_text(self._memory_file)
        prompt = self._build_consolidation_prompt(current_memory, lines)

        try:
            response = await provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": prompts.get("consolidation"),
                    },
                    {"role": "user", "content": prompt},
                ],
                tools=_SAVE_MEMORY_TOOL,
                model=model,
            )

            if not response.has_tool_calls:
                logger.warning("Memory consolidation: LLM did not call save_memory, skipping")
                return False

            args = self._extractor.parse_tool_args(response.tool_calls[0].arguments)
            if not args:
                logger.warning(
                    "Memory consolidation: unexpected arguments type {}", type(args).__name__
                )
                return False

            self._apply_save_memory_tool_result(args=args, current_memory=current_memory)

            profile = self._profile_mgr.read_profile()
            events, profile_updates = await self._extractor.extract_structured_memory(
                provider,
                model,
                profile,
                lines,
                old_messages,
                source_start=source_start,
            )
            events_written = self._ingester.append_events(events)
            await self._ingester._ingest_graph_triples(events)
            # Thread event IDs into profile updates for evidence linking (LAN-197).
            event_ids = [e.get("id", "") for e in events if e.get("id")]
            profile_added, _, profile_touched = self._profile_mgr._apply_profile_updates(
                profile,
                profile_updates,
                enable_contradiction_check=enable_contradiction_check,
                source_event_ids=event_ids,
            )
            if events_written > 0 or profile_added > 0 or profile_touched > 0:
                profile["last_verified_at"] = _utc_now_iso()
                self._profile_mgr.write_profile(profile)

            # Track extraction source and per-type distribution

            if profile_added > 0:
                self._conflict_mgr.auto_resolve_conflicts(max_items=10)

            # MEMORY.md is a pure projection from profile + events (LAN-206).
            self._snapshot.rebuild_memory_snapshot(write=True)

            # LAN-208: sync structured events to mem0 as the primary indexing
            # path — mem0 is a semantic index, not a raw transcript store.
            if self._mem0.enabled and events:
                self._ingester._sync_events_to_mem0(events)

            # LAN-208: raw conversation turn ingestion — legacy behaviour, gated
            # behind _mem0_raw_turn_ingestion (default True for backward compat).
            if self._mem0.enabled and self._mem0_raw_turn_ingestion:
                for m in old_messages:
                    role = str(m.get("role", "user")).strip().lower() or "user"
                    content = str(m.get("content", "")).strip()
                    if not content:
                        continue
                    memory_type = "episodic"
                    if role == "user":
                        memory_type = (
                            "semantic"
                            if _contains_any(
                                content,
                                (
                                    "prefer",
                                    "always",
                                    "never",
                                    "must",
                                    "cannot",
                                    "my setup",
                                    "i use",
                                ),
                            )
                            else "episodic"
                        )
                    turn_meta, _ = self._ingester._normalize_memory_metadata(
                        {
                            "topic": "conversation_turn",
                            "memory_type": memory_type,
                            "stability": "medium",
                        },
                        event_type="fact",
                        summary=content,
                        source="chat",
                    )
                    turn_meta.update(
                        {
                            "event_type": "conversation_turn",
                            "role": role,
                            "timestamp": str(m.get("timestamp", "")),
                            "session": session.key,
                        }
                    )
                    clean_content = self._ingester._sanitize_mem0_text(
                        content, allow_archival=False
                    )
                    turn_meta = EventIngester._sanitize_mem0_metadata(turn_meta)
                    if clean_content:
                        self._mem0.add_text(
                            clean_content,
                            metadata=turn_meta,
                        )

            self._finalize_consolidation(
                session,
                archive_all=archive_all,
                keep_count=keep_count,
            )
            bind_trace().debug(
                "Memory consolidate events={} duration_ms={:.0f}",
                events_written,
                (time.monotonic() - t0) * 1000,
            )
            return True
        except Exception:  # crash-barrier: multi-stage consolidation must not crash
            logger.exception("Memory consolidation failed")
            return False
