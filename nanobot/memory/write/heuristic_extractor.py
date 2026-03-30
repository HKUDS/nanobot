"""Heuristic (non-LLM) extraction of entities, triples, and memory events.

These functions provide a lightweight fallback when LLM-based extraction is
unavailable or fails.  All functions are stateless and operate on plain text
and dicts — no class or instance state required.
"""

from __future__ import annotations

import re
from typing import Any, Callable

# Words to skip when extracting single-capitalized-word entities
COMMON_WORDS: frozenset[str] = frozenset(
    {
        "the",
        "this",
        "that",
        "then",
        "than",
        "they",
        "them",
        "there",
        "these",
        "those",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "whose",
        "why",
        "how",
        "also",
        "and",
        "but",
        "for",
        "from",
        "into",
        "just",
        "like",
        "not",
        "only",
        "some",
        "such",
        "very",
        "will",
        "with",
        "would",
        "could",
        "should",
        "about",
        "after",
        "before",
        "been",
        "being",
        "have",
        "here",
        "more",
        "most",
        "much",
        "over",
        "same",
        "still",
        "each",
        "even",
        "every",
        "other",
    }
)

TYPE_CONFIDENCE: dict[str, float] = {
    "preference": 0.70,
    "constraint": 0.65,
    "decision": 0.55,
    "task": 0.50,
    "relationship": 0.60,
    "fact": 0.45,
}

# Pattern -> (subject group, predicate, object group)
TRIPLE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(\b\w[\w\s]{0,30}?)\s+works?\s+on\s+(\b\w[\w\s]{0,30})", re.I), "WORKS_ON"),
    (
        re.compile(r"(\b\w[\w\s]{0,30}?)\s+works?\s+with\s+(\b\w[\w\s]{0,30})", re.I),
        "WORKS_WITH",
    ),
    (re.compile(r"(\b\w[\w\s]{0,30}?)\s+uses?\s+(\b\w[\w\s]{0,30})", re.I), "USES"),
    (
        re.compile(r"(\b\w[\w\s]{0,30}?)\s+(?:is|are)\s+(?:in|at|from)\s+(\b\w[\w\s]{0,30})", re.I),
        "LOCATED_IN",
    ),
    (
        re.compile(r"(\b\w[\w\s]{0,30}?)\s+(?:caused|causes)\s+(\b\w[\w\s]{0,30})", re.I),
        "CAUSED_BY",
    ),
    (
        re.compile(r"(\b\w[\w\s]{0,30}?)\s+depends?\s+on\s+(\b\w[\w\s]{0,30})", re.I),
        "DEPENDS_ON",
    ),
    (re.compile(r"(\b\w[\w\s]{0,30}?)\s+owns?\s+(\b\w[\w\s]{0,30})", re.I), "OWNS"),
    (
        re.compile(
            r"(\b\w[\w\s]{0,30}?)\s+(?:is|are)\s+constrained\s+by\s+(\b\w[\w\s]{0,30})", re.I
        ),
        "CONSTRAINED_BY",
    ),
]


def extract_entities(text: str) -> list[str]:
    """Extract likely entity names from text via capitalized phrases and quoted strings."""
    entities: list[str] = []
    seen: set[str] = set()
    # Quoted strings (single or double)
    for match in re.finditer(r"""['"]([A-Za-z0-9_\- ]{2,60})['"]""", text):
        val = match.group(1).strip()
        if val.lower() not in seen:
            seen.add(val.lower())
            entities.append(val)
    # Capitalized multi-word phrases (e.g. "Google Chrome", "Project Alpha")
    for match in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", text):
        val = match.group(1).strip()
        if val.lower() not in seen:
            seen.add(val.lower())
            entities.append(val)
    # Single capitalized words that aren't sentence starters (preceded by space)
    for match in re.finditer(r"(?<=\s)([A-Z][a-z]{2,})\b", text):
        val = match.group(1).strip()
        if val.lower() not in seen and val.lower() not in COMMON_WORDS:
            seen.add(val.lower())
            entities.append(val)
    return entities[:10]


