"""In-memory BM25 search over the tools available to an agent run."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterator
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from nanobot.agent.tools.base import Tool

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_WORD = re.compile(r"[^\W_]+")
_K1 = 1.2
_B = 0.75
_NAME_WEIGHT = 2


def _tokens(text: str) -> list[str]:
    words = _WORD.findall(_CAMEL_BOUNDARY.sub(" ", text).casefold())
    # Index adjacent pairs within each field: a specific phrase in the description
    # can distinguish an operation from tools with just one matching name token.
    return words + [f"{a} {b}" for a, b in zip(words, words[1:])]


def _parameter_text(schema: object) -> Iterator[str]:
    """Walk schema fields rather than indexing JSON keywords or example values."""
    if isinstance(schema, list):
        for branch in cast(list[object], schema):
            yield from _parameter_text(branch)
        return
    if not isinstance(schema, dict):
        return
    fields = cast(dict[str, object], schema)
    description = fields.get("description")
    if isinstance(description, str):
        yield description
    for key in ("properties", "$defs", "definitions"):
        children = fields.get(key)
        if isinstance(children, dict):
            for name, child in cast(dict[str, object], children).items():
                if key == "properties":
                    yield name
                yield from _parameter_text(child)
    for key in ("items", "prefixItems", "oneOf", "anyOf", "allOf", "additionalProperties"):
        if key in fields:
            yield from _parameter_text(fields[key])


class ToolSearchIndex:
    """Read-only index returning registered names, with ties ordered by name."""

    def __init__(self, tools: list[Tool]) -> None:
        self._postings: dict[str, list[tuple[str, int]]] = {}
        lengths: dict[str, int] = {}
        for tool in tools:
            name = tool.name
            # The transport namespace is shared by every registered MCP tool.
            name_tokens = _tokens(name.removeprefix("mcp_"))
            counts = Counter(name_tokens * _NAME_WEIGHT)
            counts.update(_tokens(tool.description))
            for text in _parameter_text(tool.parameters):
                counts.update(_tokens(text))
            lengths[name] = counts.total()
            for term, tf in counts.items():
                self._postings.setdefault(term, []).append((name, tf))

        avg_length = (sum(lengths.values()) or 1) / max(len(lengths), 1)
        self._length_norm = {
            name: _K1 * (1 - _B + _B * length / avg_length) for name, length in lengths.items()
        }

    def search(self, query: str, limit: int = 5) -> list[str]:
        """Rank only matching tools; a verbatim registered name always wins."""
        if limit <= 0:
            return []
        scores: dict[str, float] = {}
        for term in sorted(set(_tokens(query))):
            matches = self._postings.get(term)
            if not matches:
                continue
            df = len(matches)
            idf = math.log1p((len(self._length_norm) - df + 0.5) / (df + 0.5))
            for name, tf in matches:
                weight = tf * (_K1 + 1) / (tf + self._length_norm[name])
                scores[name] = scores.get(name, 0.0) + idf * weight

        exact = query.strip()
        if exact in self._length_norm:
            scores[exact] = math.inf
        return sorted(scores, key=lambda name: (-scores[name], name))[:limit]
