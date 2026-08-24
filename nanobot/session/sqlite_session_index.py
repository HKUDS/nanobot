"""SQLite + FTS5 会话搜索索引（只读检索镜像）。

设计目标（JSONL 仍是主存储）：
- 写入路径不变：nanobot 自带 JsonlSessionStore 是全量 JSONL 存储，本次不改
- 本模块作为「查询/持久化镜像」：每次 save 时把会话快照同步一份到 SQLite，
  数据库只用于 search/持久化，不承担主读写
- FTS5 全文索引加速消息检索，避免每次搜索都逐行扫描全部 JSONL
- 任何数据库异常都必须静默降级（不阻塞主存储写入）：调用方 try/except 兜底

表结构：
- sessions:   会话元信息（key/title/created_at/updated_at/metadata json）
- messages:   可见消息快照（session_key/message_index/role/content）
- messages_fts: FTS5 虚拟表（content 列，外部内容表挂 messages）
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Mapping, Sequence

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_key TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS messages (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    session_key TEXT NOT NULL,
    message_index INTEGER NOT NULL,
    role TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    UNIQUE (session_key, message_index)
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_key);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    content='messages',
    content_rowid='rowid',
    tokenize='unicode61',
    detail=full
);

CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content) VALUES (new.rowid, new.content);
END;
CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.rowid, old.content);
END;
CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.rowid, old.content);
    INSERT INTO messages_fts(rowid, content) VALUES (new.rowid, new.content);
END;
"""


def visible_message_snapshot(message: Mapping[str, Any]) -> dict[str, Any] | None:
    """从原始消息行提取可见消息快照（与 session_access._visible_messages 对齐）。

    只收录 user/assistant 的可见文本；_command 命令、隐藏历史（_hidden_history /
    automation）与运行时上下文标记一律不入库，保证搜索结果的可见性与 JSONL
    逐文件扫描完全一致。
    """
    role = message.get("role")
    if role not in ("user", "assistant") or message.get("_command"):
        return None
    from nanobot.session.history_visibility import is_hidden_history_message

    if is_hidden_history_message(message):
        return None
    from nanobot.runtime_context import public_history_message

    public = public_history_message(message)
    raw_content = public.get("content")
    if isinstance(raw_content, str):
        text = raw_content.strip()
    elif isinstance(raw_content, list):
        parts: list[str] = []
        for block in raw_content:
            if isinstance(block, dict) and block.get("type") == "text":
                txt = block.get("text")
                if isinstance(txt, str):
                    parts.append(txt)
        text = "\n".join(parts).strip()
    else:
        text = ""
    if not text:
        return None
    return {"role": role, "content": text}


