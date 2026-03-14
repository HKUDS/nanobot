"""Hybrid memory search: TF-IDF vector + BM25 keyword.

Provides semantic search over MEMORY.md and daily memory files using a
simplified but equivalent approach to OpenClaw's hybrid search:
  - TF-IDF cosine similarity (replaces embedding vector search, weight 0.7)
  - BM25 keyword scoring (replaces FTS5, weight 0.3)
  - Chunks split by markdown headings (replaces sliding window)

Reference: OpenClaw src/memory/manager.ts
Reference: OpenClaw src/memory/hybrid.ts  mergeHybridResults()
Reference: docs/concepts/memory.md  "Hybrid search"
"""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

from loguru import logger


# Search defaults (aligned with OpenClaw)
SEARCH_MAX_RESULTS = 6
SEARCH_MIN_SCORE = 0.35
SEARCH_MAX_SNIPPET_CHARS = 700
HYBRID_VECTOR_WEIGHT = 0.7
HYBRID_TEXT_WEIGHT = 0.3


def tokenize(text: str) -> list[str]:
    """Tokenize: lowercase + split on non-alphanumeric. Keep Chinese single chars and 2+ char tokens."""
    return [
        t for t in re.findall(r"[a-z0-9\u4e00-\u9fff]+", text.lower())
        if len(t) > 1 or "\u4e00" <= t <= "\u9fff"
    ]


def cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    """Sparse vector cosine similarity."""
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[k] * b[k] for k in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def bm25_score(
    query_tokens: list[str],
    doc_tokens: list[str],
    doc_freq: Counter,
    n_docs: int,
    k1: float = 1.2,
    b: float = 0.75,
    avgdl: float = 100.0,
) -> float:
    """Single-document Okapi BM25 score.

    Reference: OpenClaw uses SQLite FTS5 built-in BM25; this is equivalent.
    """
    dl = len(doc_tokens)
    tf_doc = Counter(doc_tokens)
    score = 0.0
    for term in set(query_tokens):
        tf = tf_doc.get(term, 0)
        if tf == 0:
            continue
        df = doc_freq.get(term, 0)
        idf = math.log((n_docs - df + 0.5) / (df + 0.5) + 1.0)
        tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / max(avgdl, 1)))
        score += idf * tf_norm
    return score


class MemorySearchIndex:
    """Builds and searches a memory chunk index.

    Collects .md files from workspace, splits into heading-based chunks,
    and provides hybrid TF-IDF + BM25 search.

    Reference: OpenClaw src/memory/manager.ts  MemoryIndexManager
    """

    def __init__(self, workspace_dir: Path):
        self.workspace_dir = workspace_dir
        self.memory_dir = workspace_dir / "memory"

    def _collect_files(self) -> list[Path]:
        """Collect all indexable .md files from workspace."""
        files: list[Path] = []
        for name in ("MEMORY.md", "memory.md"):
            p = self.workspace_dir / name
            if p.exists() and not p.is_symlink():
                files.append(p)
                break
        if self.memory_dir.exists():
            for md in sorted(self.memory_dir.glob("**/*.md"), reverse=True):
                if not md.is_symlink():
                    files.append(md)
        return files

    def _chunk_file(self, path: Path) -> list[dict]:
        """Split file into chunks by markdown headings.

        Reference: OpenClaw src/memory/internal.ts  chunkMarkdown()
        """
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            return []

        rel = str(path.relative_to(self.workspace_dir))
        lines = content.split("\n")
        chunks: list[dict] = []
        buf: list[str] = []
        buf_start = 1

        for i, line in enumerate(lines):
            if line.startswith("#") and buf:
                text = "\n".join(buf).strip()
                if text:
                    chunks.append({
                        "path": rel,
                        "text": text,
                        "startLine": buf_start,
                        "endLine": buf_start + len(buf) - 1,
                        "source": "memory",
                    })
                buf = [line]
                buf_start = i + 1
            else:
                buf.append(line)

        if buf:
            text = "\n".join(buf).strip()
            if text:
                chunks.append({
                    "path": rel,
                    "text": text,
                    "startLine": buf_start,
                    "endLine": buf_start + len(buf) - 1,
                    "source": "memory",
                })
        return chunks

    def build_index(self) -> list[dict]:
        """Build full chunk index from all memory files."""
        chunks: list[dict] = []
        for f in self._collect_files():
            chunks.extend(self._chunk_file(f))
        return chunks

    def search(
        self,
        query: str,
        *,
        max_results: int = SEARCH_MAX_RESULTS,
        min_score: float = SEARCH_MIN_SCORE,
    ) -> list[dict]:
        """Hybrid search: TF-IDF vector + BM25 keyword.

        Flow:
          1. Build full chunk index
          2. TF-IDF cosine similarity (vector search, weight 0.7)
          3. BM25 (keyword search, weight 0.3)
          4. finalScore = 0.7 * vectorScore + 0.3 * textScore
          5. Filter by min_score, take max_results

        Reference: OpenClaw src/memory/hybrid.ts  mergeHybridResults()
        """
        chunks = self.build_index()
        if not chunks:
            return []

        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        # Compute document frequencies and token lists
        doc_freq: Counter = Counter()
        all_tokens: list[list[str]] = []
        total_len = 0
        for c in chunks:
            toks = tokenize(c["text"])
            all_tokens.append(toks)
            for t in set(toks):
                doc_freq[t] += 1
            total_len += len(toks)

        n_docs = len(chunks)
        avgdl = total_len / max(n_docs, 1)

        # TF-IDF vector search
        def _idf(term: str) -> float:
            df = doc_freq.get(term, 0)
            return math.log(n_docs / df) if df else 0.0

        q_tf = Counter(query_tokens)
        q_vec = {t: (cnt / len(query_tokens)) * _idf(t) for t, cnt in q_tf.items()}

        vector_scores: list[float] = []
        for toks in all_tokens:
            if not toks:
                vector_scores.append(0.0)
                continue
            tf = Counter(toks)
            c_vec = {t: (cnt / len(toks)) * _idf(t) for t, cnt in tf.items()}
            vector_scores.append(cosine_similarity(q_vec, c_vec))

        # BM25 keyword search
        bm25_raw: list[float] = [
            bm25_score(query_tokens, toks, doc_freq, n_docs, avgdl=avgdl)
            for toks in all_tokens
        ]
        max_bm25 = max(bm25_raw) if bm25_raw else 1.0
        text_scores = [(s / max_bm25 if max_bm25 > 0 else 0.0) for s in bm25_raw]

        # Merge results
        results: list[dict] = []
        for i, chunk in enumerate(chunks):
            score = HYBRID_VECTOR_WEIGHT * vector_scores[i] + HYBRID_TEXT_WEIGHT * text_scores[i]
            if score < min_score:
                continue
            snippet = chunk["text"][:SEARCH_MAX_SNIPPET_CHARS]
            citation = (
                f"{chunk['path']}#L{chunk['startLine']}"
                if chunk["startLine"] == chunk["endLine"]
                else f"{chunk['path']}#L{chunk['startLine']}-L{chunk['endLine']}"
            )
            results.append({
                "path": chunk["path"],
                "startLine": chunk["startLine"],
                "endLine": chunk["endLine"],
                "score": round(score, 4),
                "snippet": snippet,
                "source": chunk["source"],
                "citation": citation,
            })

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:max_results]
