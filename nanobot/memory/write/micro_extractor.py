"""Lightweight per-turn memory extraction.

Extracts structured memory events from individual conversation turns
using a cheap model (default: gpt-4o-mini). Events flow through the
existing EventIngester pipeline for deduplication, embedding, and
graph ingestion.

This is a best-effort optimization — full consolidation remains the
authoritative memory pipeline. See the design spec at
``docs/superpowers/specs/2026-03-26-micro-extraction-design.md``.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.context.prompt_loader import prompts

from ..event import MemoryEvent

if TYPE_CHECKING:
    from nanobot.memory.write.ingester import EventIngester
    from nanobot.providers.base import LLMProvider

_MICRO_EXTRACT_TOOL: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "save_events",
            "description": (
                "Save extracted memory events. Return empty array if nothing worth remembering."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "events": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": [
                                        "preference",
                                        "fact",
                                        "task",
                                        "decision",
                                        "constraint",
                                        "relationship",
                                    ],
                                },
                                "summary": {"type": "string"},
                                "entities": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "confidence": {"type": "number"},
                            },
                            "required": ["type", "summary"],
                        },
                    },
                },
                "required": ["events"],
            },
        },
    }
]


def _build_source(channel: str, tool_hints: list[str]) -> str:
    """Build a provenance source string from channel and tool hints.

    Returns a comma-separated string: channel first, then sorted unique
    tool hints.  E.g. ``"cli,exec:obsidian,read_file"``.
    """
    ch = channel or "unknown"
    parts = [ch] + sorted(set(tool_hints))
    return ",".join(p for p in parts if p)


class MicroExtractor:
    """Lightweight per-turn memory extraction.

    After each agent turn, extracts structured memory events from the
    user message + assistant response. Runs asynchronously in the
    background. Events are written to the same SQLite events table
    used by full consolidation.
    """

    def __init__(
        self,
        *,
        provider: LLMProvider,
        ingester: EventIngester,
        model: str = "gpt-4o-mini",
        enabled: bool = False,
    ) -> None:
        self._provider = provider
        self._ingester = ingester
        self._model = model
        self._enabled = enabled
        self._pending_tasks: set[asyncio.Task[None]] = set()

    async def submit(
        self,
        user_message: str,
        assistant_message: str,
        *,
        channel: str = "",
        tool_hints: list[str] | None = None,
        turn_timestamp: str = "",
    ) -> None:
        """Submit a turn for background extraction. Returns immediately."""
        if not self._enabled:
            return
        task = asyncio.create_task(
            self._extract_and_ingest(
                user_message,
                assistant_message,
                channel=channel,
                tool_hints=tool_hints or [],
                turn_timestamp=turn_timestamp,
            )
        )
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    async def _extract_and_ingest(
        self,
        user_message: str,
        assistant_message: str,
        *,
        channel: str,
        tool_hints: list[str],
        turn_timestamp: str,
    ) -> None:
        """Call LLM to extract events, then ingest them."""
        try:
            prompt = prompts.get("micro_extract")
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_message},
            ]
            response = await self._provider.chat(
                messages=messages,
                model=self._model,
                tools=_MICRO_EXTRACT_TOOL,
                temperature=0.0,
                max_tokens=500,
            )
            raw_events = self._parse_events(response)
            if not raw_events:
                return
            events = [MemoryEvent.from_dict(e) for e in raw_events]
            if channel or tool_hints:
                source = _build_source(channel, tool_hints)
                for event in events:
                    event.source = source
                    if turn_timestamp:
                        event.metadata["source_timestamp"] = turn_timestamp
            self._ingester.append_events(events)
            logger.info("Micro-extraction: {} event(s) ingested", len(events))
        except Exception:  # crash-barrier: best-effort background extraction
            logger.opt(exception=True).warning("Micro-extraction failed")

    @staticmethod
    def _parse_events(response: Any) -> list[dict[str, Any]]:
        """Extract events list from LLM tool call response."""
        if not response.tool_calls:
            return []
        tc = response.tool_calls[0]
        args = tc.arguments
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (json.JSONDecodeError, TypeError):
                return []
        if not isinstance(args, dict):
            return []
        events = args.get("events", [])
        if not isinstance(events, list):
            return []
        return [e for e in events if isinstance(e, dict) and e.get("type") and e.get("summary")]
