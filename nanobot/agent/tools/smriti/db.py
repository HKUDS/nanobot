"""
memory_box.store

High-level memory store.

Responsibilities:
- Append-only canonical Markdown storage:
    * <workspace>/memory/YYYY-MM-DD.md        (daily)
    * <workspace>/memory/MEMORY.md            (curated long-term)
    * <workspace>/memory/.trash/YYYY-MM-DD.md (soft-deleted; restorable)
- Semantic extraction:
    * #tags and @people parsed from text and normalized for filtering.
- Fast recall via SQLite + optional FTS5 (MemoryDB), with a file-scan fallback.
- Core operations:
    remember / recall / soft_forget / restore / promote
  using stable short ids (e.g. ^a1b2c3d4e5).

Query mini-syntax (passed to recall/search):
- Filters:
    * kind:<fact|pref|decision|todo|note>
    * scope:<daily|long|pinned>   (pinned is treated as long)
- Semantic tokens:
    * #tag      (matches normalized tags)
    * @person   (matches normalized people)
- Remaining terms are treated as free-text.

Examples:
- "kind:todo #groceries buy eggs"
    -> only TODO items tagged #groceries whose text matches "buy eggs"
- "scope:long @alex meeting notes"
    -> only long-term items mentioning @alex, matching "meeting notes"
- "#travel @sam itinerary"
    -> any scope/kind, tagged #travel and linked to @sam, matching "itinerary"

Author: Arghya Ranjan Das
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Iterable
from collections import Counter

from .models import MemoryValue, MemoryQuery, MemoryHit


_FTS_BAD_CHARS = re.compile(r"""["'*:^()\[\]{}\\]""")  # conservative
_ID10_RE = re.compile(r"^[0-9a-f]{10}$")


def _like_tokens(col: str, vals: Iterable[str]) -> tuple[str, list[str]]:
    """
    WHERE helper for whitespace-padded token fields:
        tags = " tag1 tag2 "
    Use LIKE "% tag %".
    """
    vals = [v.strip().lower().lstrip("#@") for v in vals if v and v.strip()]
    if not vals:
        return "", []
    clauses = [f"{col} LIKE ?" for _ in vals]
    params = [f"% {v} %" for v in vals]
    return "(" + " OR ".join(clauses) + ")", params


def _fts_safe_query(q: str) -> str:
    """
    Build a conservative FTS5 query string.

    Strategy:
    - split on whitespace
    - if any token contains "dangerous" FTS syntax chars, quote that token
    - join tokens with AND (explicit)
    - if everything is empty -> return "" (caller should avoid MATCH)
    """
    q = (q or "").strip()
    if not q:
        return ""

    toks = [t for t in q.split() if t.strip()]
    if not toks:
        return ""

    out = []
    for t in toks:
        # If token looks like raw operator syntax, quote it.
        if _FTS_BAD_CHARS.search(t):
            t2 = t.replace('"', '""')
            out.append(f'"{t2}"')
        else:
            out.append(t)
    return " AND ".join(out)


