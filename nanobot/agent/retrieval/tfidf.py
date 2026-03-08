"""TF-IDF retrieval with cosine similarity scoring."""

from __future__ import annotations

import math
from collections import Counter


class TFIDFRetriever:
    """Rank documents against a query using TF-IDF weighted cosine similarity.

    Usage::

        retriever = TFIDFRetriever()
        retriever.index(["the cat sat on the mat", "the dog barked"])
        results = retriever.search("cat")
        # results: [(doc_index, score), ...]
    """

    def __init__(self) -> None:
        self._n_docs: int = 0
        self._vocab: dict[str, int] = {}
        self._idf: dict[str, float] = {}
        self._doc_vectors: list[dict[str, float]] = []

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def index(self, documents: list[str]) -> None:
        """Tokenize and build TF-IDF vectors for a corpus.

        Calling ``index`` again replaces the previous corpus entirely.
        """
        from nanobot.agent.retrieval import tokenize

        tokenized = [tokenize(doc) for doc in documents]
        self._n_docs = len(tokenized)

        if self._n_docs == 0:
            self._vocab = {}
            self._idf = {}
            self._doc_vectors = []
            return

        # Build vocabulary and document frequencies.
        df: dict[str, int] = {}
        for tokens in tokenized:
            for term in set(tokens):
                df[term] = df.get(term, 0) + 1

        self._vocab = {term: idx for idx, term in enumerate(df)}
        self._idf = {
            term: math.log(self._n_docs / doc_freq)
            for term, doc_freq in df.items()
        }

        # Pre-compute document TF-IDF vectors (sparse, as dicts).
        self._doc_vectors = [
            self._build_tfidf_vector(tokens) for tokens in tokenized
        ]

    # ------------------------------------------------------------------
    # Searching
    # ------------------------------------------------------------------

    def search(self, query: str, top_k: int = 5) -> list[tuple[int, float]]:
        """Return the *top_k* documents most relevant to *query*.

        Each result is a ``(doc_index, score)`` tuple sorted by descending
        cosine similarity.  Documents with a score of zero are excluded.
        """
        if self._n_docs == 0:
            return []

        from nanobot.agent.retrieval import tokenize

        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        query_vec = self._build_tfidf_vector(query_tokens)
        if not query_vec:
            return []

        scores: list[tuple[int, float]] = []
        for idx, doc_vec in enumerate(self._doc_vectors):
            sim = self._cosine_similarity(query_vec, doc_vec)
            if sim > 0:
                scores.append((idx, sim))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_tfidf_vector(self, tokens: list[str]) -> dict[str, float]:
        """Build a sparse TF-IDF vector from a token list."""
        tf = Counter(tokens)
        return {
            term: count * self._idf.get(term, 0.0)
            for term, count in tf.items()
            if self._idf.get(term, 0.0) > 0
        }

    @staticmethod
    def _cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
        """Cosine similarity between two sparse vectors."""
        # Iterate over the smaller dict for efficiency.
        if len(a) > len(b):
            a, b = b, a

        dot = sum(v * b[k] for k, v in a.items() if k in b)
        if dot == 0:
            return 0.0

        norm_a = math.sqrt(sum(v * v for v in a.values()))
        norm_b = math.sqrt(sum(v * v for v in b.values()))
        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot / (norm_a * norm_b)
