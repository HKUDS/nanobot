"""Lightweight BM25-based skill router for nanobot.

Reduces system prompt size by selecting only the most relevant skills
for a given user message, instead of listing all skills every turn.

Zero external dependencies — pure Python BM25-lite scoring.

Usage::

    from nanobot.agent.skill_router import SkillRouter

    router = SkillRouter(skills)
    relevant = router.route("帮我看看那个 PR 的 CI 有没有过", top_k=3)
"""

from __future__ import annotations

import math
import re
from typing import Any


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

# CJK ranges as explicit codepoint tuples (avoids \u4+ digit regex issues).
_CJK_RANGES: list[tuple[int, int]] = [
    (0x4E00, 0x9FFF),    # CJK Unified Ideographs
    (0x3400, 0x4DBF),    # CJK Unified Ideographs Extension A
    (0x20000, 0x2A6DF),  # CJK Unified Ideographs Extension B
    (0x2A700, 0x2B73F),  # CJK Unified Ideographs Extension C
    (0x2B740, 0x2B81F),  # CJK Unified Ideographs Extension D
    (0x2B820, 0x2CEAF),  # CJK Unified Ideographs Extension E
]


def _is_cjk(char: str) -> bool:
    """Check if a character is CJK (Chinese/Japanese/Korean)."""
    cp = ord(char)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


# English words and numbers (non-CJK tokens).
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]+|\d+")


def tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase tokens.

    Uses English words/numbers and CJK bigrams (2-char chunks).
    Single CJK characters are dropped — they're too common for BM25
    (e.g. 一, 下, 中, 的 match nearly every Chinese text).
    Punctuation and whitespace are dropped.
    """
    tokens: list[str] = []

    # English compounds and numbers
    for match in _WORD_RE.finditer(text):
        tokens.append(match.group().lower())

    # CJK bigrams (2-char sliding window)
    cjk_chars = [ch for ch in text if _is_cjk(ch)]
    for i in range(len(cjk_chars) - 1):
        tokens.append(cjk_chars[i] + cjk_chars[i + 1])

    return tokens


# ---------------------------------------------------------------------------
# BM25-lite scoring
# ---------------------------------------------------------------------------

# Okapi BM25 constants
_K1 = 1.5  # Term frequency saturation
_B = 0.75  # Length normalization


class SkillRouter:
    """Routes user messages to the most relevant skills using BM25-lite.

    Parameters
    ----------
    skills : list[dict]
        Skill entries from ``SkillsLoader.list_skills()``. Each dict must have
        ``"name"`` and ``"path"`` keys. Optionally includes ``"description"``
        and ``"triggers"`` extracted from frontmatter.
    always_skills : set[str] | None
        Skill names that should always be included regardless of routing.
        These are excluded from the routing pool and appended to results.
    """

    def __init__(
        self,
        skills: list[dict[str, Any]],
        always_skills: set[str] | None = None,
    ) -> None:
        self.skills = skills
        self.always_skills = always_skills or set()

        # Build index
        self._skill_tokens: dict[str, list[str]] = {}
        self._skill_tf: dict[str, dict[str, int]] = {}
        self._doc_lens: dict[str, int] = {}
        self._doc_count = 0

        for skill in skills:
            name = skill["name"]
            if name in self.always_skills:
                continue  # Skip always-on skills from routing pool

            corpus_text = self._build_corpus(skill)
            tokens = tokenize(corpus_text)
            self._skill_tokens[name] = tokens
            self._skill_tf[name] = _compute_tf(tokens)
            self._doc_lens[name] = len(tokens)
            self._doc_count += 1

        self._avg_dl = (
            sum(self._doc_lens.values()) / len(self._doc_lens)
            if self._doc_lens
            else 1.0
        )

    @staticmethod
    def _build_corpus(skill: dict[str, Any]) -> str:
        """Build searchable corpus from skill metadata."""
        parts = [skill.get("name", "")]

        desc = skill.get("description", "")
        if desc:
            parts.append(desc)

        # Include trigger words if available
        triggers = skill.get("triggers", [])
        if triggers:
            parts.append(" ".join(triggers))

        return " ".join(parts)

    def route(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Route a user message to the most relevant skills.

        Parameters
        ----------
        query : str
            The user's message text.
        top_k : int
            Maximum number of skills to return (default 5).
        min_score : float
            Minimum BM25 score threshold. Skills below this are excluded.

        Returns
        -------
        list[dict]
            Ranked list of skill dicts with an added ``"score"`` key.
            Always-on skills are appended at the end if not already included.
        """
        if not query.strip() or not self._doc_count:
            return self._fallback(always_include=True)

        query_tokens = tokenize(query)
        if not query_tokens:
            return self._fallback(always_include=True)

        # Compute IDF for query terms
        idf: dict[str, float] = {}
        for qt in set(query_tokens):
            # Number of documents containing this term
            df = sum(
                1
                for tf_map in self._skill_tf.values()
                if qt in tf_map
            )
            if df > 0:
                idf[qt] = math.log(
                    (self._doc_count - df + 0.5) / (df + 0.5) + 1.0
                )
            else:
                idf[qt] = 0.0

        # Score each skill
        scores: list[tuple[str, float]] = []
        for name, tf_map in self._skill_tf.items():
            dl = self._doc_lens[name]
            score = 0.0
            for qt in query_tokens:
                if qt not in tf_map:
                    continue
                tf = tf_map[qt]
                # BM25 scoring
                numerator = tf * (_K1 + 1)
                denominator = tf + _K1 * (
                    1.0 - _B + _B * dl / self._avg_dl
                )
                score += idf.get(qt, 0.0) * numerator / denominator

            # Exact name match bonus
            query_lower = query.lower()
            if name.lower() in query_lower or name.lower().replace("-", " ") in query_lower:
                score += 2.0

            if score >= min_score:
                scores.append((name, score))

        # Sort by score descending
        scores.sort(key=lambda x: -x[1])
        top_names = {name for name, _ in scores[:top_k]}

        # Build result list
        result: list[dict[str, Any]] = []
        skill_map = {s["name"]: s for s in self.skills}

        for name, score in scores[:top_k]:
            entry = dict(skill_map[name])
            entry["score"] = round(score, 4)
            result.append(entry)

        # Always-on skills that weren't in the top results
        for skill in self.skills:
            if skill["name"] in self.always_skills and skill["name"] not in top_names:
                entry = dict(skill)
                entry["score"] = -1.0  # Signal: always-included, not routed
                result.append(entry)

        return result

    def _fallback(self, always_include: bool = True) -> list[dict[str, Any]]:
        """Return all skills as fallback (empty query or no indexed skills)."""
        result = []
        for skill in self.skills:
            entry = dict(skill)
            if skill["name"] in self.always_skills:
                entry["score"] = -1.0
            else:
                entry["score"] = 0.0
            result.append(entry)
        return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_tf(tokens: list[str]) -> dict[str, int]:
    """Compute term frequency map for a token list."""
    tf: dict[str, int] = {}
    for token in tokens:
        tf[token] = tf.get(token, 0) + 1
    return tf


def extract_skill_keywords(frontmatter: dict[str, Any]) -> list[str]:
    """Extract extra routing keywords from SKILL.md frontmatter.

    Looks for common fields that hint at when to use the skill:
    ``trigger``, ``triggers``, ``keywords``, ``aliases``.
    """
    keywords: list[str] = []

    for key in ("trigger", "triggers", "keywords", "aliases", "tags"):
        val = frontmatter.get(key)
        if val is None:
            continue
        if isinstance(val, str):
            keywords.extend(val.split(","))
        elif isinstance(val, list):
            keywords.extend(str(v) for v in val)

    return [kw.strip() for kw in keywords if kw.strip()]
