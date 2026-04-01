"""LLM + heuristic extraction of structured memory events.

``MemoryExtractor`` converts raw conversation messages into structured
memory event dicts suitable for storage in the SQLite database.  The pipeline:

1. **Heuristic pre-filter** — skip short/trivial messages to avoid LLM calls.
2. **LLM extraction** — ask the provider to identify entities, facts, and
   events from conversation context; output structured JSON via tool-call.
3. **Coercion + validation** — normalize extracted events (timestamps,
   entity lists, salience scores, TTL) into the canonical event schema.

Extracted events are consumed by ``MemoryStore.consolidate()`` which
persists them and updates the active knowledge snapshot.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.context.prompt_loader import prompts

__all__ = ["MemoryExtractor"]

from ..constants import _SAVE_EVENTS_TOOL
from ..event import MemoryEvent
from .correction_detector import (
    clean_phrase,
    extract_fact_corrections,
    extract_preference_corrections,
)
from .heuristic_extractor import (
    extract_entities,
    extract_events_heuristic,
    extract_triples_heuristic,
)
from .micro_extractor import _build_source

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider


class MemoryExtractor:
    """LLM + heuristic extraction component extracted from MemoryStore."""

    def __init__(
        self,
        *,
        to_str_list: Callable[[Any], list[str]],
        coerce_event: Callable[..., MemoryEvent | None],
        utc_now_iso: Callable[[], str],
    ):
        self.to_str_list = to_str_list
        self.coerce_event = coerce_event
        self.utc_now_iso = utc_now_iso
        self.last_extraction_source: str = ""

    @staticmethod
    def default_profile_updates() -> dict[str, list[str]]:
        return {
            "preferences": [],
            "stable_facts": [],
            "active_projects": [],
            "relationships": [],
            "constraints": [],
        }

    @staticmethod
    def parse_tool_args(args: Any) -> dict[str, Any] | None:
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                return None
        return args if isinstance(args, dict) else None

    # ------------------------------------------------------------------
    # Correction detection — delegates to correction_detector module
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_phrase(value: str) -> str:
        return clean_phrase(value)

    def extract_explicit_preference_corrections(self, content: str) -> list[tuple[str, str]]:
        return extract_preference_corrections(content)

    def extract_explicit_fact_corrections(self, content: str) -> list[tuple[str, str]]:
        return extract_fact_corrections(content)

    # ------------------------------------------------------------------
    # Heuristic extraction — delegates to heuristic_extractor module
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_entities(text: str) -> list[str]:
        """Extract likely entity names from text via capitalized phrases and quoted strings."""
        return extract_entities(text)

    @classmethod
    def _extract_triples_heuristic(
        cls,
        summary: str,
        entities: list[str],
        event_type: str,
    ) -> list[dict[str, str | float]]:
        """Extract subject-predicate-object triples from text via patterns."""
        return extract_triples_heuristic(summary, entities, event_type)

    def heuristic_extract_events(
        self,
        old_messages: list[dict[str, Any]],
        *,
        source_start: int,
    ) -> tuple[list[MemoryEvent], dict[str, list[str]]]:
        return extract_events_heuristic(
            old_messages,
            source_start=source_start,
            coerce_event_fn=self.coerce_event,
            utc_now_iso_fn=self.utc_now_iso,
            default_profile_updates_fn=self.default_profile_updates,
        )

    # ------------------------------------------------------------------
    # LLM-based extraction
    # ------------------------------------------------------------------

    async def extract_structured_memory(
        self,
        provider: LLMProvider,
        model: str,
        current_profile: dict[str, Any],
        lines: list[str],
        old_messages: list[dict[str, Any]],
        *,
        source_start: int,
        channel: str = "",
        tool_hints: list[str] | None = None,
        turn_timestamp: str = "",
    ) -> tuple[list[MemoryEvent], dict[str, list[str]]]:
        prompt = (
            "Extract structured memory from this conversation and call save_events. "
            "Only include actionable long-term information.\n\n"
            "## Current Profile\n"
            f"{json.dumps(current_profile, ensure_ascii=False)}\n\n"
            "## Conversation\n"
            f"{chr(10).join(lines)}"
        )
        try:
            response = await provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": prompts.get("extractor"),
                    },
                    {"role": "user", "content": prompt},
                ],
                tools=_SAVE_EVENTS_TOOL,
                model=model,
            )
            if response.has_tool_calls:
                args = self.parse_tool_args(response.tool_calls[0].arguments)
                if args:
                    _raw_events = args.get("events")
                    raw_events: list[Any] = _raw_events if isinstance(_raw_events, list) else []
                    _raw_updates = args.get("profile_updates")
                    raw_updates: dict[str, Any] = (
                        _raw_updates if isinstance(_raw_updates, dict) else {}
                    )
                    updates = self.default_profile_updates()
                    for key in updates:
                        updates[key] = self.to_str_list(raw_updates.get(key))

                    events: list[MemoryEvent] = []
                    for _, item in enumerate(raw_events):
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
                        event = self.coerce_event(item, source_span=source_span)
                        if event:
                            events.append(event)
                        if len(events) >= 40:
                            break
                    self.last_extraction_source = "llm"
                    if channel or tool_hints:
                        _source = _build_source(channel, tool_hints or [])
                        for event in events:
                            event.source = _source
                            if turn_timestamp:
                                event.metadata["source_timestamp"] = turn_timestamp
                    return events, updates
        except Exception:  # crash-barrier: LLM extraction + parsing
            logger.exception(
                "Structured event extraction failed, falling back to heuristic extraction"
            )

        self.last_extraction_source = "heuristic"
        return self.heuristic_extract_events(old_messages, source_start=source_start)
