"""SQLite FTS5 store for subconscious memory chunks.

Inspired by OpenHuman's memory_tree / memory_store architecture:
- Each Obsidian note is chunked into ≤3000-token fragments
- Stored with full-text search via SQLite FTS5
- Entity mentions extracted per chunk (people, projects, dates, tags)
- Hierarchical summary tree mirrors the vault folder structure
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

# Token budget per chunk (rough: 1 token ≈ 4 chars)
CHUNK_TOKEN_BUDGET = 3000
CHUNK_CHAR_BUDGET = CHUNK_TOKEN_BUDGET * 4


@dataclass
class Chunk:
    chunk_id: str
    source_path: str          # Relative path inside vault
    chunk_index: int
    content: str
    heading: str              # Nearest H1/H2 heading above this chunk
    tags: list[str]
    entities: list[str]       # People / projects / [[links]] mentioned
    mtime: float              # Source file mtime when ingested
    word_count: int = field(init=False)

    def __post_init__(self) -> None:
        self.word_count = len(self.content.split())


def _make_chunk_id(path: str, index: int) -> str:
    raw = f"{path}::{index}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _extract_tags(text: str) -> list[str]:
    """Extract #tag and YAML frontmatter tags from markdown."""
    tags: list[str] = []
    # Inline #tags
    tags += re.findall(r"(?<!\w)#([a-zA-Z][a-zA-Z0-9_/-]*)", text)
    # YAML frontmatter tags: list
    fm = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if fm:
        raw = fm.group(1)
        m = re.search(r"tags:\s*\n((?:\s*-\s*.+\n?)+)", raw)
        if m:
            tags += re.findall(r"-\s*(.+)", m.group(1))
        m2 = re.search(r"tags:\s*\[([^\]]+)\]", raw)
        if m2:
            tags += [t.strip().strip('"\'') for t in m2.group(1).split(",")]
    return list(dict.fromkeys(t.strip() for t in tags if t.strip()))


def _extract_entities(text: str) -> list[str]:
    """Extract [[wiki-links]] and @mentions as entities."""
    entities: list[str] = []
    # Obsidian wiki-links: [[Note Name]] or [[Note Name|alias]]
    entities += [m.split("|")[0].strip() for m in re.findall(r"\[\[([^\]]+)\]\]", text)]
    # @mentions
    entities += re.findall(r"@([A-Za-z][A-Za-z0-9_.-]+)", text)
    return list(dict.fromkeys(e for e in entities if e))


def _strip_frontmatter(text: str) -> tuple[str, str]:
    """Return (cleaned_text, frontmatter_block)."""
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.DOTALL)
    if m:
        return text[m.end():], m.group(1)
    return text, ""


def _split_into_chunks(text: str, path: str, heading: str, tags: list[str]) -> Iterator[Chunk]:
    """Split a document body into ≤CHUNK_CHAR_BUDGET chunks, respecting paragraph boundaries."""
    # Split on double newline to get paragraphs
    paragraphs = re.split(r"\n{2,}", text.strip())
    current_parts: list[str] = []
    current_len = 0
    chunk_index = 0
    current_heading = heading

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # Track heading changes within document
        m = re.match(r"^(#{1,3})\s+(.+)", para)
        if m:
            current_heading = m.group(2).strip()

        if current_len + len(para) > CHUNK_CHAR_BUDGET and current_parts:
            content = "\n\n".join(current_parts)
            entities = _extract_entities(content)
            yield Chunk(
                chunk_id=_make_chunk_id(path, chunk_index),
                source_path=path,
                chunk_index=chunk_index,
                content=content,
                heading=current_heading,
                tags=tags,
                entities=entities,
                mtime=0.0,
            )
            chunk_index += 1
            current_parts = []
            current_len = 0

        current_parts.append(para)
        current_len += len(para) + 2  # +2 for \n\n

    if current_parts:
        content = "\n\n".join(current_parts)
        entities = _extract_entities(content)
        yield Chunk(
            chunk_id=_make_chunk_id(path, chunk_index),
            source_path=path,
            chunk_index=chunk_index,
            content=content,
            heading=current_heading,
            tags=tags,
            entities=entities,
            mtime=0.0,
        )


