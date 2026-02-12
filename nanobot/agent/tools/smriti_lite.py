"""
Smriti Lite: Single-file, zero-dependency durable memory engine for Nanobot.

- Canonical append-only Markdown files:
        workspace/memory/
        ├── MEMORY.md          # Long-term knowledge
        ├── 2023-10-27.md      # Daily logs
        ├── index.sqlite3      # Search index (auto-rebuilds)
        └── .trash/            # Soft-deleted memories
- SQLite index + optional FTS5 for fast recall
- Soft delete / restore
- Promote daily -> long-term
- #tags / @people extraction + tag suggestions
"""

from __future__ import annotations

import os
import re
import secrets
import sqlite3
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

try:
    import fcntl  # Unix only
except Exception:
    fcntl = None


# ------------------------
# Utils
# ------------------------
def ensure_dir(p: Path) -> Path:
    p = Path(p)
    p.mkdir(parents=True, exist_ok=True)
    return p


def today_date() -> str:
    return datetime.now().astimezone().date().isoformat()


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _now_hms() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _new_id10() -> str:
    return secrets.token_hex(5)


# ------------------------
# Models
# ------------------------
@dataclass(frozen=True)
class MemoryValue:
    id: str
    ts: str
    day: str
    time: str
    scope: str  # "daily" | "long"
    kind: str   # "fact" | "pref" | "decision" | "todo" | "note"
    text: str
    tags: str   # normalized: " tag1 tag2 "
    people: str # normalized: " person1 person2 "
    source: str # markdown filepath


@dataclass(frozen=True)
class MemoryQuery:
    q: str = ""
    kind: str | None = None
    scope: str | None = None
    tags_any: tuple[str, ...] = ()
    people_any: tuple[str, ...] = ()
    ids_any: tuple[str, ...] = ()
    limit: int = 8
    include_trash: bool = False


@dataclass(frozen=True)
class MemoryHit:
    id: str
    day: str
    time: str
    kind: str
    scope: str
    snippet: str
    score: float


# ------------------------
# DB Layer
# ------------------------
_FTS_BAD_CHARS = re.compile(r"""["'*:^()\[\]{}\\]""")
_ID10_RE = re.compile(r"^[0-9a-f]{10}$")


def _like_tokens(col: str, vals: Iterable[str]) -> tuple[str, list[str]]:
    vals2 = [v.strip().lower().lstrip("#@") for v in vals if v and v.strip()]
    if not vals2:
        return "", []
    clauses = [f"{col} LIKE ?" for _ in vals2]
    params = [f"% {v} %" for v in vals2]
    return "(" + " OR ".join(clauses) + ")", params


def _fts_safe_query(q: str) -> str:
    q = (q or "").strip()
    if not q:
        return ""
    toks = [t for t in q.split() if t.strip()]
    if not toks:
        return ""
    out: list[str] = []
    for t in toks:
        if _FTS_BAD_CHARS.search(t):
            t2 = t.replace('"', '""')
            out.append(f'"{t2}"')
        else:
            out.append(t)
    return " AND ".join(out)


class MemoryDB:
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

            con.execute("CREATE INDEX IF NOT EXISTS mem_day_time_idx ON mem(day DESC, time DESC)")
            con.execute("CREATE INDEX IF NOT EXISTS mem_kind_idx ON mem(kind)")
            con.execute("CREATE INDEX IF NOT EXISTS mem_scope_idx ON mem(scope)")
            con.execute("CREATE INDEX IF NOT EXISTS trash_deleted_idx ON trash(deleted_ts DESC)")

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

    def recent_vocab(self, *, rows: int, include_trash: bool) -> dict[str, list[tuple[str, int]]]:
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
            ct_tags.update((r["tags"] or "").split())
            ct_ppl.update((r["people"] or "").split())
        return {"tags": ct_tags.most_common(200), "people": ct_ppl.most_common(200)}

    def search(self, mq: MemoryQuery) -> list[MemoryHit]:
        if not self.fts_ok:
            return []

        meta = "trash" if mq.include_trash else "mem"
        fts = "trash_fts" if mq.include_trash else "mem_fts"
        q = (mq.q or "").strip()

        # Structured-only query: no MATCH
        if not q:
            where: list[str] = []
            params: list[object] = []

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

        # Free-text present (FTS ranking)
        match = _fts_safe_query(q)
        if not match:
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


