"""Memory system for persistent agent memory."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from nanobot.utils.helpers import ensure_dir

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import Session


_SAVE_MEMORY_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "Save the memory consolidation result to persistent storage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "history_entry": {
                        "type": "string",
                        "description": "One or two concise sentences summarizing key outcomes only. "
                        "Start with [YYYY-MM-DD HH:MM]. Omit tool names, internal steps, and verbose logs; keep only facts useful for grep.",
                    },
                    "memory_update": {
                        "type": "string",
                        "description": "Full updated long-term memory as markdown. Include all existing "
                        "facts plus new ones. Return unchanged if nothing new.",
                    },
                },
                "required": ["history_entry", "memory_update"],
            },
        },
    }
]


class MemoryStore:
    """Two-layer memory: MEMORY.md (long-term facts) + HISTORY.md (grep-searchable log)."""

    def __init__(self, workspace: Path, history_max_chars: int = 0):
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"
        self.history_max_chars = history_max_chars  # 0 = no limit

    def read_long_term(self) -> str:
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        self.memory_file.write_text(content, encoding="utf-8")

    def append_history(self, entry: str) -> None:
        self._ensure_history_db()
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")
        self._insert_history_entry(entry.strip())

    def _history_db_path(self) -> Path:
        return self.memory_dir / "history.db"

    def _ensure_history_db(self) -> None:
        path = self._history_db_path()
        if path.exists():
            return
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE history_entries (id INTEGER PRIMARY KEY, content TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE VIRTUAL TABLE history_fts USING fts5(content, content='history_entries', content_rowid='id')"
        )
        conn.execute(
            "CREATE TRIGGER history_entries_ai AFTER INSERT ON history_entries BEGIN "
            "INSERT INTO history_fts(rowid, content) VALUES (new.id, new.content); END"
        )
        conn.commit()
        conn.close()
        self._backfill_history_from_file()

    def _backfill_history_from_file(self) -> None:
        if not self.history_file.exists():
            return
        text = self.history_file.read_text(encoding="utf-8")
        entries = [e.strip() for e in text.split("\n\n") if e.strip()]
        if not entries:
            return
        conn = sqlite3.connect(self._history_db_path())
        cur = conn.execute("SELECT COUNT(*) FROM history_entries")
        if cur.fetchone()[0] > 0:
            conn.close()
            return
        for entry in entries:
            conn.execute(
                "INSERT INTO history_entries (content, created_at) VALUES (?, ?)",
                (entry, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())),
            )
        conn.commit()
        conn.close()
        logger.debug("Backfilled {} history entries into DB", len(entries))

    def _insert_history_entry(self, content: str) -> None:
        self._ensure_history_db()
        conn = sqlite3.connect(self._history_db_path())
        conn.execute(
            "INSERT INTO history_entries (content, created_at) VALUES (?, ?)",
            (content, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())),
        )
        conn.commit()
        conn.close()

    def get_relevant_history(self, query: str, top_k: int = 5) -> str:
        """Retrieve history entries relevant to the query via SQLite FTS5. No history loss; full log stays in HISTORY.md."""
        self._ensure_history_db()
        conn = sqlite3.connect(self._history_db_path())
        query = (query or "").strip()
        if not query:
            rows = conn.execute(
                "SELECT content FROM history_entries ORDER BY id DESC LIMIT ?", (top_k,)
            ).fetchall()
        else:
            terms = query.replace('"', ' ').split()
            fts_query = " OR ".join(f'"{t}"' for t in terms if t)
            if not fts_query:
                rows = conn.execute(
                    "SELECT content FROM history_entries ORDER BY id DESC LIMIT ?", (top_k,)
                ).fetchall()
            else:
                try:
                    rows = conn.execute(
                        "SELECT content FROM history_fts WHERE history_fts MATCH ? ORDER BY rank LIMIT ?",
                        (fts_query, top_k),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = conn.execute(
                        "SELECT content FROM history_entries ORDER BY id DESC LIMIT ?", (top_k,)
                    ).fetchall()
        conn.close()
        if not rows:
            return ""
        return "\n\n".join(r[0] for r in rows)

    def get_memory_context(self) -> str:
        long_term = self.read_long_term()
        return f"## Long-term Memory\n{long_term}" if long_term else ""

    async def consolidate(
        self,
        session: Session,
        provider: LLMProvider,
        model: str,
        *,
        archive_all: bool = False,
        memory_window: int = 50,
    ) -> bool:
        """Consolidate old messages into MEMORY.md + HISTORY.md via LLM tool call.

        Returns True on success (including no-op), False on failure.
        """
        if archive_all:
            old_messages = session.messages
            keep_count = 0
            logger.info("Memory consolidation (archive_all): {} messages", len(session.messages))
        else:
            keep_count = memory_window // 2
            if len(session.messages) <= keep_count:
                return True
            if len(session.messages) - session.last_consolidated <= 0:
                return True
            old_messages = session.messages[session.last_consolidated:-keep_count]
            if not old_messages:
                return True
            logger.info("Memory consolidation: {} to consolidate, {} keep", len(old_messages), keep_count)

        lines = []
        for m in old_messages:
            if not m.get("content"):
                continue
            tools = f" [tools: {', '.join(m['tools_used'])}]" if m.get("tools_used") else ""
            lines.append(f"[{m.get('timestamp', '?')[:16]}] {m['role'].upper()}{tools}: {m['content']}")

        current_memory = self.read_long_term()
        prompt = f"""Process this conversation and call the save_memory tool with your consolidation.

## Current Long-term Memory
{current_memory or "(empty)"}

## Conversation to Process
{chr(10).join(lines)}"""

        try:
            response = await provider.chat(
                messages=[
                    {"role": "system", "content": "You are a memory consolidation agent. Call the save_memory tool. Keep history_entry short (1-2 sentences, key facts only). Do not list every tool or minor detail."},
                    {"role": "user", "content": prompt},
                ],
                tools=_SAVE_MEMORY_TOOL,
                model=model,
            )

            if not response.has_tool_calls:
                logger.warning("Memory consolidation: LLM did not call save_memory, skipping")
                return False

            args = response.tool_calls[0].arguments
            # Some providers return arguments as a JSON string instead of dict
            if isinstance(args, str):
                args = json.loads(args)
            # Some providers return arguments as a list (handle edge case)
            if isinstance(args, list):
                if args and isinstance(args[0], dict):
                    args = args[0]
                else:
                    logger.warning("Memory consolidation: unexpected arguments as empty or non-dict list")
                    return False
            if not isinstance(args, dict):
                logger.warning("Memory consolidation: unexpected arguments type {}", type(args).__name__)
                return False

            if entry := args.get("history_entry"):
                if not isinstance(entry, str):
                    entry = json.dumps(entry, ensure_ascii=False)
                self.append_history(entry)
            if update := args.get("memory_update"):
                if not isinstance(update, str):
                    update = json.dumps(update, ensure_ascii=False)
                if update != current_memory:
                    self.write_long_term(update)

            session.last_consolidated = 0 if archive_all else len(session.messages) - keep_count
            logger.info("Memory consolidation done: {} messages, last_consolidated={}", len(session.messages), session.last_consolidated)
            return True
        except Exception:
            logger.exception("Memory consolidation failed")
            return False
