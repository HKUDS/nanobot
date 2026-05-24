"""Skill 检索索引：SQLite FTS5 目录 + 查询召回。

本模块为渐进式 Skill 加载提供「按 query 选 top-k」能力，配合
``ContextBuilder`` 将检索结果注入 system prompt 的 Skills 摘要段。

架构（两层缓存）：
- **L2 磁盘**：``{workspace}/.nanobot/skill_index.sqlite``
  - ``skills`` 表：name / description / path / requirements 等元数据
  - ``skill_fts`` 虚拟表：FTS5 全文索引（name + description + body_snippet）
  - ``skill_index_meta``：catalog fingerprint、index generation
- **L1 内存**（进程内，gateway 单实例）：
  - catalog 快照缓存：fallback 全量 summary 时避免重复 SELECT
  - query LRU 缓存：相同 (generation, query, exclude) 跳过重复 FTS

失效策略：
- ``catalog_fingerprint`` = 所有 SKILL.md 内容 hash + disabled_skills + index_body_chars
- fingerprint 变化 → ``rebuild()`` → ``generation += 1`` → L1 全部清空
- ``available`` 依赖运行时 env/cli，**不**写入索引世代；``to_summary_dict`` 现场重算

检索失败（DB 损坏、FTS 语法错误等）只打 log，返回 ``[]``，由上层 fallback。
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.skills import SkillsLoader

if TYPE_CHECKING:
    from nanobot.config.schema import SkillRetrievalConfig

# skill_index_meta 表中的键名
_META_GENERATION = "index_generation"      # 索引世代，每次 rebuild +1，用于 L1 cache key
_META_FINGERPRINT = "catalog_fingerprint"  # 目录指纹，用于判断是否需要 rebuild
# FTS query 分词：支持 Unicode（含中文单字）
_FTS_TOKEN_RE = re.compile(r"[\w\u0080-\U0010ffff]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class SkillIndexEntry:
    """索引中的一条 skill 记录；检索时可选附带 bm25 分数。"""

    name: str
    description: str
    path: str
    source: str          # workspace | builtin
    requirements: dict[str, Any]  # requires.bins / requires.env，供运行时重算 available
    score: float | None = None    # bm25 分数，越小越相关（FTS5 约定）

    def to_summary_dict(self, loader: SkillsLoader) -> dict[str, Any]:
        """转为 ``SkillsLoader.build_skills_summary(entries=...)`` 所需的 dict。

        available 在此现场计算，避免 env/cli 变化但索引未 rebuild 时标记过期。
        """
        meta = {"requires": self.requirements}
        available = loader._check_requirements(meta)
        missing = loader._get_missing_requirements(meta) if not available else ""
        return {
            "name": self.name,
            "path": self.path,
            "source": self.source,
            "description": self.description,
            "available": available,
            "missing_requirements": missing,
        }


class SkillIndex:
    """Skill 检索索引：L2 SQLite FTS + L1 进程内缓存。"""

    def __init__(
        self,
        workspace: Path,
        config: SkillRetrievalConfig | None = None,
    ) -> None:
        from nanobot.config.schema import SkillRetrievalConfig

        self._workspace = workspace.expanduser().resolve()
        self._config = config or SkillRetrievalConfig()
        self._db_path = self._workspace / ".nanobot" / "skill_index.sqlite"
        self._lock = threading.RLock()  # gateway 多 session 并发读写的互斥
        self._conn: sqlite3.Connection | None = None
        # L1：全量 catalog 快照（generation 匹配时直接返回）
        self._catalog_cache: list[SkillIndexEntry] | None = None
        self._catalog_generation = -1
        # 内存中的 generation，避免 catalog 命中时仍连库读 meta
        self._generation_memory = -1
        # L1：query → top-k 结果 LRU（OrderedDict 实现）
        self._retrieve_cache: OrderedDict[tuple[Any, ...], list[SkillIndexEntry]] = OrderedDict()

    def close(self) -> None:
        """关闭 SQLite 连接并清空 L1 缓存。"""
        with self._lock:
            self._clear_l1()
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def warm(self, loader: SkillsLoader) -> None:
        """启动预热：若 fingerprint 已变则 rebuild（AgentLoop 启动时调用）。"""
        with self._lock:
            self.ensure_ready(loader)

    def ensure_ready(self, loader: SkillsLoader) -> None:
        """懒检查：目录指纹未变且 generation > 0 则跳过 rebuild。"""
        fingerprint = self._catalog_fingerprint(loader)
        stored_fp = self._read_meta(_META_FINGERPRINT)
        generation = self._get_generation()
        if fingerprint == stored_fp and generation > 0:
            return
        self.rebuild(loader)

    def rebuild(self, loader: SkillsLoader) -> None:
        """全量扫描 loader 中的 skill，刷新 skills 表并重建 FTS 索引。"""
        with self._lock:
            try:
                conn = self._connect()
                # 包含 unavailable skill（requirements 未满足仍索引，summary 会标注 unavailable）
                entries = loader.list_skills(filter_unavailable=False)
                seen: set[str] = set()
                index_body_chars = self._config.index_body_chars

                for entry in entries:
                    name = entry["name"]
                    seen.add(name)
                    path = Path(entry["path"])
                    raw = path.read_bytes()
                    content_hash = hashlib.sha256(raw).hexdigest()
                    mtime_ns = path.stat().st_mtime_ns
                    description = loader._get_skill_description(name)
                    requirements = loader._get_skill_meta(name).get("requires", {})
                    # 可选：索引正文前 N 字符，提升 FTS 对正文关键词的召回
                    body_snippet = ""
                    if index_body_chars > 0:
                        content = raw.decode("utf-8", errors="replace")
                        body = loader._strip_frontmatter(content)
                        body_snippet = body[:index_body_chars]

                    conn.execute(
                        """
                        INSERT INTO skills (
                            name, path, source, description, body_snippet,
                            requirements_json, content_hash, mtime_ns
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(name) DO UPDATE SET
                            path = excluded.path,
                            source = excluded.source,
                            description = excluded.description,
                            body_snippet = excluded.body_snippet,
                            requirements_json = excluded.requirements_json,
                            content_hash = excluded.content_hash,
                            mtime_ns = excluded.mtime_ns
                        """,
                        (
                            name,
                            entry["path"],
                            entry["source"],
                            description,
                            body_snippet,
                            json.dumps(requirements, sort_keys=True),
                            content_hash,
                            mtime_ns,
                        ),
                    )

                # 删除磁盘上已不存在的 skill 行
                if seen:
                    placeholders = ",".join("?" for _ in seen)
                    conn.execute(
                        f"DELETE FROM skills WHERE name NOT IN ({placeholders})",
                        tuple(sorted(seen)),
                    )
                else:
                    conn.execute("DELETE FROM skills")

                # FTS5 external content 表：bulk 变更后必须 rebuild 虚拟表
                conn.execute("INSERT INTO skill_fts(skill_fts) VALUES('rebuild')")
                fingerprint = self._catalog_fingerprint(loader)
                generation = self._get_generation() + 1
                self._write_meta(_META_FINGERPRINT, fingerprint)
                self._write_meta(_META_GENERATION, str(generation))
                self._generation_memory = generation
                conn.commit()
                self._clear_l1()  # 新世代 → 清空 query/catalog L1
                logger.debug(
                    "Skill index rebuilt: {} skills, generation={}",
                    len(seen),
                    generation,
                )
            except Exception as exc:
                logger.warning("Skill index rebuild failed: {}", exc)

    def list_catalog(self, loader: SkillsLoader) -> list[SkillIndexEntry]:
        """返回索引中全部 skill（用于 fallback 全量 summary，优先走 L1）。"""
        with self._lock:
            generation = self._get_generation()
            if (
                self._config.catalog_cache
                and self._catalog_cache is not None
                and self._catalog_generation == generation
            ):
                return list(self._catalog_cache)

            try:
                conn = self._connect()
                rows = conn.execute(
                    """
                    SELECT name, path, source, description, requirements_json
                    FROM skills
                    ORDER BY name
                    """
                ).fetchall()
            except Exception as exc:
                logger.warning("Skill index catalog read failed: {}", exc)
                return []

            entries = [
                SkillIndexEntry(
                    name=row["name"],
                    description=row["description"],
                    path=row["path"],
                    source=row["source"],
                    requirements=json.loads(row["requirements_json"] or "{}"),
                )
                for row in rows
            ]
            if self._config.catalog_cache:
                self._catalog_cache = list(entries)
                self._catalog_generation = generation
            return entries

    def retrieve(
        self,
        query: str,
        *,
        loader: SkillsLoader,
        k: int,
        exclude: set[str] | None = None,
        min_score: float | None = None,
    ) -> list[SkillIndexEntry]:
        """按 query 做 FTS 检索，返回 bm25 排序的 top-k（排除 exclude 中的 name）。"""
        normalized = _normalize_query(query)
        if not normalized:
            return []

        exclude = exclude or set()
        generation = self._get_generation()
        # cache key 含 generation：rebuild 后旧缓存自动失效
        cache_key = (generation, normalized, k, frozenset(exclude), min_score)
        cache_size = self._config.query_cache_size

        with self._lock:
            # L1 query 命中
            if cache_size > 0 and cache_key in self._retrieve_cache:
                self._retrieve_cache.move_to_end(cache_key)
                return list(self._retrieve_cache[cache_key])

            try:
                self.ensure_ready(loader)
                fts_query = _build_fts_query(normalized)
                if not fts_query:
                    return []

                conn = self._connect()
                # bm25(skill_fts) 升序：分数越小相关性越高
                if exclude:
                    placeholders = ",".join("?" for _ in exclude)
                    sql = f"""
                        SELECT s.name, s.path, s.source, s.description, s.requirements_json,
                               bm25(skill_fts) AS score
                        FROM skill_fts
                        JOIN skills s ON s.rowid = skill_fts.rowid
                        WHERE skill_fts MATCH ?
                          AND s.name NOT IN ({placeholders})
                        ORDER BY score
                        LIMIT ?
                    """
                    params: tuple[Any, ...] = (fts_query, *sorted(exclude), k)
                else:
                    sql = """
                        SELECT s.name, s.path, s.source, s.description, s.requirements_json,
                               bm25(skill_fts) AS score
                        FROM skill_fts
                        JOIN skills s ON s.rowid = skill_fts.rowid
                        WHERE skill_fts MATCH ?
                        ORDER BY score
                        LIMIT ?
                    """
                    params = (fts_query, k)

                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError as exc:
                # 常见：MATCH 语法非法、FTS 表损坏
                logger.debug("Skill FTS query failed for {!r}: {}", query, exc)
                return []
            except Exception as exc:
                logger.warning("Skill index retrieve failed: {}", exc)
                return []

            hits: list[SkillIndexEntry] = []
            for row in rows:
                score = float(row["score"])
                if min_score is not None and score > min_score:
                    continue
                hits.append(
                    SkillIndexEntry(
                        name=row["name"],
                        description=row["description"],
                        path=row["path"],
                        source=row["source"],
                        requirements=json.loads(row["requirements_json"] or "{}"),
                        score=score,
                    )
                )

            # 写入 L1 query 缓存（LRU 淘汰）
            if cache_size > 0:
                self._retrieve_cache[cache_key] = list(hits)
                self._retrieve_cache.move_to_end(cache_key)
                while len(self._retrieve_cache) > cache_size:
                    self._retrieve_cache.popitem(last=False)

            return hits

    def _connect(self) -> sqlite3.Connection:
        """懒连接 SQLite；WAL 模式支持并发读。"""
        if self._conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._init_schema(self._conn)
        return self._conn

    @staticmethod
    def _init_schema(conn: sqlite3.Connection) -> None:
        """初始化 meta / skills / skill_fts 表结构（幂等）。"""
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS skill_index_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS skills (
                rowid INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                path TEXT NOT NULL,
                source TEXT NOT NULL,
                description TEXT NOT NULL,
                body_snippet TEXT NOT NULL DEFAULT '',
                requirements_json TEXT NOT NULL DEFAULT '{}',
                content_hash TEXT NOT NULL,
                mtime_ns INTEGER NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS skill_fts USING fts5(
                name,
                description,
                body_snippet,
                content='skills',
                content_rowid='rowid',
                tokenize='unicode61'
            );
            """
        )

    def _read_meta(self, key: str) -> str | None:
        try:
            conn = self._connect()
            row = conn.execute(
                "SELECT value FROM skill_index_meta WHERE key = ?",
                (key,),
            ).fetchone()
            return None if row is None else str(row["value"])
        except Exception:
            return None

    def _write_meta(self, key: str, value: str) -> None:
        conn = self._connect()
        conn.execute(
            """
            INSERT INTO skill_index_meta(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )

    def _get_generation(self) -> int:
        """读取索引世代；优先用内存值，避免 catalog L1 命中时反复读库。"""
        if self._generation_memory >= 0:
            return self._generation_memory
        raw = self._read_meta(_META_GENERATION)
        if not raw:
            return 0
        try:
            self._generation_memory = int(raw)
        except ValueError:
            self._generation_memory = 0
        return self._generation_memory

    def _catalog_fingerprint(self, loader: SkillsLoader) -> str:
        """计算目录指纹：skill 内容 hash + disabled 列表 + body 索引长度配置。"""
        parts: list[str] = []
        for entry in sorted(loader.list_skills(filter_unavailable=False), key=lambda item: item["name"]):
            path = Path(entry["path"])
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            parts.append(f"{entry['name']}:{digest}")
        parts.append(f"disabled:{','.join(sorted(loader.disabled_skills))}")
        parts.append(f"body_chars:{self._config.index_body_chars}")
        return hashlib.sha256("|".join(parts).encode()).hexdigest()

    def _clear_l1(self) -> None:
        """清空 L1 缓存（rebuild 后调用；不清 generation_memory）。"""
        self._catalog_cache = None
        self._catalog_generation = -1
        self._retrieve_cache.clear()


def _normalize_query(text: str) -> str:
    """预处理检索 query：压空白、转小写。"""
    return " ".join(text.split()).strip().lower()


def _build_fts_query(normalized: str) -> str:
    """将自然语言 query 转为 FTS5 MATCH 表达式（token OR 连接）。

    例：``"set cron reminder"`` → ``"set" OR "cron" OR "reminder"``
    过短 token（<2 字符）过滤后再 fallback 到全部 token（保留中文单字）。
    """
    tokens = _FTS_TOKEN_RE.findall(normalized)
    tokens = [token for token in tokens if len(token) >= 2]
    if not tokens:
        tokens = _FTS_TOKEN_RE.findall(normalized)
    if not tokens:
        return ""
    escaped = [token.replace('"', '""') for token in tokens[:20]]
    return " OR ".join(f'"{part}"' for part in escaped)
