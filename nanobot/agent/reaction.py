"""Emoji reaction classification utilities.

Moved from ``bus/events.py`` per the module boundary rule: the bus layer must
be a pure data transport; sentiment classification belongs in the agent layer.
"""

from __future__ import annotations

_POSITIVE_EMOJIS: frozenset[str] = frozenset(
    {
        "\U0001f44d",
        "+1",
        "thumbsup",
        "THUMBSUP",
        "\u2764",
        "heart",
        "HEART",
        "\U0001f389",
        "tada",
        "\U0001f44f",
        "clap",
        "\U0001f60d",
        "star",
        "\u2b50",
        "ok",
        "OK",
        "DONE",
        "\u2705",
        "check",
        "white_check_mark",
    }
)
_NEGATIVE_EMOJIS: frozenset[str] = frozenset(
    {
        "\U0001f44e",
        "-1",
        "thumbsdown",
        "THUMBSDOWN",
        "\U0001f612",
        "\U0001f620",
        "angry",
        "confused",
        "\U0001f615",
        "\U0001f641",
        "disappointed",
    }
)


def classify_reaction(emoji: str) -> str | None:
    """Map an emoji string to ``'positive'``, ``'negative'``, or ``None`` if ambiguous."""
    e = emoji.strip().lower()
    if e in _POSITIVE_EMOJIS or emoji in _POSITIVE_EMOJIS:
        return "positive"
    if e in _NEGATIVE_EMOJIS or emoji in _NEGATIVE_EMOJIS:
        return "negative"
    return None
