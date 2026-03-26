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

from typing import Any

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
