"""Memory system for persistent agent memory."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
                    "daily_note": {
                        "type": "string",
                        "description": "A dated episodic note for archival memory. Start with [YYYY-MM-DD HH:MM] when possible.",
                    },
                    "history_entry": {
                        "type": "string",
                        "description": "Deprecated alias for daily_note. A dated episodic note.",
                    },
                    "memory_update": {
                        "type": "string",
                        "description": "Full updated core long-term memory as markdown. Keep stable facts and preferences here; do not dump daily episodic notes into it.",
                    },
                },
                "required": ["memory_update"],
            },
        },
    }
]


class MemoryStore:
    """OpenClaw-style memory: compact core memory + dated notes + searchable recall."""

    def __init__(self, workspace: Path):
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"
        self.pinned_file = self.memory_dir / "PINNED.md"
        self.index_file = self.memory_dir / ".memory_index.sqlite3"

    @staticmethod
    def _read_file(path: Path) -> str:
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    @staticmethod
    def _coerce_text(value: Any) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _extract_note_day(note: str) -> str:
        if note.startswith("[") and len(note) >= 11:
            candidate = note[1:11]
            try:
                datetime.strptime(candidate, "%Y-%m-%d")
                return candidate
            except ValueError:
                pass
        return datetime.now().strftime("%Y-%m-%d")

    def _daily_note_path(self, day: str) -> Path:
        return self.memory_dir / f"{day}.md"

    def _doc_paths(self) -> list[Path]:
        docs: list[Path] = []
        if self.memory_file.exists():
            docs.append(self.memory_file)
        for path in sorted(self.memory_dir.glob("*.md")):
            if path.name in {self.memory_file.name, self.history_file.name, self.pinned_file.name}:
                continue
            docs.append(path)
        return docs

    def _resolve_memory_path(self, path: str) -> Path:
        target = Path(path).expanduser()
        if not target.is_absolute():
            if target.parts and target.parts[0] == "memory":
                target = self.memory_dir / Path(*target.parts[1:])
            else:
                target = self.memory_dir / target
        resolved = target.resolve()
        try:
            resolved.relative_to(self.memory_dir.resolve())
        except ValueError as exc:
            raise PermissionError(f"Path {path} is outside memory directory") from exc
        return resolved

    def _memory_relpath(self, path: Path) -> str:
        return f"memory/{path.relative_to(self.memory_dir).as_posix()}"

    def _index_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.index_file)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_docs (
                path TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        return conn

    @staticmethod
    def _snippet(content: str, query: str, width: int = 160) -> str:
        lower_content = content.lower()
        lower_query = query.lower()
        idx = lower_content.find(lower_query)
        if idx < 0:
            idx = 0
        start = max(0, idx - 40)
        end = min(len(content), start + width)
        snippet = " ".join(content[start:end].split())
        if start > 0:
            snippet = "..." + snippet
        if end < len(content):
            snippet = snippet + "..."
        return snippet

    def rebuild_index(self) -> None:
        conn = self._index_connection()
        try:
            conn.execute("DELETE FROM memory_docs")
            for path in self._doc_paths():
                conn.execute(
                    "INSERT INTO memory_docs(path, content, updated_at) VALUES (?, ?, ?)",
                    (
                        self._memory_relpath(path),
                        path.read_text(encoding="utf-8"),
                        path.stat().st_mtime,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def read_long_term(self) -> str:
        return self._read_file(self.memory_file)

    def read_pinned(self) -> str:
        return self._read_file(self.pinned_file)

    def write_long_term(self, content: str) -> None:
        self.memory_file.write_text(content, encoding="utf-8")
        self.rebuild_index()

    def write_daily_note(self, day: str, content: str) -> Path:
        path = self._daily_note_path(day)
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
        self.rebuild_index()
        return path

    def append_daily_note(self, note: str) -> Path:
        path = self._daily_note_path(self._extract_note_day(note))
        with open(path, "a", encoding="utf-8") as f:
            f.write(note.rstrip() + "\n\n")
        self.rebuild_index()
        return path

    def append_history(self, entry: str) -> None:
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")

    def search(self, query: str, limit: int = 5) -> list[dict[str, str]]:
        query = query.strip()
        if not query:
            return []
        self.rebuild_index()
        conn = self._index_connection()
        try:
            rows = conn.execute(
                """
                SELECT path, content
                FROM memory_docs
                WHERE lower(content) LIKE lower(?)
                ORDER BY updated_at DESC, path ASC
                LIMIT ?
                """,
                (f"%{query}%", limit),
            ).fetchall()
        finally:
            conn.close()

        return [
            {
                "path": path,
                "title": Path(path).name,
                "snippet": self._snippet(content, query),
            }
            for path, content in rows
        ]

    def get_document(self, path: str) -> str:
        target = self._resolve_memory_path(path)
        if not target.exists():
            raise FileNotFoundError(f"Memory document not found: {path}")
        if not target.is_file():
            raise FileNotFoundError(f"Memory document is not a file: {path}")
        return target.read_text(encoding="utf-8")

    def get_memory_context(self) -> str:
        long_term = self.read_long_term()
        return f"## Long-term Memory\n{long_term}" if long_term else ""

    def get_pinned_context(self) -> str:
        return self.read_pinned().strip()

    async def consolidate(
        self,
        session: Session,
        provider: LLMProvider,
        model: str,
        *,
        archive_all: bool = False,
        memory_window: int = 50,
    ) -> bool:
        """Consolidate old messages into MEMORY.md + dated daily notes via LLM tool call."""
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

## Current Core Memory
{current_memory or "(empty)"}

## Conversation to Process
{chr(10).join(lines)}

Update memory_update with compact durable facts only.
Put episodic progress and dated archival notes into daily_note."""

        try:
            response = await provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a memory consolidation agent. Call save_memory with a compact core memory update and a dated daily note.",
                    },
                    {"role": "user", "content": prompt},
                ],
                tools=_SAVE_MEMORY_TOOL,
                model=model,
            )

            if not response.has_tool_calls:
                logger.warning("Memory consolidation: LLM did not call save_memory, skipping")
                return False

            args = response.tool_calls[0].arguments
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

            note = args.get("daily_note") or args.get("history_entry")
            if note:
                note_text = self._coerce_text(note)
                self.append_daily_note(note_text)
                self.append_history(note_text)

            update = args.get("memory_update")
            if update is not None:
                update_text = self._coerce_text(update)
                if update_text != current_memory:
                    self.write_long_term(update_text)

            session.last_consolidated = 0 if archive_all else len(session.messages) - keep_count
            logger.info(
                "Memory consolidation done: {} messages, last_consolidated={}",
                len(session.messages),
                session.last_consolidated,
            )
            return True
        except Exception:
            logger.exception("Memory consolidation failed")
            return False
