import sqlite3
from pathlib import Path

from nanobot.config.schema import MemoryIndexConfig
from nanobot.memory_index.index import MemoryIndex
from nanobot.memory_index.indexer import Chunk, file_hash, write_chunks


def test_index_creates_tables(tmp_path):
    idx = MemoryIndex(tmp_path, MemoryIndexConfig())
    conn = sqlite3.connect(idx.db_path)
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','shadow') AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }
    conn.close()
    assert "files" in tables
    assert "chunks" in tables
    assert "index_meta" in tables
    # chunks_fts is a virtual table
    vtables = {
        r[0]
        for r in sqlite3.connect(idx.db_path)
        .execute("SELECT name FROM sqlite_master WHERE type='table'")
        .fetchall()
    }
    assert "chunks_fts" in vtables


def test_index_stores_model_metadata(tmp_path):
    cfg = MemoryIndexConfig()
    idx = MemoryIndex(tmp_path, cfg)
    conn = sqlite3.connect(idx.db_path)
    row = conn.execute("SELECT value FROM index_meta WHERE key='embedding_model'").fetchone()
    conn.close()
    assert row is not None
    assert row[0] == cfg.embedding.model


def test_index_rebuilds_on_model_mismatch(tmp_path):
    # Create index with model A
    cfg_a = MemoryIndexConfig()
    idx_a = MemoryIndex(tmp_path, cfg_a)
    # Write a dummy file record to verify it gets wiped
    conn = sqlite3.connect(idx_a.db_path)
    conn.execute("INSERT INTO files(path, mtime, size, hash) VALUES ('x', 0, 0, 'abc')")
    conn.commit()
    conn.close()

    # Create index with different model — should wipe and rebuild
    cfg_b = MemoryIndexConfig()
    cfg_b.embedding.model = "mxbai-embed-large"
    cfg_b.embedding.dim = 1024
    idx_b = MemoryIndex(tmp_path, cfg_b)
    conn = sqlite3.connect(idx_b.db_path)
    file_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    stored_model = conn.execute(
        "SELECT value FROM index_meta WHERE key='embedding_model'"
    ).fetchone()[0]
    conn.close()
    assert file_count == 0
    assert stored_model == "mxbai-embed-large"


def _open(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def test_write_chunks_inserts_rows(tmp_path):
    idx = MemoryIndex(tmp_path, MemoryIndexConfig())
    f = tmp_path / "memory" / "MEMORY.md"
    f.write_text("## Facts\n\nSome fact.\n")
    chunks = [Chunk("Some fact.", 2, 2, 1_700_000_000.0)]
    write_chunks(
        idx.db_path, f, f.stat().st_mtime, f.stat().st_size, file_hash(f), chunks, None, False
    )
    conn = _open(idx.db_path)
    assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 1
    conn.close()


def test_write_chunks_replaces_on_reindex(tmp_path):
    idx = MemoryIndex(tmp_path, MemoryIndexConfig())
    f = tmp_path / "memory" / "MEMORY.md"
    f.write_text("## A\n\nOld content.\n")
    old_chunk = [Chunk("Old content.", 2, 2, 1_700_000_000.0)]
    write_chunks(
        idx.db_path, f, f.stat().st_mtime, f.stat().st_size, "hash1", old_chunk, None, False
    )

    new_chunk = [Chunk("New content.", 2, 2, 1_700_000_000.0)]
    write_chunks(
        idx.db_path, f, f.stat().st_mtime, f.stat().st_size, "hash2", new_chunk, None, False
    )

    conn = _open(idx.db_path)
    texts = [r[0] for r in conn.execute("SELECT text FROM chunks").fetchall()]
    conn.close()
    assert texts == ["New content."]  # old chunk gone

    conn = _open(idx.db_path)
    # Old text should be gone from FTS
    old_fts = conn.execute(
        "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'Old'",
    ).fetchall()
    conn.close()
    assert old_fts == []  # FTS cleaned up on re-index


def test_write_chunks_populates_fts(tmp_path):
    idx = MemoryIndex(tmp_path, MemoryIndexConfig())
    f = tmp_path / "memory" / "MEMORY.md"
    f.write_text("## Facts\n\nThe sky is blue.\n")
    chunks = [Chunk("The sky is blue.", 2, 2, 1_700_000_000.0)]
    write_chunks(
        idx.db_path, f, f.stat().st_mtime, f.stat().st_size, file_hash(f), chunks, None, False
    )
    conn = _open(idx.db_path)
    result = conn.execute("SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'sky'").fetchall()
    conn.close()
    assert len(result) == 1


async def test_startup_index_skips_unchanged_file(tmp_path):
    cfg = MemoryIndexConfig()
    idx = MemoryIndex(tmp_path, cfg)
    f = tmp_path / "memory" / "MEMORY.md"
    f.write_text("## Facts\n\nSome fact.\n")

    await idx.startup_index()
    conn = _open(idx.db_path)
    count_after_first = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    conn.close()

    # Run again — should not duplicate
    await idx.startup_index()
    conn = _open(idx.db_path)
    count_after_second = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    conn.close()
    assert count_after_first > 0  # first run actually indexed something
    assert count_after_first == count_after_second
