"""BM25 (Okapi BM25) retrieval over a list of text documents."""

from __future__ import annotations

import math
from collections import Counter


class BM25Retriever:
    """Rank documents against a query using the Okapi BM25 scoring function.

    Usage::

        retriever = BM25Retriever()
        retriever.index(["the cat sat on the mat", "the dog barked"])
        results = retriever.search("cat")
        # results: [(doc_index, score), ...]
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b

        self._corpus_tokens: list[list[str]] = []
        self._doc_freqs: dict[str, int] = {}
        self._doc_lens: list[int] = []
        self._avgdl: float = 0.0
        self._n_docs: int = 0

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def index(self, documents: list[str]) -> None:
        """Tokenize and index a corpus of documents.

        Calling ``index`` again replaces the previous corpus entirely.
        """
        from nanobot.agent.retrieval import tokenize

        self._corpus_tokens = [tokenize(doc) for doc in documents]
        self._n_docs = len(self._corpus_tokens)
        self._doc_lens = [len(tokens) for tokens in self._corpus_tokens]
        self._avgdl = (
            sum(self._doc_lens) / self._n_docs if self._n_docs else 0.0
        )

        # Document frequency: how many docs contain each term.
        df: dict[str, int] = {}
        for tokens in self._corpus_tokens:
            for term in set(tokens):
                df[term] = df.get(term, 0) + 1
        self._doc_freqs = df

    # ------------------------------------------------------------------
    # Searching
    # ------------------------------------------------------------------

    def search(self, query: str, top_k: int = 5) -> list[tuple[int, float]]:
        """Return the *top_k* documents most relevant to *query*.

        Each result is a ``(doc_index, score)`` tuple sorted by descending
        score.  Documents with a score of zero are excluded.
        """
        if self._n_docs == 0:
            return []

        from nanobot.agent.retrieval import tokenize

        query_terms = tokenize(query)
        if not query_terms:
            return []

        scores: list[tuple[int, float]] = []
        for idx, doc_tokens in enumerate(self._corpus_tokens):
            score = self._score_document(query_terms, doc_tokens, idx)
            if score > 0:
                scores.append((idx, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _idf(self, term: str) -> float:
        """Inverse document frequency with smoothing."""
        df = self._doc_freqs.get(term, 0)
        return math.log(
            (self._n_docs - df + 0.5) / (df + 0.5) + 1.0
        )

    def _score_document(
        self,
        query_terms: list[str],
        doc_tokens: list[str],
        doc_idx: int,
    ) -> float:
        doc_len = self._doc_lens[doc_idx]
        tf_map = Counter(doc_tokens)
        score = 0.0

        for term in query_terms:
            tf = tf_map.get(term, 0)
            if tf == 0:
                continue
            idf = self._idf(term)
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (
                1 - self.b + self.b * doc_len / self._avgdl
            )
            score += idf * numerator / denominator

        return score
