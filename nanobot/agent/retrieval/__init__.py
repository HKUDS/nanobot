"""Lightweight retrieval algorithms for agent memory search."""

import re

from nanobot.agent.retrieval.bm25 import BM25Retriever

__all__ = ["BM25Retriever", "tokenize"]


def tokenize(text: str) -> list[str]:
    """Split text into lowercase alphanumeric tokens."""
    return [w for w in re.split(r"\W+", text.lower()) if w]