# ------------------------
# Store Layer
# ------------------------
_TAG_RE = re.compile(r"(?<!\w)#([A-Za-z0-9_\-./]+)")
_PPL_RE = re.compile(r"(?<!\w)@([A-Za-z0-9_\-./]+)")
_ID_INLINE_RE = re.compile(r"\^([0-9a-f]{10})\s*$")
_ID_TOKEN_RE = re.compile(r"^\^([0-9a-f]{10})$")

_STOP = {
    "a","an","the","and","or","but","if","then","else","for","to","of","in","on","at","by","with","from",
    "is","are","was","were","be","been","being","as","it","this","that","these","those",
    "i","you","we","they","me","him","her","them","my","your","our","their",
    "not","no","yes","ok","okay",
    "note","todo","fact","pref","decision",
    "do","did","done","make","made","go","went","get","got","put","take","took","use","used",
    "today","tomorrow","yesterday","now","later","soon",
}
_TAG_SPLIT = re.compile(r"[_\-\./]+")
_WORD_RE = re.compile(r"[a-z0-9]+")


def _norm_tokens(xs: list[str]) -> str:
    xs2 = [x.strip().lower() for x in xs if x and x.strip()]
    xs2 = sorted(set(xs2))
    return (" " + " ".join(xs2) + " ") if xs2 else " "


def _extract_semantics(text: str) -> tuple[list[str], list[str]]:
    tags = [m.group(1).lower() for m in _TAG_RE.finditer(text or "")]
    ppl = [m.group(1).lower() for m in _PPL_RE.finditer(text or "")]
    return sorted(set(tags)), sorted(set(ppl))


def _infer_kind(kind: Optional[str], text: str) -> str:
    k = (kind or "").strip().lower()
    if k in ("fact", "pref", "decision", "todo", "note"):
        return k
    t = (text or "").lstrip().lower()
    for prefix, kk in (
        ("fact:", "fact"),
        ("pref:", "pref"),
        ("decision:", "decision"),
        ("todo:", "todo"),
        ("note:", "note"),
    ):
        if t.startswith(prefix):
            return kk
    return "note"


_LINE_RE = re.compile(
    r"""^\s*-\s*\[([0-9:\- ]+)\]\s*\((fact|pref|decision|todo|note)\)\s*(.*?)\s*\^([0-9a-f]{10})\s*$""",
    re.IGNORECASE,
)


