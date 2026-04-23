"""Parsers that turn nanobot's existing LLM extraction outputs into MemoryCandidates.

Two channels are supported:

* :func:`parse_consolidator_bullets` — input is the raw bullet-list summary
  produced by :file:`nanobot/templates/agent/consolidator_archive.md`.
* :func:`parse_dream_phase1_tags` — input is the ``[USER]/[MEMORY]/[SOUL]``
  tagged analysis produced by :file:`nanobot/templates/agent/dream_phase1.md`.

Both intentionally have **no** dependency on ``mgp_client`` so they remain
unit-testable without the optional package.
"""

from __future__ import annotations

import re

from .models import ParsedFact


# Tag → (scope, type) mapping for Dream Phase 1 output.
#
# NOTE: ``SOUL`` maps to ``profile`` (not ``identity``) because the MGP
# spec's ``supported_memory_types`` set is ``profile / preference /
# episodic_event / semantic_fact / procedural_rule / relationship /
# checkpoint_pointer / artifact_summary`` — there is no ``identity``
# type. ``profile`` is the closest semantic match for SOUL.md content
# (stable agent persona / identity facts).
DREAM_TAG_TO_MGP: dict[str, tuple[str, str]] = {
    "USER": ("user", "preference"),
    "MEMORY": ("agent", "semantic_fact"),
    "SOUL": ("agent", "profile"),
}


_DREAM_TAG_RE = re.compile(r"^\[(USER|MEMORY|SOUL)\]\s+(.+?)\s*$")
# Lines we deliberately skip when parsing Dream phase-1 output.
_DREAM_IGNORED_TAGS = ("FILE-REMOVE", "SKILL", "SKIP")


# Heuristic keyword → (scope, type) buckets for consolidator bullet
# classification. The buckets follow the prompt's category labels in
# ``consolidator_archive.md``: User facts / Decisions / Solutions / Events /
# Preferences. Match order matters — preference wins over semantic_fact.
_PREFERENCE_HINTS = (
    "prefer",
    "preference",
    "favor",
    "favourite",
    "favorite",
    "likes",
    "dislikes",
    "always use",
    "always answer",
    "always reply",
    "communication style",
    "tone",
)
_EVENT_HINTS = (
    "deadline",
    "scheduled",
    "meeting",
    "occurred",
    "happened",
    "tomorrow",
    "next week",
    "planned",
)


def _classify_bullet(text: str) -> tuple[str, str, str | None]:
    """Return (scope, type, preference_value) for one bullet line.

    Default classification is ``("user", "semantic_fact", None)`` because
    nanobot's consolidator prompt explicitly targets *user-relevant* facts.
    Bullets that look like preferences or events are remapped accordingly.
    """
    lower = text.lower()
    if any(hint in lower for hint in _PREFERENCE_HINTS):
        # Try to extract the preference value after a "prefers ..." or
        # "always use ..." phrase. Fall back to the whole statement.
        m = re.search(
            r"(?:prefers|prefer|favors|favor|likes|always use|always answer|always reply)\s+(.+?)[\.;]?$",
            text,
            re.IGNORECASE,
        )
        value = m.group(1).strip() if m else text
        return "user", "preference", value
    if any(hint in lower for hint in _EVENT_HINTS):
        return "user", "episodic_event", None
    return "user", "semantic_fact", None


def parse_consolidator_bullets(summary: str, *, source_ref: str | None = None) -> list[ParsedFact]:
    """Split a consolidator summary into one ``ParsedFact`` per bullet.

    Empty input or the explicit ``(nothing)`` sentinel returns ``[]``.
    Lines that look like Markdown headers, ``[RAW]`` raw-archive markers,
    or "User said:" raw archive bodies are filtered out so we never write
    raw conversation transcripts to MGP.
    """
    if not summary:
        return []
    stripped = summary.strip()
    if not stripped or stripped.lower() == "(nothing)":
        return []
    # Don't write raw-archived turns; that's tail-end fallback content.
    if stripped.startswith("[RAW]"):
        return []

    facts: list[ParsedFact] = []
    for raw_line in stripped.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Strip common bullet leaders: "- foo", "* foo", "1. foo".
        m = re.match(r"^(?:[-*+]|\d+[.)])\s+(.+)$", line)
        if m:
            line = m.group(1).strip()
        # Drop section-style headings that the LLM occasionally emits.
        if line.startswith("#"):
            continue
        if not line:
            continue
        scope, mtype, pref_value = _classify_bullet(line)
        facts.append(
            ParsedFact(
                scope=scope,
                type=mtype,
                statement=line,
                preference_value=pref_value,
                source_ref=source_ref,
            )
        )
    return facts


def parse_dream_phase1_tags(analysis: str, *, source_ref: str | None = None) -> list[ParsedFact]:
    """Split Dream Phase-1 tagged output into one ``ParsedFact`` per relevant line.

    Recognized tags map via :data:`DREAM_TAG_TO_MGP`. Lines tagged
    ``[FILE-REMOVE]`` and ``[SKILL]`` are intentionally ignored in the MVP
    (Stage 2 may turn ``[FILE-REMOVE]`` into ``expire_memory`` calls).
    The ``[SKIP]`` sentinel from the prompt is also ignored.
    """
    if not analysis:
        return []
    facts: list[ParsedFact] = []
    for raw_line in analysis.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Quick reject for ignored / sentinel tags before regex.
        if any(line.startswith(f"[{t}") for t in _DREAM_IGNORED_TAGS):
            continue
        m = _DREAM_TAG_RE.match(line)
        if not m:
            continue
        tag, statement = m.group(1), m.group(2).strip()
        if not statement:
            continue
        scope, mtype = DREAM_TAG_TO_MGP[tag]
        facts.append(
            ParsedFact(
                scope=scope,
                type=mtype,
                statement=statement,
                source_ref=source_ref,
            )
        )
    return facts
