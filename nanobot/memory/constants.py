"""Tool schemas used by memory consolidation and event extraction."""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Domain constants — single source of truth for the memory subsystem.
# All consumers import from here. No re-definitions elsewhere.
# ---------------------------------------------------------------------------

PROFILE_KEYS: tuple[str, ...] = (
    "preferences",
    "stable_facts",
    "active_projects",
    "relationships",
    "constraints",
)

EVENT_TYPES: frozenset[str] = frozenset(
    {"preference", "fact", "task", "decision", "constraint", "relationship"}
)
MEMORY_TYPES: frozenset[str] = frozenset({"semantic", "episodic", "reflection"})
MEMORY_STABILITY: frozenset[str] = frozenset({"high", "medium", "low"})

# Profile belief statuses
PROFILE_STATUS_ACTIVE: str = "active"
PROFILE_STATUS_CONFLICTED: str = "conflicted"
PROFILE_STATUS_STALE: str = "stale"

# Conflict resolution statuses
CONFLICT_STATUS_OPEN: str = "open"
CONFLICT_STATUS_NEEDS_USER: str = "needs_user"
CONFLICT_STATUS_RESOLVED: str = "resolved"

# Episodic event statuses
EPISODIC_STATUS_OPEN: str = "open"
EPISODIC_STATUS_RESOLVED: str = "resolved"

_SAVE_EVENTS_TOOL: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "save_events",
            "description": "Extract structured memory events and profile updates from conversation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "events": {
                        "type": "array",
                        "description": "Notable events extracted from conversation.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "timestamp": {"type": "string"},
                                "type": {
                                    "type": "string",
                                    "description": "preference|fact|task|decision|constraint|relationship",
                                },
                                "summary": {"type": "string"},
                                "entities": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "salience": {"type": "number"},
                                "confidence": {"type": "number"},
                                "ttl_days": {"type": "integer"},
                                "triples": {
                                    "type": "array",
                                    "description": (
                                        "Entity relationship triples extracted from this event. "
                                        "Predicates: WORKS_ON, WORKS_WITH, USES, LOCATED_IN, "
                                        "CAUSED_BY, RELATED_TO, OWNS, DEPENDS_ON, CONSTRAINED_BY."
                                    ),
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "subject": {"type": "string"},
                                            "predicate": {"type": "string"},
                                            "object": {"type": "string"},
                                            "confidence": {"type": "number"},
                                        },
                                        "required": ["subject", "predicate", "object"],
                                    },
                                },
                            },
                            "required": ["type", "summary"],
                        },
                    },
                    "profile_updates": {
                        "type": "object",
                        "properties": {
                            "preferences": {"type": "array", "items": {"type": "string"}},
                            "stable_facts": {"type": "array", "items": {"type": "string"}},
                            "active_projects": {"type": "array", "items": {"type": "string"}},
                            "relationships": {"type": "array", "items": {"type": "string"}},
                            "constraints": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
                "required": ["events", "profile_updates"],
            },
        },
    }
]


# -- Combined single-tool schema for one-call consolidation (Task 6) ----------

_CONSOLIDATE_MEMORY_TOOL: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "consolidate_memory",
            "description": (
                "Consolidate conversation into memory: history summary, "
                "structured events, and profile updates."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "history_entry": {
                        "type": "string",
                        "description": (
                            "2-5 sentence summary of key events, decisions, and topics discussed."
                        ),
                    },
                    "events": _SAVE_EVENTS_TOOL[0]["function"]["parameters"]["properties"][
                        "events"
                    ],
                    "profile_updates": _SAVE_EVENTS_TOOL[0]["function"]["parameters"]["properties"][
                        "profile_updates"
                    ],
                },
                "required": ["history_entry", "events"],
            },
        },
    }
]