class MemoryStore:
    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)
        self.memory_dir = ensure_dir(self.workspace / "memory")
        self.trash_dir = ensure_dir(self.memory_dir / ".trash")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.db = MemoryDB(self.memory_dir / "index.sqlite3")
        self._vocab_cache: dict | None = None
        self._vocab_cache_ts: float = 0.0

    def _day_file(self, day: str) -> Path:
        return self.memory_dir / f"{day}.md"

    def _trash_file(self, day: str) -> Path:
        return self.trash_dir / f"{day}.md"

    def _lock_fd(self, fd) -> None:
        if fcntl is None:
            return
        fcntl.flock(fd, fcntl.LOCK_EX)

    def _unlock_fd(self, fd) -> None:
        if fcntl is None:
            return
        fcntl.flock(fd, fcntl.LOCK_UN)

    def _ensure_header(self, path: Path, title: str) -> None:
        if path.exists():
            return
        path.write_text(f"# {title}\n\n", encoding="utf-8")

    # ---- convenience reads ----
    def read_long_term(self) -> str:
        return self.memory_file.read_text(encoding="utf-8") if self.memory_file.exists() else ""

    def read_today_tail(self, tail_lines: int = 80) -> str:
        p = self._day_file(today_date())
        if not p.exists():
            return ""
        lines = p.read_text(encoding="utf-8").splitlines()
        return ("\n".join(lines[-int(tail_lines):]).strip() + "\n") if lines else ""

    # ---- query parsing ----
    def parse_query(self, query: str, *, limit: int = 8, include_trash: bool = False) -> MemoryQuery:
        s = (query or "").strip()
        if not s:
            return MemoryQuery(limit=int(limit), include_trash=bool(include_trash))

        kind: str | None = None
        scope: str | None = None
        tags: list[str] = []
        ppl: list[str] = []
        ids: list[str] = []
        terms: list[str] = []

        for tok in s.split():
            tl = tok.lower()

            if tl.startswith("kind:"):
                kind = tl.split(":", 1)[1].strip()
                continue

            if tl.startswith("scope:"):
                scope = tl.split(":", 1)[1].strip()
                continue

            if tok.startswith("#"):
                tags.append(tok[1:])
                continue

            if tok.startswith("@"):
                ppl.append(tok[1:])
                continue

            m_id = _ID_TOKEN_RE.match(tok)
            if m_id:
                ids.append(m_id.group(1))
                continue

            terms.append(tok)

        if kind is not None and kind not in ("fact", "pref", "decision", "todo", "note"):
            kind = None

        if scope in ("long", "pinned"):
            scope2 = "long"
        elif scope == "daily":
            scope2 = "daily"
        else:
            scope2 = None

        return MemoryQuery(
            q=" ".join(terms),
            kind=kind,
            scope=scope2,
            tags_any=tuple(tags),
            people_any=tuple(ppl),
            ids_any=tuple(ids),
            limit=int(limit),
            include_trash=bool(include_trash),
        )

    # ---- core ops ----
    def remember(self, text: str, *, kind: str | None = None, scope: str = "daily") -> str:
        text2 = (text or "").strip()
        if not text2:
            raise ValueError("empty memory")

        day = today_date()
        ts_iso = _now_iso()
        hms = _now_hms()
        mid = _new_id10()

        k = _infer_kind(kind, text2)
        tags, ppl = _extract_semantics(text2)

        scope2 = scope.strip().lower() if scope else "daily"
        if scope2 in ("long", "pinned"):
            scope2 = "long"
        elif scope2 != "daily":
            scope2 = "daily"

        if scope2 == "long":
            path = self.memory_file
            self._ensure_header(path, "Long-term Memory")
            line = f"- [{day} {hms}] ({k}) {text2} ^{mid}\n"
        else:
            path = self._day_file(day)
            self._ensure_header(path, day)
            line = f"- [{hms}] ({k}) {text2} ^{mid}\n"

        with path.open("a", encoding="utf-8") as f:
            self._lock_fd(f.fileno())
            try:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
            finally:
                self._unlock_fd(f.fileno())

        v = MemoryValue(
            id=mid,
            ts=ts_iso,
            day=day,
            time=hms,
            scope=scope2,
            kind=k,
            text=text2,
            tags=_norm_tokens(tags),
            people=_norm_tokens(ppl),
            source=str(path),
        )
        self.db.upsert_mem(v)
        return mid

    def recall(self, query: str, *, limit: int = 8, include_trash: bool = False) -> list[MemoryHit]:
        mq = self.parse_query(query, limit=limit, include_trash=include_trash)
        hits = self.db.search(mq)
        if hits:
            return hits
        return self._scan_recall(mq)

    def soft_forget(self, mid: str) -> str:
        mid2 = (mid or "").strip().lstrip("^")
        if not mid2:
            return "Missing id."

        v0 = self.db.get_mem(mid2)
        if not v0:
            return f"Not found: ^{mid2}"

        dst = self._trash_file(v0.day)
        self._ensure_header(dst, f"TRASH {v0.day}")

        v = self.db.move_to_trash(mid2, deleted_ts=_now_iso(), trash_file=str(dst))
        if not v:
            return f"Not found: ^{mid2}"

        moved = self._transfer_line(Path(v0.source), dst, mid2, delete_src=True, promote=False, day=None)
        if not moved:
            self._append_synth(dst, v0, promote=False)
        return f"Soft-forgot ^{mid2}"

    def restore(self, mid: str) -> str:
        mid2 = (mid or "").strip().lstrip("^")
        if not mid2:
            return "Missing id."

        v = self.db.restore_from_trash(mid2)
        if not v:
            return f"Not in trash: ^{mid2}"

        dst = self.memory_file if v.scope == "long" else self._day_file(v.day)
        self._ensure_header(dst, "Long-term Memory" if v.scope == "long" else v.day)

        src = self._trash_file(v.day)
        moved = self._transfer_line(src, dst, mid2, delete_src=True, promote=False, day=None)
        if not moved:
            self._append_synth(dst, v, promote=(v.scope == "long"))
        return f"Restored ^{mid2}"

    def promote(self, mid: str, *, remove: bool = True) -> str:
        mid2 = (mid or "").strip().lstrip("^")
        if not mid2:
            return "Missing id."

        v = self.db.get_mem(mid2)
        if not v:
            return f"Not found: ^{mid2}"

        self._ensure_header(self.memory_file, "Long-term Memory")

        moved = self._transfer_line(Path(v.source), self.memory_file, mid2, delete_src=bool(remove), promote=True, day=v.day)
        if not moved:
            self._append_synth(self.memory_file, v, promote=True)

        self.db.update_scope_source(mid2, "long", str(self.memory_file))
        return f"Promoted ^{mid2}" + ("" if remove else " (copied)")

    # ---- vocab + tag suggestion ----
    def vocab(self, *, rows: int = 5000, include_trash: bool = False, ttl_s: float = 5.0) -> dict[str, list[tuple[str, int]]]:
        now = time.time()
        if (not include_trash) and self._vocab_cache and (now - self._vocab_cache_ts) < float(ttl_s):
            return self._vocab_cache

        v = self.db.recent_vocab(rows=int(rows), include_trash=bool(include_trash))
        if not include_trash:
            self._vocab_cache = v
            self._vocab_cache_ts = now
        return v

    def suggest_tags(self, text: str, *, max_tags: int = 2, min_count: int = 2, rows: int = 5000) -> list[str]:
        s = (text or "").lower()
        toks = [t for t in _WORD_RE.findall(s) if (len(t) >= 3 and t not in _STOP)]
        if not toks:
            return []
        tokset = set(toks)

        vocab = self.vocab(rows=rows, include_trash=False)
        cands: list[tuple[int, str]] = []
        for tag, count in vocab.get("tags", []):
            if count < int(min_count):
                continue
            parts = [p for p in _TAG_SPLIT.split(tag) if p]
            overlap = sum(1 for p in parts if p in tokset)
            if overlap <= 0:
                continue
            score = (overlap * 100) + min(int(count), 50)
            cands.append((score, tag))
        cands.sort(reverse=True)
        return [t for _, t in cands[: int(max_tags)]]

    # ---- listings + context packing ----
    def list_recent(self, limit: int = 20) -> str:
        vals = self.db.list_recent(limit=limit)
        if not vals:
            return "No recent memory."
        return "\n".join([f"- ({v.day} {v.time}) ^{v.id} ({v.kind}/{v.scope}) {v.text}" for v in vals])

    def list_trash(self, limit: int = 20) -> str:
        rows = self.db.list_trash(limit=limit)
        if not rows:
            return "Trash empty."
        return "\n".join([f"- ^{r['id']} deleted {r['deleted_ts']} from {r['source']}" for r in rows])

    def get_memory_context(self, *, long_chars: int = 1200, recent_n: int = 10, today_tail_lines: int = 80) -> str:
        parts: list[str] = []

        lt = self.read_long_term().strip()
        if lt:
            if len(lt) > int(long_chars):
                lt = lt[: int(long_chars)] + "\n…(use recall for more)"
            parts.append("## Long-term Memory\n" + lt)

        recent = self.list_recent(limit=int(recent_n))
        if recent and "No recent" not in recent:
            parts.append("## Recent Memory\n" + recent)

        today_tail = self.read_today_tail(int(today_tail_lines)).strip()
        if today_tail:
            parts.append("## Today (tail)\n" + today_tail)

        return "\n\n".join(parts).strip()

    # ---- internal: scan fallback ----
    def _scan_recall(self, mq: MemoryQuery) -> list[MemoryHit]:
        q = (mq.q or "").strip().lower()
        tags_any = tuple(t.strip().lower().lstrip("#") for t in mq.tags_any if t and t.strip())
        ppl_any = tuple(p.strip().lower().lstrip("@") for p in mq.people_any if p and p.strip())
        ids_any = tuple(i.strip().lower().lstrip("^") for i in mq.ids_any if i and i.strip())

        def line_ok(ln: str) -> bool:
            lo = ln.lower()
            if "^" not in lo:
                return False
            if q and q not in lo:
                return False
            if mq.kind and f"({mq.kind})" not in lo:
                return False
            for t in tags_any:
                if f"#{t}" not in lo:
                    return False
            for p in ppl_any:
                if f"@{p}" not in lo:
                    return False
            return True

        out: list[MemoryHit] = []

        # Targeted id lookup
        if ids_any:
            targets = set(i for i in ids_any if _ID10_RE.match(i))
        else:
            targets = set()

        if mq.include_trash:
            files = sorted(self.trash_dir.glob("????-??-??.md"), reverse=True)
        else:
            files = sorted(self.memory_dir.glob("????-??-??.md"), reverse=True)
            if mq.scope in (None, "long") and self.memory_file.exists():
                files = [self.memory_file] + files
            if mq.scope == "daily":
                files = [f for f in files if f != self.memory_file]

        for fp in files:
            try:
                lines = fp.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue

            for ln in lines:
                m = _ID_INLINE_RE.search(ln)
                if not m:
                    continue
                mid = m.group(1)
                if targets and mid not in targets:
                    continue
                if not line_ok(ln):
                    continue

                day, tm, kind, scope = self._extract_line_meta(fp, ln)
                out.append(MemoryHit(mid, day, tm, kind, scope, ln[:240], 0.0))
                if len(out) >= mq.limit:
                    return out

        return out

    def _extract_line_meta(self, fp: Path, ln: str) -> tuple[str, str, str, str]:
        # defaults
        scope = "long" if fp.name == "MEMORY.md" else "daily"
        day = fp.stem if fp.name != "MEMORY.md" else "----"
        tm = "--:--:--"
        kind = "note"

        m = _LINE_RE.match(ln.strip())
        if not m:
            return day, tm, kind, scope

        when = m.group(1).strip()
        kind = m.group(2).lower()
        # m.group(3) is text, m.group(4) is id

        # when is either "HH:MM:SS" or "YYYY-MM-DD HH:MM:SS"
        if len(when) >= 19 and " " in when:
            parts = when.split()
            if len(parts) >= 2:
                day = parts[0]
                tm = parts[1]
            scope = "long"
        else:
            tm = when
            if fp.name != "MEMORY.md":
                day = fp.stem
            scope = "daily"

        return day, tm, kind, scope

    # ---- internal: file transfer + synth append ----
    def _append_synth(self, dst: Path, v: MemoryValue, *, promote: bool) -> None:
        if promote:
            line = f"- [{v.day} {v.time}] ({v.kind}) {v.text} ^{v.id}\n"
            self._ensure_header(dst, "Long-term Memory")
        else:
            # if dst is a day-specific file, keep daily-style; otherwise keep long-style
            if dst.name == "MEMORY.md":
                line = f"- [{v.day} {v.time}] ({v.kind}) {v.text} ^{v.id}\n"
                self._ensure_header(dst, "Long-term Memory")
            else:
                title = dst.stem
                self._ensure_header(dst, f"TRASH {title}" if dst.parent.name == ".trash" else title)
                line = f"- [{v.time}] ({v.kind}) {v.text} ^{v.id}\n"
        with dst.open("a", encoding="utf-8") as f:
            self._lock_fd(f.fileno())
            try:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
            finally:
                self._unlock_fd(f.fileno())

    def _transfer_line(self, src: Path, dst: Path, mid: str, *, delete_src: bool, promote: bool, day: str | None) -> bool:
        if not src.exists():
            return False

        needle = f"^{mid}"
        try:
            lines = src.read_text(encoding="utf-8").splitlines(True)
        except Exception:
            return False

        keep: list[str] = []
        picked: str | None = None

        for ln in lines:
            if needle in ln:
                picked = ln if ln.endswith("\n") else ln + "\n"
                if not delete_src:
                    keep.append(ln)
            else:
                keep.append(ln)

        if picked is None:
            return False

        # Promote daily -> long: rewrite bracket time
        if promote and day and picked.startswith("- [") and "]" in picked:
            m = re.match(r"- \[(\d\d:\d\d:\d\d)\]\s+(.*)$", picked.strip())
            if m:
                picked = f"- [{day} {m.group(1)}] {m.group(2)}\n"

        if delete_src:
            tmp_path = None
            try:
                fd, tmp_path = tempfile.mkstemp(prefix=src.name + ".", dir=str(src.parent))
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write("".join(keep))
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, src)
                tmp_path = None
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass

        # Ensure dst header
        if dst.name == "MEMORY.md":
            self._ensure_header(dst, "Long-term Memory")
        else:
            title = dst.stem
            if dst.parent.name == ".trash":
                self._ensure_header(dst, f"TRASH {title}")
            else:
                self._ensure_header(dst, title)

        with dst.open("a", encoding="utf-8") as f:
            self._lock_fd(f.fileno())
            try:
                f.write(picked)
                f.flush()
                os.fsync(f.fileno())
            finally:
                self._unlock_fd(f.fileno())

        return True


__all__ = ["MemoryValue", "MemoryQuery", "MemoryHit", "MemoryStore"]