class SessionSqliteIndex:
    """只读检索镜像：SQLite 存储 + FTS5 全文索引。

    所有公开方法都是尽力而为：内部异常向上抛，由调用方（SessionManager /
    WebuiSessionAccess）捕获并降级，绝不会让数据库成为主流程的断点。
    """

    def __init__(self, db_path: Path | str, *, timeout: float = 5.0) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self._path),
            timeout=timeout,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------------ write

    def upsert_session(
        self,
        session_key: str,
        *,
        title: str = "",
        created_at: str = "",
        updated_at: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO sessions(session_key, title, created_at, updated_at, metadata)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_key) DO UPDATE SET
                    title=excluded.title,
                    created_at=excluded.created_at,
                    updated_at=excluded.updated_at,
                    metadata=excluded.metadata
                """,
                (
                    session_key,
                    (title or "")[:1000],
                    created_at or "",
                    updated_at or "",
                    json.dumps(dict(metadata or {}), ensure_ascii=False),
                ),
            )
            self._conn.commit()

    def upsert_messages(
        self,
        session_key: str,
        messages: Sequence[dict[str, Any]],
        *,
        message_offset: int | None = None,
    ) -> int:
        """全量覆盖某个会话的消息快照（先删后插，与 JSONL 全量写入语义对齐）。"""
        with self._lock:
            self._conn.execute("DELETE FROM messages WHERE session_key = ?", (session_key,))
            seen: dict[int, tuple[str, str]] = {}
            base = message_offset if message_offset is not None else 0
            for idx, msg in enumerate(messages):
                snap = visible_message_snapshot(msg)
                if snap is None:
                    continue
                seen[idx + base] = (snap["role"], snap["content"])
            self._conn.executemany(
                """
                INSERT INTO messages(session_key, message_index, role, content)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (session_key, index, role, content)
                    for index, (role, content) in seen.items()
                ],
            )
            self._conn.commit()
            return len(seen)

    def delete_session(self, session_key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM messages WHERE session_key = ?", (session_key,))
            self._conn.execute("DELETE FROM sessions WHERE session_key = ?", (session_key,))
            self._conn.commit()

    # ------------------------------------------------------------------ search

    def search(
        self,
        query: str,
        limit: int,
        *,
        exclude_session_key: str | None = None,
    ) -> list[dict[str, Any]]:
        """检索历史会话消息。

        - 阶段 1：标题匹配（精确/前缀/包含），rank 由高到低
        - 阶段 2：FTS5 全文检索消息正文
        - 阶段 3：LIKE 兜底（FTS5 分词不友好时的中文/符号查询）

        返回结构与 WebuiSessionAccess.search 一致：
        [{session_key, title, updated_at, messages: [{message_index, role, content}]}]
        """
        needle = query.strip().casefold()
        if not needle:
            return []
        with self._lock:
            rows = self._conn.execute(
                "SELECT session_key, title, updated_at FROM sessions ORDER BY updated_at DESC"
            ).fetchall()
        exclude: set[str] = set()
        if exclude_session_key:
            exclude.add(exclude_session_key)

        ranked: list[tuple[int, dict[str, Any]]] = []
        remaining: list[str] = []
        for row in rows:
            key = str(row["session_key"])
            if key in exclude:
                continue
            title = (row["title"] or "").strip()
            folded = title.casefold()
            rank = (
                0 if folded == needle
                else 1 if folded.startswith(needle)
                else 2 if needle in folded
                else None
            )
            if rank is None:
                remaining.append(key)
                continue
            ranked.append((rank, {
                "session_key": key,
                "title": title,
                "updated_at": row["updated_at"],
                "messages": [],
            }))

        needed = max(0, limit - len(ranked))
        if needed > 0:
            # 对所有 remaining 会话做 LIKE 消息正文匹配（SQLite 扫描，比
            # 逐文件读 JSONL 快得多）。FTS5 只做加速器，不依赖它做准入门禁。
            for key in remaining:
                if needed <= 0:
                    break
                matched = self._message_matches(key, needle)
                if not matched:
                    continue
                ranked.append((3, {
                    "session_key": key,
                    "title": self._title_for(key),
                    "updated_at": self._updated_for(key),
                    "messages": matched[-2:],
                }))
                needed -= 1

        ranked.sort(key=lambda item: item[0])
        return [item[1] for item in ranked[:limit]]

    def _fts_hit_session_keys(
        self,
        query: str,
        exclude: set[str],
    ) -> set[str]:
        """FTS5 检索：把查询拆成词条做 MATCH，返回命中的 session_key 集合。

        unicode61 分词对中文不友好（默认按整段 token），所以失败/零命中时
        返回空集由 LIKE 兜底；查询词含空格/引号时自动转义。
        """
        terms = [tok for tok in query.split() if tok]
        if not terms:
            return set()
        # 用双引号包裹每个词，避免特殊字符破坏 MATCH 语法
        match_expr = " AND ".join(f'"{t.replace(chr(34), "")}"' for t in terms)
        try:
            with self._lock:
                rows = self._conn.execute(
                    "SELECT DISTINCT session_key FROM messages_fts WHERE messages_fts MATCH ?",
                    (match_expr,),
                ).fetchall()
        except sqlite3.OperationalError:
            return set()
        return {str(r["session_key"]) for r in rows if str(r["session_key"]) not in exclude}

    def _message_matches(
        self,
        session_key: str,
        needle: str,
    ) -> list[dict[str, Any]]:
        """会话内按消息正文匹配（casefold 包含），返回前若干条命中消息。"""
        try:
            with self._lock:
                rows = self._conn.execute(
                    """
                    SELECT message_index, role, content
                    FROM messages
                    WHERE session_key = ? AND content <> ''
                    ORDER BY message_index
                    """,
                    (session_key,),
                ).fetchall()
        except sqlite3.Error:
            return []
        matched = []
        for row in rows:
            content = str(row["content"])
            if needle in content.casefold():
                matched.append({
                    "message_index": int(row["message_index"]),
                    "role": str(row["role"]),
                    "content": content,
                })
        return matched

    def _title_for(self, session_key: str) -> str:
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT title FROM sessions WHERE session_key = ?", (session_key,)
                ).fetchone()
        except sqlite3.Error:
            return ""
        return str(row["title"]) if row else ""

    def _updated_for(self, session_key: str) -> str | None:
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT updated_at FROM sessions WHERE session_key = ?", (session_key,)
                ).fetchone()
        except sqlite3.Error:
            return None
        if row is None:
            return None
        value = str(row["updated_at"])
        return value or None

    # ------------------------------------------------------------------ misc

    def count_messages(self) -> int:
        try:
            with self._lock:
                row = self._conn.execute("SELECT COUNT(*) AS n FROM messages").fetchone()
            return int(row["n"]) if row else 0
        except sqlite3.Error:
            return 0

    def has_session(self, session_key: str) -> bool:
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT 1 FROM sessions WHERE session_key = ?", (session_key,)
                ).fetchone()
            return row is not None
        except sqlite3.Error:
            return False

    def close(self) -> None:
        try:
            with self._lock:
                self._conn.close()
        except sqlite3.Error:
            pass