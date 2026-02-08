"""
memory_box.store

High-level memory store for Nanobot.

Responsibilities:
- Append-only canonical Markdown storage:
    * workspace/memory/YYYY-MM-DD.md   (daily)
    * workspace/memory/MEMORY.md       (curated long-term)
    * workspace/memory/.trash/YYYY-MM-DD.md (soft-deleted)
- Lightweight semantic extraction:
    * #tags and @people parsed from text and normalized for filtering.
- Fast recall via SQLite + optional FTS5 (delegated to MemoryDB), with a
  file-scan fallback when FTS is unavailable.
- Operations:
    remember / recall / soft_forget / restore / promote
  using stable short ids (e.g. ^<10-hex>).

Query mini-syntax:
- kind:<fact|pref|decision|todo|note>
- scope:<daily|long|pinned>
- #tag  @person  plus free-text terms

Author: Arghya Ranjan Das
"""

from __future__ import annotations

import os
import re
import secrets
import tempfile
import time
from datetime import datetime
from pathlib import Path

try:
    import fcntl  # Linux/Unix
except Exception:
    fcntl = None

from .db import MemoryDB
from .models import MemoryValue, MemoryQuery, MemoryHit
from .utils import ensure_dir, today_date


# ---- parsing regex ----
_TAG_RE = re.compile(r"(?<!\w)#([A-Za-z0-9_\-./]+)")
_PPL_RE = re.compile(r"(?<!\w)@([A-Za-z0-9_\-./]+)")
_ID_INLINE_RE = re.compile(r"\^([0-9a-f]{10})\s*$")
_ID_TOKEN_RE = re.compile(r"^\^([0-9a-f]{10})$")

# ---- tag suggestion helpers ----
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


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _now_hms() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _new_id10() -> str:
    return secrets.token_hex(5)


def _norm_tokens(xs: list[str]) -> str:
    xs = [x.strip().lower() for x in xs if x and x.strip()]
    xs = sorted(set(xs))
    return (" " + " ".join(xs) + " ") if xs else " "


def _extract_semantics(text: str) -> tuple[list[str], list[str]]:
    tags = [m.group(1).lower() for m in _TAG_RE.finditer(text or "")]
    ppl = [m.group(1).lower() for m in _PPL_RE.finditer(text or "")]
    return sorted(set(tags)), sorted(set(ppl))


def _infer_kind(kind: str | None, text: str) -> str:
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


