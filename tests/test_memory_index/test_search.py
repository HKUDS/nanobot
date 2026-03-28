import math
import sqlite3
import time
from pathlib import Path

import pytest

from nanobot.config.schema import MemoryIndexConfig
from nanobot.memory_index.index import MemoryIndex
from nanobot.memory_index.indexer import Chunk, write_chunks
from nanobot.memory_index.search import (
    apply_temporal_decay,
    bm25_search,
    mmr_rerank,
    rrf_merge,
    sync_search,
)


def _make_db(tmp_path: Path, chunks_by_file: dict[str, list[Chunk]]) -> Path:
    """Create a test index DB with given chunks (no embeddings)."""
    cfg = MemoryIndexConfig()
    idx = MemoryIndex(tmp_path, cfg)
    for filename, chunks in chunks_by_file.items():
        f = tmp_path / "memory" / filename
        f.write_text("placeholder")
        write_chunks(
            idx.db_path, f, f.stat().st_mtime, f.stat().st_size, filename, chunks, None, False
        )
    return idx.db_path


def _open(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def test_bm25_search_returns_matching_chunk(tmp_path):
    db = _make_db(
        tmp_path,
        {
            "MEMORY.md": [
                Chunk("The capital of France is Paris.", 1, 1, time.time()),
                Chunk("Python is a programming language.", 2, 2, time.time()),
            ]
        },
    )
    conn = _open(db)
    ids = bm25_search(conn, "France Paris", 5)
    conn.close()
    assert len(ids) >= 1  # at least the France/Paris chunk matches


def test_bm25_search_returns_empty_on_no_match(tmp_path):
    db = _make_db(
        tmp_path,
        {
            "MEMORY.md": [
                Chunk("The sky is blue.", 1, 1, time.time()),
            ]
        },
    )
    conn = _open(db)
    ids = bm25_search(conn, "xyzzy_nonexistent_token_zzz", 5)
    conn.close()
    assert ids == []


def test_rrf_merge_boosts_shared_doc(tmp_path):
    # doc 1 appears in both lists; doc 2 only in bm25; doc 3 only in vec
    scores = rrf_merge([1, 2], [1, 3])
    assert scores[1] > scores[2]  # doc 1 boosted by both
    assert scores[1] > scores[3]


def test_rrf_merge_single_list(tmp_path):
    scores = rrf_merge([5, 6, 7], [])
    assert 5 in scores
    assert scores[5] > scores[6] > scores[7]


def test_temporal_decay_penalizes_old_chunk(tmp_path):
    now = time.time()
    old_ts = now - 180 * 86400  # 180 days ago
    db = _make_db(
        tmp_path,
        {
            "MEMORY.md": [
                Chunk("Recent fact.", 1, 1, now),
                Chunk("Old fact.", 2, 2, old_ts),
            ]
        },
    )
    conn = _open(db)
    ids = [r[0] for r in conn.execute("SELECT id FROM chunks ORDER BY id").fetchall()]
    conn.close()
    recent_id, old_id = ids[0], ids[1]
    base_scores = {recent_id: 1.0, old_id: 1.0}
    conn = _open(db)
    decayed = apply_temporal_decay(base_scores, conn, half_life_days=90.0)
    conn.close()
    # 180-day-old chunk should score roughly exp(-2) ≈ 0.135 of original
    assert decayed[old_id] < decayed[recent_id]
    assert decayed[old_id] == pytest.approx(math.exp(-2.0), rel=0.05)


def test_mmr_rerank_increases_diversity(tmp_path):
    # Two near-identical vectors and one diverse vector
    # MMR should prefer the diverse one in the top-2
    vec_a = [1.0, 0.0, 0.0]
    vec_b = [0.99, 0.14, 0.0]  # very similar to a
    vec_c = [0.0, 1.0, 0.0]  # diverse

    scores = {1: 0.9, 2: 0.8, 3: 0.5}  # doc 1 and 2 score higher, but similar
    chunk_vecs = {1: vec_a, 2: vec_b, 3: vec_c}

    result = mmr_rerank(scores, chunk_vecs, query_vec=[1.0, 0.0, 0.0], top_k=2, lambda_=0.5)
    assert 1 in result  # highest relevance always selected first
    assert 3 in result  # diverse doc preferred over near-duplicate doc 2
    assert 2 not in result


def test_mmr_rerank_falls_back_to_score_order_without_vecs(tmp_path):
    scores = {1: 0.9, 2: 0.7, 3: 0.5}
    result = mmr_rerank(scores, {}, query_vec=None, top_k=2, lambda_=0.5)
    assert result == [1, 2]


def test_sync_search_end_to_end(tmp_path):
    db = _make_db(
        tmp_path,
        {
            "MEMORY.md": [
                Chunk("The user prefers dark mode interfaces.", 1, 1, time.time()),
                Chunk("Python is a programming language.", 2, 2, time.time()),
                Chunk("The user lives in New York.", 3, 3, time.time()),
            ]
        },
    )
    results = sync_search(db, "dark mode preference", None, 2, False, 0.5, 90.0)
    assert len(results) <= 2
    assert any("dark mode" in r.text for r in results)


def test_sync_search_returns_empty_for_no_match(tmp_path):
    db = _make_db(
        tmp_path,
        {
            "MEMORY.md": [
                Chunk("Unrelated content about cats.", 1, 1, time.time()),
            ]
        },
    )
    results = sync_search(db, "xyzzy_nonexistent", None, 5, False, 0.5, 90.0)
    assert results == []