class MemoryDB:
    """SQL-only layer. Uses FTS5 if available; otherwise table-only ops."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.fts_ok = False
        self._init_db()

    def _con(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.db_path), timeout=30.0)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        con.execute("PRAGMA foreign_keys=ON;")
        return con

    def _init_db(self) -> None:
        con = self._con()
        try:
            con.execute(
                "CREATE TABLE IF NOT EXISTS mem("
                "id TEXT PRIMARY KEY, ts TEXT, day TEXT, time TEXT, "
                "scope TEXT, kind TEXT, text TEXT, tags TEXT, people TEXT, source TEXT)"
            )
            con.execute(
                "CREATE TABLE IF NOT EXISTS trash("
                "id TEXT PRIMARY KEY, ts TEXT, day TEXT, time TEXT, "
                "scope TEXT, kind TEXT, text TEXT, tags TEXT, people TEXT, source TEXT, "
                "deleted_ts TEXT, trash_file TEXT)"
            )

            # Indices that matter in practice:
            con.execute("CREATE INDEX IF NOT EXISTS mem_day_time_idx ON mem(day DESC, time DESC)")
            con.execute("CREATE INDEX IF NOT EXISTS mem_kind_idx ON mem(kind)")
            con.execute("CREATE INDEX IF NOT EXISTS mem_scope_idx ON mem(scope)")
            con.execute("CREATE INDEX IF NOT EXISTS trash_deleted_idx ON trash(deleted_ts DESC)")

            # FTS tables: keep them updated manually to stay compatible everywhere.
            try:
                con.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS mem_fts USING fts5("
                    "id UNINDEXED, text, tags, people, kind, tokenize='porter')"
                )
                con.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS trash_fts USING fts5("
                    "id UNINDEXED, text, tags, people, kind, tokenize='porter')"
                )
                self.fts_ok = True
            except sqlite3.OperationalError:
                self.fts_ok = False

            con.commit()
        finally:
            con.close()

    # ---------- basic CRUD ----------
    def upsert_mem(self, v: MemoryValue) -> None:
        con = self._con()
        try:
            con.execute("BEGIN")
            con.execute(
                "INSERT OR REPLACE INTO mem(id, ts, day, time, scope, kind, text, tags, people, source) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (v.id, v.ts, v.day, v.time, v.scope, v.kind, v.text, v.tags, v.people, v.source),
            )
            if self.fts_ok:
                con.execute("DELETE FROM mem_fts WHERE id=?", (v.id,))
                con.execute(
                    "INSERT INTO mem_fts(id, text, tags, people, kind) VALUES(?,?,?,?,?)",
                    (v.id, v.text, v.tags, v.people, v.kind),
                )
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def get_mem(self, mid: str) -> MemoryValue | None:
        con = self._con()
        try:
            r = con.execute("SELECT * FROM mem WHERE id=?", (mid,)).fetchone()
            if not r:
                return None
            return MemoryValue(
                id=r["id"], ts=r["ts"], day=r["day"], time=r["time"],
                scope=r["scope"], kind=r["kind"], text=r["text"],
                tags=r["tags"], people=r["people"], source=r["source"],
            )
        finally:
            con.close()

    def get_trash(self, mid: str) -> MemoryValue | None:
        con = self._con()
        try:
            r = con.execute("SELECT * FROM trash WHERE id=?", (mid,)).fetchone()
            if not r:
                return None
            return MemoryValue(
                id=r["id"], ts=r["ts"], day=r["day"], time=r["time"],
                scope=r["scope"], kind=r["kind"], text=r["text"],
                tags=r["tags"], people=r["people"], source=r["source"],
            )
        finally:
            con.close()

    def move_to_trash(self, mid: str, deleted_ts: str, trash_file: str) -> MemoryValue | None:
        con = self._con()
        try:
            con.execute("BEGIN")
            r = con.execute("SELECT * FROM mem WHERE id=?", (mid,)).fetchone()
            if not r:
                con.rollback()
                return None

            con.execute("DELETE FROM mem WHERE id=?", (mid,))
            if self.fts_ok:
                con.execute("DELETE FROM mem_fts WHERE id=?", (mid,))

            con.execute(
                "INSERT OR REPLACE INTO trash("
                "id, ts, day, time, scope, kind, text, tags, people, source, deleted_ts, trash_file) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    r["id"], r["ts"], r["day"], r["time"], r["scope"], r["kind"],
                    r["text"], r["tags"], r["people"], r["source"], deleted_ts, trash_file
                ),
            )

            if self.fts_ok:
                con.execute("DELETE FROM trash_fts WHERE id=?", (mid,))
                con.execute(
                    "INSERT INTO trash_fts(id, text, tags, people, kind) VALUES(?,?,?,?,?)",
                    (r["id"], r["text"], r["tags"], r["people"], r["kind"]),
                )

            con.commit()

            return MemoryValue(
                id=r["id"], ts=r["ts"], day=r["day"], time=r["time"],
                scope=r["scope"], kind=r["kind"], text=r["text"],
                tags=r["tags"], people=r["people"], source=r["source"],
            )
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def restore_from_trash(self, mid: str) -> MemoryValue | None:
        con = self._con()
        try:
            con.execute("BEGIN")
            r = con.execute("SELECT * FROM trash WHERE id=?", (mid,)).fetchone()
            if not r:
                con.rollback()
                return None

            con.execute("DELETE FROM trash WHERE id=?", (mid,))
            if self.fts_ok:
                con.execute("DELETE FROM trash_fts WHERE id=?", (mid,))

            v = MemoryValue(
                id=r["id"], ts=r["ts"], day=r["day"], time=r["time"],
                scope=r["scope"], kind=r["kind"], text=r["text"],
                tags=r["tags"], people=r["people"], source=r["source"],
            )

            con.execute(
                "INSERT OR REPLACE INTO mem(id, ts, day, time, scope, kind, text, tags, people, source) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (v.id, v.ts, v.day, v.time, v.scope, v.kind, v.text, v.tags, v.people, v.source),
            )

            if self.fts_ok:
                con.execute("DELETE FROM mem_fts WHERE id=?", (v.id,))
                con.execute(
                    "INSERT INTO mem_fts(id, text, tags, people, kind) VALUES(?,?,?,?,?)",
                    (v.id, v.text, v.tags, v.people, v.kind),
                )

            con.commit()
            return v
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def update_scope_source(self, mid: str, scope: str, source: str) -> None:
        con = self._con()
        try:
            con.execute("UPDATE mem SET scope=?, source=? WHERE id=?", (scope, source, mid))
            con.commit()
        finally:
            con.close()

    def list_recent(self, limit: int = 20) -> list[MemoryValue]:
        con = self._con()
        try:
            rows = con.execute(
                "SELECT * FROM mem ORDER BY day DESC, time DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            return [
                MemoryValue(
                    id=r["id"], ts=r["ts"], day=r["day"], time=r["time"],
                    scope=r["scope"], kind=r["kind"], text=r["text"],
                    tags=r["tags"], people=r["people"], source=r["source"],
                )
                for r in rows
            ]
        finally:
            con.close()

    def list_trash(self, limit: int = 20):
        con = self._con()
        try:
            return con.execute(
                "SELECT id, day, time, kind, scope, deleted_ts, source, trash_file "
                "FROM trash ORDER BY deleted_ts DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        finally:
            con.close()

    # ---------- vocab ----------
    def recent_vocab(self, *, rows: int = 5000, include_trash: bool = False) -> dict[str, list[tuple[str, int]]]:
        """
        Return top tags/people from the most recent `rows` items.
        Uses normalized whitespace-padded storage: " tag1 tag2 ".
        """
        table = "trash" if include_trash else "mem"
        con = self._con()
        try:
            rs = con.execute(
                f"SELECT tags, people FROM {table} ORDER BY day DESC, time DESC LIMIT ?",
                (int(rows),),
            ).fetchall()
        finally:
            con.close()

        ct_tags = Counter()
        ct_ppl = Counter()
        for r in rs:
            for t in (r["tags"] or "").split():
                ct_tags[t] += 1
            for p in (r["people"] or "").split():
                ct_ppl[p] += 1

        return {"tags": ct_tags.most_common(200), "people": ct_ppl.most_common(200)}

    # ---------- search ----------
    def search(self, mq: MemoryQuery) -> list[MemoryHit]:
        """
        Ranked search.

        IMPORTANT BEHAVIOR:
        - If there is no free-text (mq.q == ""), we DO NOT run `fts MATCH`.
          We run a pure meta-table query with LIKE filters.
        - If free-text exists and FTS5 exists, we rank with bm25 + snippet.
        - If FTS5 is not available, caller should fallback to file scan.
        """
        if not self.fts_ok:
            return []

        meta = "trash" if mq.include_trash else "mem"
        fts = "trash_fts" if mq.include_trash else "mem_fts"

        q = (mq.q or "").strip()

        # ---- Case A: structured-only query (NO MATCH) ----
        if not q:
            where = []
            params: list[object] = []

            # exact filters
            if mq.kind:
                where.append(f"{meta}.kind=?")
                params.append(mq.kind)
            if mq.scope:
                where.append(f"{meta}.scope=?")
                params.append(mq.scope)

            # exact id filter(s)
            if mq.ids_any:
                good_ids = [x for x in mq.ids_any if _ID10_RE.match(x)]
                if good_ids:
                    where.append("(" + " OR ".join([f"{meta}.id=?" for _ in good_ids]) + ")")
                    params.extend(good_ids)

            # token membership via LIKE on whitespace padded fields
            tag_clause, tag_params = _like_tokens(f"{meta}.tags", mq.tags_any)
            if tag_clause:
                where.append(tag_clause)
                params.extend(tag_params)

            ppl_clause, ppl_params = _like_tokens(f"{meta}.people", mq.people_any)
            if ppl_clause:
                where.append(ppl_clause)
                params.extend(ppl_params)

            sql = (
                f"SELECT {meta}.id, {meta}.day, {meta}.time, {meta}.kind, {meta}.scope, "
                f"substr({meta}.text, 1, 240) AS snip "
                f"FROM {meta} "
            )
            if where:
                sql += "WHERE " + " AND ".join(where) + " "
            sql += "ORDER BY day DESC, time DESC LIMIT ?"
            params.append(int(mq.limit))

            con = self._con()
            try:
                rows = con.execute(sql, params).fetchall()
                return [
                    MemoryHit(
                        id=r["id"], day=r["day"], time=r["time"],
                        kind=r["kind"], scope=r["scope"],
                        snippet=r["snip"], score=0.0,
                    )
                    for r in rows
                ]
            finally:
                con.close()

        # ---- Case B: free-text present (FTS ranking) ----
        match = _fts_safe_query(q)
        if not match:
            # if safe builder strips to nothing, just treat as structured-only
            mq2 = MemoryQuery(
                q="",
                kind=mq.kind, scope=mq.scope,
                tags_any=mq.tags_any, people_any=mq.people_any,
                ids_any=mq.ids_any,
                limit=mq.limit, include_trash=mq.include_trash,
            )
            return self.search(mq2)

        where = [f"{fts} MATCH ?"]
        params: list[object] = [match]

        if mq.kind:
            where.append(f"{meta}.kind=?")
            params.append(mq.kind)
        if mq.scope:
            where.append(f"{meta}.scope=?")
            params.append(mq.scope)

        if mq.ids_any:
            good_ids = [x for x in mq.ids_any if _ID10_RE.match(x)]
            if good_ids:
                where.append("(" + " OR ".join([f"{meta}.id=?" for _ in good_ids]) + ")")
                params.extend(good_ids)

        tag_clause, tag_params = _like_tokens(f"{meta}.tags", mq.tags_any)
        if tag_clause:
            where.append(tag_clause)
            params.extend(tag_params)

        ppl_clause, ppl_params = _like_tokens(f"{meta}.people", mq.people_any)
        if ppl_clause:
            where.append(ppl_clause)
            params.extend(ppl_params)

        sql = (
            f"SELECT {meta}.id, {meta}.day, {meta}.time, {meta}.kind, {meta}.scope, "
            f"snippet({fts}, 1, '[', ']', '…', 14) AS snip, "
            f"bm25({fts}) AS score "
            f"FROM {fts} JOIN {meta} ON {meta}.id = {fts}.id "
            f"WHERE " + " AND ".join(where) +
            " ORDER BY score ASC, day DESC, time DESC LIMIT ?"
        )
        params.append(int(mq.limit))

        con = self._con()
        try:
            try:
                rows = con.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                # Fallback: quote whole query as a phrase (escape quotes)
                params[0] = '"' + q.replace('"', '""') + '"'
                rows = con.execute(sql, params).fetchall()

            return [
                MemoryHit(
                    id=r["id"], day=r["day"], time=r["time"],
                    kind=r["kind"], scope=r["scope"],
                    snippet=r["snip"], score=float(r["score"]),
                )
                for r in rows
            ]
        finally:
            con.close()
