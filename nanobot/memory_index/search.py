"""Hybrid BM25+vector search with RRF fusion, temporal decay, and MMR."""

from __future__ import annotations

import math
import sqlite3
import struct
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

_RRF_K = 60


@dataclass
class SearchResult:
    text: str
    source: str
    start_line: int
    end_line: int
    score: float


def bm25_search(conn: sqlite3.Connection, query: str, k: int) -> list[int]:
    """Return up to k chunk IDs ranked by BM25 (best first)."""
    try:
        rows = conn.execute(
            "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? "
            "ORDER BY bm25(chunks_fts) LIMIT ?",
            [query, k],
        ).fetchall()
        return [r[0] for r in rows]
    except sqlite3.OperationalError:
        return []


def vector_search(conn: sqlite3.Connection, query_vec: list[float], k: int) -> list[int]:
    """Return up to k chunk IDs ranked by cosine distance (best first)."""
    query_bytes = struct.pack(f"{len(query_vec)}f", *query_vec)
    try:
        rows = conn.execute(
            "SELECT rowid FROM chunks_vec WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
            [query_bytes, k],
        ).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []


def rrf_merge(bm25_ids: list[int], vec_ids: list[int]) -> dict[int, float]:
    """Merge two ranked lists using Reciprocal Rank Fusion."""
    scores: dict[int, float] = defaultdict(float)
    for rank, doc_id in enumerate(bm25_ids):
        scores[doc_id] += 1.0 / (_RRF_K + rank)
    for rank, doc_id in enumerate(vec_ids):
        scores[doc_id] += 1.0 / (_RRF_K + rank)
    return dict(scores)


def apply_temporal_decay(
    scores: dict[int, float],
    conn: sqlite3.Connection,
    half_life_days: float,
) -> dict[int, float]:
    """Multiply each score by exp(-age_days / half_life_days)."""
    if not scores or half_life_days <= 0:
        return scores
    now = time.time()
    placeholders = ",".join("?" * len(scores))
    rows = conn.execute(
        f"SELECT id, created_at FROM chunks WHERE id IN ({placeholders})",
        list(scores.keys()),
    ).fetchall()
    id_to_ts = {r[0]: r[1] for r in rows}
    return {
        doc_id: score * math.exp(-(now - id_to_ts.get(doc_id, now)) / 86400 / half_life_days)
        for doc_id, score in scores.items()
    }


def mmr_rerank(
    scores: dict[int, float],
    chunk_vecs: dict[int, list[float]],
    query_vec: list[float] | None,
    top_k: int,
    lambda_: float,
) -> list[int]:
    """Maximal Marginal Relevance: diversify top-k results."""
    if not scores:
        return []
    if query_vec is None or not chunk_vecs:
        return sorted(scores, key=scores.__getitem__, reverse=True)[:top_k]

    candidates = list(scores.keys())
    selected: list[int] = []

    while len(selected) < top_k and candidates:
        best_id, best_score = None, float("-inf")
        for cid in candidates:
            relevance = scores[cid]
            max_sim = (
                max(_dot(chunk_vecs[cid], chunk_vecs[s]) for s in selected if s in chunk_vecs)
                if selected
                else 0.0
            )
            mmr_score = lambda_ * relevance - (1 - lambda_) * max_sim
            if mmr_score > best_score:
                best_score, best_id = mmr_score, cid
        if best_id is None:
            break
        selected.append(best_id)
        candidates.remove(best_id)

    return selected


def sync_search(
    db_path: Path,
    query: str,
    query_vec: list[float] | None,
    top_k: int,
    vec_available: bool,
    mmr_lambda: float,
    half_life_days: float,
) -> list[SearchResult]:
    """Full search pipeline: BM25 + vector → RRF → decay → MMR → results."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    if vec_available:
        try:
            import sqlite_vec

            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
        except Exception:
            vec_available = False

    try:
        candidate_k = top_k * 4
        bm25_ids = bm25_search(conn, query, candidate_k)
        vec_ids = (
            vector_search(conn, query_vec, candidate_k) if (vec_available and query_vec) else []
        )

        if not bm25_ids and not vec_ids:
            return []

        merged = rrf_merge(bm25_ids, vec_ids)
        decayed = apply_temporal_decay(merged, conn, half_life_days)

        # Retrieve stored embeddings for MMR (from chunks.embedding BLOB)
        chunk_vecs: dict[int, list[float]] = {}
        if vec_available and query_vec:
            dim = len(query_vec)
            placeholders = ",".join("?" * len(decayed))
            rows = conn.execute(
                f"SELECT id, embedding FROM chunks WHERE id IN ({placeholders}) AND embedding IS NOT NULL",
                list(decayed.keys()),
            ).fetchall()
            for r in rows:
                if r["embedding"]:
                    chunk_vecs[r["id"]] = list(struct.unpack(f"{dim}f", r["embedding"]))

        ordered = mmr_rerank(decayed, chunk_vecs, query_vec, top_k, mmr_lambda)

        if not ordered:
            return []

        placeholders = ",".join("?" * len(ordered))
        rows = conn.execute(
            f"SELECT c.id, c.text, c.start_line, c.end_line, f.path "
            f"FROM chunks c JOIN files f ON c.file_id = f.id "
            f"WHERE c.id IN ({placeholders})",
            ordered,
        ).fetchall()
        id_to_row = {r["id"]: r for r in rows}

        return [
            SearchResult(
                text=id_to_row[doc_id]["text"],
                source=Path(id_to_row[doc_id]["path"]).name,
                start_line=id_to_row[doc_id]["start_line"],
                end_line=id_to_row[doc_id]["end_line"],
                score=decayed.get(doc_id, 0.0),
            )
            for doc_id in ordered
            if doc_id in id_to_row
        ]
    finally:
        conn.close()


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))
