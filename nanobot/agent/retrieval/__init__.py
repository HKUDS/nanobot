"""Lightweight retrieval algorithms for agent memory search."""

import re

from nanobot.agent.retrieval.bm25 import BM25Retriever
from nanobot.agent.retrieval.tfidf import TFIDFRetriever

__all__ = ["BM25Retriever", "TFIDFRetriever", "tokenize"]


def tokenize(text: str) -> list[str]:
    """Split text into lowercase alphanumeric tokens."""
    return [w for w in re.split(r"\W+", text.lower()) if w]
