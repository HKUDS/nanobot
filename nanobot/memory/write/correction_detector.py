"""Pure-function correction detection from user text.

Extracts explicit preference corrections ("I prefer X not Y") and fact
corrections ("X is Y not Z") using regex patterns.  These are standalone
text-processing functions with no instance state.
"""

from __future__ import annotations

import re

__all__ = [
    "clean_phrase",
    "extract_fact_corrections",
    "extract_preference_corrections",
]


def clean_phrase(value: str) -> str:
    """Strip whitespace, punctuation, and leading articles from a phrase."""
    cleaned = re.sub(r"\s+", " ", value.strip().strip(".,;:!?\"'()[]{}"))
    cleaned = re.sub(r"^(?:the|a|an)\s+", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def extract_preference_corrections(content: str) -> list[tuple[str, str]]:
    """Extract ``(new_value, old_value)`` pairs from preference correction text.

    Matches patterns like "I prefer X not Y" and "not X but I prefer Y".
    Returns deduplicated pairs with cleaned phrases.
    """
    text = str(content or "").strip()
    if not text:
        return []

    matches: list[tuple[str, str]] = []
    patterns = (
        (
            r"(?:correction\s*[:,-]?\s*)?(?:i\s+(?:now\s+)?)?(?:prefer|want|use)\s+(.+?)\s*(?:,|;|\s+but)?\s*not\s+(.+?)(?:[.!?]|$)",
            "new_old",
        ),
        (
            r"(?:correction\s*[:,-]?\s*)?(?:not\s+)(.+?)\s*(?:,|;|\s+but)\s*(?:i\s+(?:now\s+)?)?(?:prefer|want|use)\s+(.+?)(?:[.!?]|$)",
            "old_new",
        ),
    )

    for pattern, order in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            if order == "new_old":
                new_value = clean_phrase(match.group(1))
                old_value = clean_phrase(match.group(2))
            else:
                old_value = clean_phrase(match.group(1))
                new_value = clean_phrase(match.group(2))
            if not new_value or not old_value:
                continue
            if clean_phrase(new_value).lower() == clean_phrase(old_value).lower():
                continue
            matches.append((new_value, old_value))

    dedup: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for new_value, old_value in matches:
        key = (new_value.lower(), old_value.lower())
        if key in seen:
            continue
        seen.add(key)
        dedup.append((new_value, old_value))
    return dedup


def extract_fact_corrections(content: str) -> list[tuple[str, str]]:
    """Extract ``(new_fact, old_fact)`` pairs from fact correction text.

    Matches patterns like "X is Y not Z" and "X is not Y, it is Z".
    Returns deduplicated pairs with subject embedded in each fact string.
    """
    text = str(content or "").strip()
    if not text:
        return []

    matches: list[tuple[str, str]] = []
    patterns = (
        r"(?:correction\s*[:,-]?\s*)?(?:actually\s+)?([a-zA-Z0-9_\- ]{2,80}?)\s+is\s+(.+?)\s*(?:,|;|\s+but)?\s*not\s+(.+?)(?:[.!?]|$)",
        r"(?:correction\s*[:,-]?\s*)?(?:actually\s+)?([a-zA-Z0-9_\- ]{2,80}?)\s+is\s+not\s+(.+?)\s*(?:,|;|\s+but)\s*(?:it(?:'s| is)|is)\s+(.+?)(?:[.!?]|$)",
    )

    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            subject = clean_phrase(match.group(1))
            if "prefer" in subject.lower() or "want" in subject.lower() or "use" in subject.lower():
                continue

            if "is not" in pattern:
                old_value = clean_phrase(match.group(2))
                new_value = clean_phrase(match.group(3))
            else:
                new_value = clean_phrase(match.group(2))
                old_value = clean_phrase(match.group(3))

            if not subject or not new_value or not old_value:
                continue

            new_fact = f"{subject} is {new_value}"
            old_fact = f"{subject} is {old_value}"
            if clean_phrase(new_fact).lower() == clean_phrase(old_fact).lower():
                continue
            matches.append((new_fact, old_fact))

    dedup: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for new_value, old_value in matches:
        key = (new_value.lower(), old_value.lower())
        if key in seen:
            continue
        seen.add(key)
        dedup.append((new_value, old_value))
    return dedup