class SubconsciousStore:
    """SQLite-backed FTS store for vault chunks.

    Database location: ~/.nanobot/subconscious.db
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._init_schema()
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        db = self._conn
        assert db is not None
        db.executescript("""
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id    TEXT PRIMARY KEY,
                source_path TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content     TEXT NOT NULL,
                heading     TEXT NOT NULL DEFAULT '',
                tags        TEXT NOT NULL DEFAULT '[]',
                entities    TEXT NOT NULL DEFAULT '[]',
                mtime       REAL NOT NULL DEFAULT 0,
                ingested_at REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS file_meta (
                source_path TEXT PRIMARY KEY,
                mtime       REAL NOT NULL,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                ingested_at REAL NOT NULL DEFAULT 0
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                chunk_id UNINDEXED,
                source_path,
                heading,
                content,
                tags,
                content=chunks,
                content_rowid=rowid
            );

            CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
                INSERT INTO chunks_fts(rowid, chunk_id, source_path, heading, content, tags)
                VALUES (new.rowid, new.chunk_id, new.source_path, new.heading, new.content, new.tags);
            END;

            CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
                INSERT INTO chunks_fts(chunks_fts, rowid, chunk_id, source_path, heading, content, tags)
                VALUES ('delete', old.rowid, old.chunk_id, old.source_path, old.heading, old.content, old.tags);
            END;

            CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
                INSERT INTO chunks_fts(chunks_fts, rowid, chunk_id, source_path, heading, content, tags)
                VALUES ('delete', old.rowid, old.chunk_id, old.source_path, old.heading, old.content, old.tags);
                INSERT INTO chunks_fts(rowid, chunk_id, source_path, heading, content, tags)
                VALUES (new.rowid, new.chunk_id, new.source_path, new.heading, new.content, new.tags);
            END;
        """)
        db.commit()

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def needs_ingest(self, rel_path: str, mtime: float) -> bool:
        """Return True if file is new or modified since last ingest."""
        db = self._db()
        row = db.execute(
            "SELECT mtime FROM file_meta WHERE source_path = ?", (rel_path,)
        ).fetchone()
        if row is None:
            return True
        return float(row["mtime"]) < mtime

    def ingest_document(self, rel_path: str, content: str, mtime: float) -> int:
        """Parse, chunk, and store a markdown document. Returns number of chunks."""
        body, _fm = _strip_frontmatter(content)
        tags = _extract_tags(content)

        # Get document title from first H1 or filename
        m = re.search(r"^#\s+(.+)", body, re.MULTILINE)
        title = m.group(1).strip() if m else Path(rel_path).stem

        now = time.time()
        db = self._db()

        # Remove stale chunks for this file
        db.execute("DELETE FROM chunks WHERE source_path = ?", (rel_path,))

        count = 0
        for chunk in _split_into_chunks(body, rel_path, title, tags):
            chunk.mtime = mtime
            db.execute(
                """INSERT OR REPLACE INTO chunks
                   (chunk_id, source_path, chunk_index, content, heading, tags, entities, mtime, ingested_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    chunk.chunk_id,
                    chunk.source_path,
                    chunk.chunk_index,
                    chunk.content,
                    chunk.heading,
                    json.dumps(chunk.tags, ensure_ascii=False),
                    json.dumps(chunk.entities, ensure_ascii=False),
                    chunk.mtime,
                    now,
                ),
            )
            count += 1

        db.execute(
            """INSERT OR REPLACE INTO file_meta (source_path, mtime, chunk_count, ingested_at)
               VALUES (?, ?, ?, ?)""",
            (rel_path, mtime, count, now),
        )
        db.commit()
        return count

    def remove_document(self, rel_path: str) -> None:
        """Remove all chunks for a deleted file."""
        db = self._db()
        db.execute("DELETE FROM chunks WHERE source_path = ?", (rel_path,))
        db.execute("DELETE FROM file_meta WHERE source_path = ?", (rel_path,))
        db.commit()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Full-text search over vault chunks. Returns ranked results."""
        db = self._db()
        rows = db.execute(
            """SELECT c.chunk_id, c.source_path, c.heading, c.content, c.tags,
                      c.entities, rank
               FROM chunks_fts
               JOIN chunks c ON c.chunk_id = chunks_fts.chunk_id
               WHERE chunks_fts MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (query, limit),
        ).fetchall()
        results = []
        for r in rows:
            results.append({
                "chunk_id": r["chunk_id"],
                "source_path": r["source_path"],
                "heading": r["heading"],
                "content": r["content"][:800],  # truncate for context
                "tags": json.loads(r["tags"]),
                "entities": json.loads(r["entities"]),
            })
        return results

    def recall(self, limit: int = 20) -> list[dict]:
        """Return most recently ingested chunks."""
        db = self._db()
        rows = db.execute(
            """SELECT chunk_id, source_path, heading, content, tags, entities, mtime
               FROM chunks ORDER BY mtime DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [
            {
                "chunk_id": r["chunk_id"],
                "source_path": r["source_path"],
                "heading": r["heading"],
                "content": r["content"][:600],
                "tags": json.loads(r["tags"]),
            }
            for r in rows
        ]

    def stats(self) -> dict:
        """Return store statistics."""
        db = self._db()
        total_chunks = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        total_files = db.execute("SELECT COUNT(*) FROM file_meta").fetchone()[0]
        last_ingested = db.execute("SELECT MAX(ingested_at) FROM file_meta").fetchone()[0]
        return {
            "total_chunks": total_chunks,
            "total_files": total_files,
            "last_ingested": last_ingested,
        }

    def list_files(self) -> list[dict]:
        """List all ingested files with metadata."""
        db = self._db()
        rows = db.execute(
            "SELECT source_path, mtime, chunk_count, ingested_at FROM file_meta ORDER BY ingested_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