class MemoryStore:
    """
    Strong minimal memory:
      - canonical markdown files
      - SQLite index (+ FTS if available)
      - tags/people extraction
      - soft delete/restore
      - promote daily -> long
      - vocab() + suggest_tags() for agent tag reuse
    """

    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)
        self.memory_dir = ensure_dir(self.workspace / "memory")
        self.trash_dir = ensure_dir(self.memory_dir / ".trash")
        self.memory_file = self.memory_dir / "MEMORY.md"

        self.db = MemoryDB(self.memory_dir / "index.sqlite3")

        # vocab cache (avoid spamming DB when agent asks repeatedly)
        self._vocab_cache: dict | None = None
        self._vocab_cache_ts: float = 0.0

    # ---- paths ----
    def _day_file(self, day: str) -> Path:
        return self.memory_dir / f"{day}.md"

    def _trash_file(self, day: str) -> Path:
        return self.trash_dir / f"{day}.md"

    # ---- file locking ----
    def _lock_fd(self, fd):
        if fcntl is None:
            return
        fcntl.flock(fd, fcntl.LOCK_EX)

    def _unlock_fd(self, fd):
        if fcntl is None:
            return
        fcntl.flock(fd, fcntl.LOCK_UN)

    # ---- headers ----
    def _ensure_header(self, path: Path, title: str) -> None:
        if path.exists():
            return
        path.write_text(f"# {title}\n\n", encoding="utf-8")

    # ---- read helpers ----
    def read_long_term(self) -> str:
        return self.memory_file.read_text(encoding="utf-8") if self.memory_file.exists() else ""

    def read_today_tail(self, tail_lines: int = 80) -> str:
        p = self._day_file(today_date())
        if not p.exists():
            return ""
        lines = p.read_text(encoding="utf-8").splitlines()
        return ("\n".join(lines[-tail_lines:]).strip() + "\n") if lines else ""

    # ---- query parsing ----
    def parse_query(self, query: str, *, limit: int = 8, include_trash: bool = False) -> MemoryQuery:
        s = (query or "").strip()
        if not s:
            return MemoryQuery(limit=int(limit), include_trash=bool(include_trash))

        kind = None
        scope = None
        tags: list[str] = []
        ppl: list[str] = []
        ids: list[str] = []
        terms: list[str] = []

        for tok in s.split():
            tl = tok.lower()

            if tl.startswith("kind:"):
                kind = tl.split(":", 1)[1]
                continue

            if tl.startswith("scope:"):
                scope = tl.split(":", 1)[1]
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

        kind2 = _infer_kind(kind, "") if kind else None
        scope2 = ("long" if scope in ("long", "pinned") else ("daily" if scope == "daily" else None))

        return MemoryQuery(
            q=" ".join(terms),
            kind=kind2,
            scope=scope2,
            tags_any=tuple(tags),
            people_any=tuple(ppl),
            ids_any=tuple(ids),
            limit=int(limit),
            include_trash=bool(include_trash),
        )

    # ---- core ops ----
    def remember(self, text: str, *, kind: str | None = None, scope: str = "daily") -> str:
        text = (text or "").strip()
        if not text:
            raise ValueError("empty memory")

        day = today_date()
        ts_iso = _now_iso()
        hms = _now_hms()
        mid = _new_id10()

        k = _infer_kind(kind, text)
        tags, ppl = _extract_semantics(text)

        if scope not in ("daily", "long"):
            scope = "daily"

        if scope == "long":
            path = self.memory_file
            self._ensure_header(path, "Long-term Memory")
            line = f"- [{day} {hms}] ({k}) {text} ^{mid}\n"
        else:
            path = self._day_file(day)
            self._ensure_header(path, day)
            line = f"- [{hms}] ({k}) {text} ^{mid}\n"

        # locked append (prevents concurrent line interleaving)
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
            scope=scope,
            kind=k,
            text=text,
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
        mid = (mid or "").strip().lstrip("^")
        if not mid:
            return "Missing id."

        v = self.db.move_to_trash(mid, deleted_ts=_now_iso(), trash_file=str(self._trash_file(today_date())))
        if not v:
            return f"Not found: ^{mid}"

        src = Path(v.source)
        dst = self._trash_file(v.day)
        self._ensure_header(dst, f"TRASH {v.day}")

        moved = self._move_line(src, dst, mid)
        return f"Soft-forgot ^{mid}" + ("" if moved else " (DB moved; line not found in file)")

    def restore(self, mid: str) -> str:
        mid = (mid or "").strip().lstrip("^")
        if not mid:
            return "Missing id."

        v = self.db.restore_from_trash(mid)
        if not v:
            return f"Not in trash: ^{mid}"

        dst = self.memory_file if v.scope == "long" else self._day_file(v.day)
        self._ensure_header(dst, "Long-term Memory" if v.scope == "long" else v.day)

        src = self._trash_file(v.day)
        moved = self._move_line(src, dst, mid)
        if not moved:
            # synthesize if line not found
            line = (
                f"- [{v.day} {v.time}] ({v.kind}) {v.text} ^{v.id}\n"
                if v.scope == "long"
                else f"- [{v.time}] ({v.kind}) {v.text} ^{v.id}\n"
            )
            with dst.open("a", encoding="utf-8") as f:
                self._lock_fd(f.fileno())
                try:
                    f.write(line)
                    f.flush()
                    os.fsync(f.fileno())
                finally:
                    self._unlock_fd(f.fileno())

        return f"Restored ^{mid}"

    def promote(self, mid: str, *, remove: bool = True) -> str:
        """
        Curate a high-value item into MEMORY.md (long-term).
        If remove=True, removes from daily file (keeps daily lightweight).
        """
        mid = (mid or "").strip().lstrip("^")
        if not mid:
            return "Missing id."

        v = self.db.get_mem(mid)
        if not v:
            return f"Not found in active memory: ^{mid}"

        self._ensure_header(self.memory_file, "Long-term Memory")

        src = Path(v.source)
        if src.exists() and self._has_id(src, mid):
            if remove:
                moved = self._move_line(src, self.memory_file, mid, promote=True, day=v.day)
            else:
                moved = self._copy_line(src, self.memory_file, mid, promote=True, day=v.day)
            if not moved:
                self._append_longterm_line(v)
        else:
            self._append_longterm_line(v)

        self.db.update_scope_source(mid, "long", str(self.memory_file))
        return f"Promoted ^{mid} -> MEMORY.md" + ("" if remove else " (copied)")

    # ---- vocab + suggestions (for agent) ----
    def vocab(self, *, rows: int = 5000, include_trash: bool = False, ttl_s: float = 5.0) -> dict[str, list[tuple[str, int]]]:
        now = time.time()
        if (not include_trash) and self._vocab_cache and (now - self._vocab_cache_ts) < float(ttl_s):
            return self._vocab_cache

        v = self.db.recent_vocab(rows=int(rows), include_trash=bool(include_trash))

        if not include_trash:
            self._vocab_cache = v
            self._vocab_cache_ts = now
        return v

    def suggest_tags(
        self,
        text: str,
        *,
        max_tags: int = 2,
        min_count: int = 2,
        max_count: int | None = None,
        rows: int = 5000,
    ) -> list[str]:
        """
        Suggest existing tags (WITHOUT '#') to reuse for `text`.

        Heuristic:
        - tokenize text into [a-z0-9]+
        - compare against parts of each existing tag split on _-./
        - score by overlap + frequency
        """
        s = (text or "").lower()
        toks = [t for t in _WORD_RE.findall(s) if (len(t) >= 3 and t not in _STOP)]
        if not toks:
            return []
        tokset = set(toks)

        vocab = self.vocab(rows=rows, include_trash=False)
        candidates: list[tuple[int, str]] = []

        for tag, count in vocab.get("tags", []):
            if count < int(min_count):
                continue
            if max_count is not None and count > int(max_count):
                continue

            parts = [p for p in _TAG_SPLIT.split(tag) if p]
            overlap = sum(1 for p in parts if p in tokset)
            if overlap <= 0:
                continue

            score = (overlap * 100) + min(int(count), 50)
            candidates.append((score, tag))

        candidates.sort(reverse=True)
        return [t for _, t in candidates[: int(max_tags)]]

    # ---- listings / context ----
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

    def get_memory_context(self, *, long_chars: int = 1200, recent_n: int = 10) -> str:
        parts: list[str] = []
        lt = self.read_long_term().strip()
        if lt:
            if len(lt) > long_chars:
                lt = lt[:long_chars] + "\n…(use memory:recall for more)"
            parts.append("## Long-term Memory\n" + lt)

        recent = self.list_recent(limit=recent_n)
        if recent and "No recent" not in recent:
            parts.append("## Recent Memory\n" + recent)

        today = self.read_today_tail(80).strip()
        if today:
            parts.append("## Today (tail)\n" + today)

        return "\n\n".join(parts).strip()

    # ---- fallback scan (no FTS) ----
    def _scan_recall(self, mq: MemoryQuery) -> list[MemoryHit]:
        root = self.trash_dir if mq.include_trash else self.memory_dir
        files = sorted(root.glob("????-??-??.md"), reverse=True)

        q = (mq.q or "").lower()
        out: list[MemoryHit] = []

        for fp in files:
            for ln in fp.read_text(encoding="utf-8").splitlines():
                if "^" not in ln:
                    continue
                if q and q not in ln.lower():
                    continue
                m = _ID_INLINE_RE.search(ln)
                if not m:
                    continue
                out.append(
                    MemoryHit(
                        id=m.group(1),
                        day=fp.stem,
                        time="--:--:--",
                        kind="note",
                        scope="daily",
                        snippet=ln[:240],
                        score=0.0,
                    )
                )
                if len(out) >= mq.limit:
                    return out
        return out

    # ---- file transfer helpers (atomic rewrite) ----
    def _has_id(self, path: Path, mid: str) -> bool:
        return f"^{mid}" in path.read_text(encoding="utf-8")

    def _move_line(self, src: Path, dst: Path, mid: str, *, promote: bool = False, day: str | None = None) -> bool:
        return self._transfer_line(src, dst, mid, delete_src=True, promote=promote, day=day)

    def _copy_line(self, src: Path, dst: Path, mid: str, *, promote: bool = False, day: str | None = None) -> bool:
        return self._transfer_line(src, dst, mid, delete_src=False, promote=promote, day=day)

    def _transfer_line(self, src: Path, dst: Path, mid: str, *, delete_src: bool, promote: bool, day: str | None) -> bool:
        if not src.exists():
            return False

        needle = f"^{mid}"
        lines = src.read_text(encoding="utf-8").splitlines(True)

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

        # If promoting daily -> long, rewrite timestamp:
        if promote and day and picked.startswith("- [") and "]" in picked:
            m = re.match(r"- \[(\d\d:\d\d:\d\d)\]\s+(.*)$", picked.strip())
            if m:
                picked = f"- [{day} {m.group(1)}] {m.group(2)}\n"

        # Atomic rewrite (avoid partial write on crash)
        if delete_src:
            tmp = None
            try:
                fd, tmp = tempfile.mkstemp(prefix=src.name + ".", dir=str(src.parent))
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write("".join(keep))
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, src)
            finally:
                if tmp and os.path.exists(tmp):
                    try:
                        os.unlink(tmp)
                    except Exception:
                        pass

        # Locked append to dst
        with dst.open("a", encoding="utf-8") as f:
            self._lock_fd(f.fileno())
            try:
                f.write(picked)
                f.flush()
                os.fsync(f.fileno())
            finally:
                self._unlock_fd(f.fileno())

        return True

    def _append_longterm_line(self, v: MemoryValue) -> None:
        line = f"- [{v.day} {v.time}] ({v.kind}) {v.text} ^{v.id}\n"
        self._ensure_header(self.memory_file, "Long-term Memory")
        with self.memory_file.open("a", encoding="utf-8") as f:
            self._lock_fd(f.fileno())
            try:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
            finally:
                self._unlock_fd(f.fileno())
