"""Tool schemas used by memory consolidation and event extraction."""

from __future__ import annotations

_SAVE_MEMORY_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "Save the memory consolidation result to persistent storage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "history_entry": {
                        "type": "string",
                        "description": "A paragraph (2-5 sentences) summarizing key events/decisions/topics. "
                        "Start with [YYYY-MM-DD HH:MM]. Include detail useful for grep search.",
                    },
                    "memory_update": {
                        "type": "string",
                        "description": "Full updated long-term memory as markdown. Include all existing "
                        "facts plus new ones. Return unchanged if nothing new.",
                    },
                },
                "required": ["history_entry", "memory_update"],
            },
        },
    }
]


_SAVE_EVENTS_TOOL = [
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