def extract_triples_heuristic(
    summary: str,
    entities: list[str],
    event_type: str,
) -> list[dict[str, str | float]]:
    """Extract subject-predicate-object triples from text via patterns.

    Also infers triples from entity pairs when the event type implies a
    relationship (e.g. *relationship* -> WORKS_WITH between first two entities).
    """
    triples: list[dict[str, str | float]] = []
    seen: set[tuple[str, str, str]] = set()

    # Pattern-based extraction
    for pattern, predicate in TRIPLE_PATTERNS:
        for match in pattern.finditer(summary):
            subj = match.group(1).strip()
            obj = match.group(2).strip()
            if not subj or not obj or len(subj) < 2 or len(obj) < 2:
                continue
            key = (subj.lower(), predicate, obj.lower())
            if key not in seen:
                seen.add(key)
                triples.append(
                    {
                        "subject": subj,
                        "predicate": predicate,
                        "object": obj,
                        "confidence": 0.55,
                    }
                )

    # Infer from entity pairs + event type
    _type_predicates: dict[str, str] = {
        "relationship": "WORKS_WITH",
        "task": "WORKS_ON",
        "decision": "RELATED_TO",
    }
    if event_type in _type_predicates and len(entities) >= 2:
        pred = _type_predicates[event_type]
        subj, obj = entities[0], entities[1]
        key = (subj.lower(), pred, obj.lower())
        if key not in seen:
            seen.add(key)
            triples.append(
                {
                    "subject": subj,
                    "predicate": pred,
                    "object": obj,
                    "confidence": 0.45,
                }
            )

    return triples[:10]


def extract_events_heuristic(
    old_messages: list[dict[str, Any]],
    *,
    source_start: int,
    coerce_event_fn: Callable[..., dict[str, Any] | None],
    utc_now_iso_fn: Callable[[], str],
    default_profile_updates_fn: Callable[[], dict[str, list[str]]],
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """Full heuristic fallback pipeline for memory event extraction.

    Scans user messages for type-hint keywords and produces structured events
    plus profile update suggestions.
    """
    updates = default_profile_updates_fn()
    events: list[dict[str, Any]] = []

    type_hints = [
        ("preference", ("prefer", "i like", "i dislike", "my preference")),
        ("constraint", ("must", "cannot", "can't", "do not", "never")),
        ("decision", ("decided", "we will", "let's", "plan is")),
        ("task", ("todo", "next step", "please", "need to")),
        ("relationship", ("is my", "works with", "project lead", "manager")),
    ]

    for offset, message in enumerate(old_messages):
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        if message.get("role") != "user":
            continue
        text = content.strip()
        if len(text) < 8:
            continue
        lowered = text.lower()

        event_type = "fact"
        for candidate, needles in type_hints:
            if any(needle in lowered for needle in needles):
                event_type = candidate
                break

        summary = text if len(text) <= 220 else text[:217] + "..."
        entities = extract_entities(text)
        confidence = TYPE_CONFIDENCE.get(event_type, 0.45)
        triples = extract_triples_heuristic(text, entities, event_type)
        source_span = [source_start + offset, source_start + offset]
        event = coerce_event_fn(
            {
                "timestamp": message.get("timestamp") or utc_now_iso_fn(),
                "type": event_type,
                "summary": summary,
                "entities": entities,
                "salience": 0.55,
                "confidence": confidence,
                "triples": triples,
            },
            source_span=source_span,
        )
        if event:
            events.append(event)

        if event_type == "preference":
            updates["preferences"].append(summary)
        elif event_type == "constraint":
            updates["constraints"].append(summary)
        elif event_type == "relationship":
            updates["relationships"].append(summary)
        else:
            updates["stable_facts"].append(summary)

    for key in updates:
        updates[key] = list(dict.fromkeys(updates[key]))
    return events[:20], updates
