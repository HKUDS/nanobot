"""Lightweight feedback detector — emoji, keyword, and /feedback command."""

from __future__ import annotations

import re
from typing import NamedTuple


class FeedbackSignal(NamedTuple):
    sentiment: str   # positive | negative | neutral
    trigger: str     # emoji_reaction | keyword | explicit_command


_POSITIVE_EMOJI = {"👍", "❤️", "🙏", "💯", "🎉", "👏", "😍", "🥰", "✅", "⭐"}
_NEGATIVE_EMOJI = {"👎", "😡", "😤", "🤦", "❌", "💩", "😞", "😒"}

_POSITIVE_KW = [
    r"\bthanks?\b", r"\bthank you\b", r"\bperfect\b", r"\bgreat job\b",
    r"\bwell done\b", r"\bawesome\b", r"\bexcellent\b", r"\bhelpful\b",
    r"\blove it\b", r"\bspot on\b", r"\bnailed it\b",
]
_NEGATIVE_KW = [
    r"\bthat'?s wrong\b", r"\bnot helpful\b", r"\bwrong answer\b",
    r"\bthat'?s not right\b", r"\bincorrect\b", r"\bbad answer\b",
    r"\buseless\b", r"\bterrible\b", r"\bhorrible\b", r"\bnot what i asked\b",
]

_POS_RE = re.compile("|".join(_POSITIVE_KW), re.IGNORECASE)
_NEG_RE = re.compile("|".join(_NEGATIVE_KW), re.IGNORECASE)
_FEEDBACK_CMD_RE = re.compile(r"^/feedback\b", re.IGNORECASE)


def detect_feedback(text: str) -> FeedbackSignal | None:
    """Return a FeedbackSignal if *text* looks like feedback, else None."""
    text = text.strip()
    if not text:
        return None

    if _FEEDBACK_CMD_RE.match(text):
        remainder = text[len("/feedback"):].strip()
        if _NEG_RE.search(remainder):
            return FeedbackSignal("negative", "explicit_command")
        if _POS_RE.search(remainder):
            return FeedbackSignal("positive", "explicit_command")
        return FeedbackSignal("neutral", "explicit_command")

    head = text[:20]
    for emoji in _POSITIVE_EMOJI:
        if emoji in head:
            return FeedbackSignal("positive", "emoji_reaction")
    for emoji in _NEGATIVE_EMOJI:
        if emoji in head:
            return FeedbackSignal("negative", "emoji_reaction")

    if _NEG_RE.search(text):
        return FeedbackSignal("negative", "keyword")
    if _POS_RE.search(text):
        return FeedbackSignal("positive", "keyword")

    return None
