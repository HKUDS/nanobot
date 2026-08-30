"""Detect a turn that announces an action it never performed.

Reported as #1697: the agent replied "I am querying now", "locating and
executing", "results coming shortly" -- and issued no tool call at all. The user
had to answer "there are no results" before the agent conceded that the query had
never started.

Nothing in the loop catches this. The turn returns a fluent, on-topic reply and
raises nothing, so every existing check passes. The 353 test files in this
repository cover many failure modes; none covers a turn that claims work it did
not do.

The check needs no model and makes no judgement about the text. If an assistant
message asserts that it is performing or has performed an action, and the turn
carried zero tool calls, the assertion cannot be true. That is a property of the
transcript, which is why it can run on every turn without producing noise.

It is deliberately narrow. It fires only on first-person claims of action in
progress or already done. Offers, questions, plans and conditionals -- "shall I
run it?", "I could write a script" -- claim nothing and are ignored.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import cast

# First-person assertions that an action is under way or finished. The reported
# case is Chinese and the framework is used in both languages, so both are
# covered; the Chinese patterns are taken from the transcript in #1697.
_CLAIM_PATTERNS: tuple[str, ...] = (
    r"\b(?:i am|i'm) (?:now )?(?:querying|running|executing|fetching|searching|checking|calling)\b",
    r"\b(?:i|we) (?:have )?(?:just )?(?:ran|executed|fetched|retrieved|queried|called|completed)\b",
    r"\b(?:running|executing|fetching|querying) (?:it |this |that )?now\b",
    r"\blet me (?:run|execute|fetch|query|check) (?:it|this|that)\b[^.]*\b(?:now|immediately)\b",
    r"\b(?:results?|output) (?:will be|are) (?:back|returned|ready) (?:shortly|soon|in a moment)\b",
    r"正在(?:执行|查询|定位|运行)",
    r"我(?:立即|马上|现在就)(?:为您|给你)?(?:查询|执行|运行|开始)",
    r"稍等[—\-, ]*结果(?:即将|马上)?返回",
    r"已(?:执行|完成|查询)",
)

# Phrases that explicitly claim nothing. A message built only from these is an
# offer, not a report, and must not be flagged.
_OFFER_PATTERNS: tuple[str, ...] = (
    r"\b(?:shall|should) i\b",
    r"\bwould you like me to\b",
    r"\bdo you want me to\b",
    r"\bi (?:can|could|will be able to)\b",
    r"\bif you (?:want|confirm|approve)\b",
    r"需要我",
    r"是否需要",
    r"只需你回复",
    r"我可以",
)

_CLAIM_RE = tuple(re.compile(p, re.IGNORECASE) for p in _CLAIM_PATTERNS)
_OFFER_RE = tuple(re.compile(p, re.IGNORECASE) for p in _OFFER_PATTERNS)

_OFFER_WINDOW = 40  # characters either side of a claim to look for a hedge


def _text_of(content: object) -> str:
    """Flatten assistant content, which may be a string or a list of blocks.

    Narrowed explicitly rather than by duck typing: a bare Iterable leaves the
    element type unknown, which basedpyright rejects, and a str is itself
    iterable so it has to be handled before the sequence branch.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, (list, tuple)):
        return ""
    parts: list[str] = []
    for block in cast("Sequence[object]", content):
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            value = cast("dict[str, object]", block).get("text")
            if isinstance(value, str):
                parts.append(value)
    return "\n".join(parts)


def unsupported_action_claims(
    content: object,
    tool_calls: Sequence[object] | None,
) -> list[str]:
    """Return the action claims this message makes without having acted.

    Empty when the message claims nothing, when the turn did make tool calls, or
    when every claim sits inside an offer.
    """
    if tool_calls:
        return []

    text = _text_of(content)
    if not text:
        return []

    claims: list[str] = []
    for pattern in _CLAIM_RE:
        for match in pattern.finditer(text):
            window = text[max(0, match.start() - _OFFER_WINDOW):
                          match.end() + _OFFER_WINDOW]
            if any(offer.search(window) for offer in _OFFER_RE):
                continue  # phrased as an offer, not a report
            claims.append(match.group(0))
    return claims
