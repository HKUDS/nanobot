"""Memory system for persistent agent memory."""

from __future__ import annotations

import json
import math
from datetime import datetime
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
                        "description": "A paragraph (2-5 sentences) summarizing key events/decisions/topics. "
                        "Start with [YYYY-MM-DD HH:MM]. Include detail useful for grep search.",
                    },
                    "memory_update": {
                        "type": "string",
                        "description": "Semantic memory — full updated MEMORY.md as markdown. ONLY stable, timeless facts: preferences, relationships, projects, skills."
                        "NEVER include events, current activities, or anything time-bound. Return current memory unchanged if nothing new."
                    },
                    "episodic_memory_update": {
                        "type": "array",
                        "description": "Episodic memory — time-bound events, experiences, and context only.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "importance": {
                                    "type": "string",
                                    "enum": ["high", "medium", "low"],
                                    "description": "Retrieval importance: high=critical to remember, medium=useful, low=nice to have.",
                                },
                            },
                            "required": ["text", "importance"],
                        },
                    },
                },
                "required": ["history_entry", "memory_update"],
            },
        },
    }
]

_DECAY_LAMBDA = {"high": 0.001, "medium": 0.01, "low": 0.1}
_IMPORTANCE_WEIGHT = {"high": 1.0, "medium": 0.6, "low": 0.3}


class MemoryStore:
    """Three-layer memory: MEMORY.md (long-term semantic facts) + memory.jsonl(long-term episodic facts) + HISTORY.md (grep-searchable log)."""

    def __init__(self, workspace: Path):
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"
        self.episodic_file = self.memory_dir / "memory.jsonl"
        self._facts: list[dict] = []
        self._bm25 = None
        self._mtime: float = 0.0
        self._sync()

    def _sync(self) -> None:
        if not self.episodic_file.exists() or (mtime := self.episodic_file.stat().st_mtime) == self._mtime:
            return
        self._facts = []
        for line in self.episodic_file.read_text(encoding="utf-8").splitlines():
            try:
                self._facts.append(json.loads(line.strip()))
            except (json.JSONDecodeError, ValueError):
                pass
        try:
            from rank_bm25 import BM25Okapi
            self._bm25 = BM25Okapi([m["text"].lower().split() for m in self._facts]) if self._facts else None
        except ImportError:
            self._bm25 = None
        self._mtime = mtime

    def _decay_score(self, fact: dict) -> float:
        imp = fact.get("importance", "medium")
        try: age = (datetime.now() - datetime.fromisoformat(fact["created_at"])).days
        except (KeyError, ValueError): age = 0
        return _IMPORTANCE_WEIGHT.get(imp, 0.6) * math.exp(-_DECAY_LAMBDA.get(imp, 0.01) * age)

    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        self._sync()
        if not self._facts:
            return []
        if self._bm25 is not None:
            bm25 = self._bm25.get_scores(query.lower().split())
            scored = sorted(((bm25[i] * self._decay_score(m), i) for i, m in enumerate(self._facts) if bm25[i] > 0), reverse=True)
        else:
            scored = sorted(((self._decay_score(m), i) for i, m in enumerate(self._facts)), reverse=True)
        return [self._facts[i] for _, i in scored[:top_k]]

    def read_long_term(self) -> str:
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        self.memory_file.write_text(content, encoding="utf-8")

    def append_history(self, entry: str) -> None:
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")

    def get_memory_context(self, query: str = "") -> str:
        parts = []
        if lt := self.read_long_term():
            parts.append(f"## Semantic Memory\n{lt}")
        if query and (relevant := self.retrieve(query, top_k=5)):
            parts.append("## Episodic Memory\n" + "\n".join(f"- [{m['importance']}] {m['text']}" for m in relevant))
        return "\n\n".join(parts) if parts else ""

    async def consolidate(
        self,
        session: Session,
        provider: LLMProvider,
        model: str,
        *,
        archive_all: bool = False,
        memory_window: int = 50,
    ) -> bool:
        """Consolidate old messages into MEMORY.md(semantic) + memory.jsonl(episodic) + HISTORY.md via LLM tool call.
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
                    {"role": "system", "content": "You are a memory consolidation agent. Call the save_memory tool. "
                     "memory_update: ONLY timeless semantic facts (preferences, relationships, projects, skills) — never events or activities. "
                     "episodic_memory_update: ONLY episodic entries (events, activities, context) — never stable facts. "
                     "importance: high=must remember, medium=useful, low=nice to have."},
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
            if (facts_list := args.get("episodic_memory_update")) and isinstance(facts_list, list):
                self._sync()
                existing = {m["text"].lower() for m in self._facts}
                memory_lower = (update or "").lower()
                now = datetime.now().isoformat()
                entries = [json.dumps({"text": t, "importance": m.get("importance", "medium"), "created_at": now}, ensure_ascii=False)
                           for m in facts_list if (t := m.get("text", "").strip()) and t.lower() not in existing
                           and t.lower() not in memory_lower]
                if entries:
                    with open(self.episodic_file, "a", encoding="utf-8") as fh:
                        fh.write("\n".join(entries) + "\n")
                logger.info("Memory consolidation: appended {} facts", len(entries))

            session.last_consolidated = 0 if archive_all else len(session.messages) - keep_count
            logger.info("Memory consolidation done: {} messages, last_consolidated={}", len(session.messages), session.last_consolidated)
            return True
        except Exception:
            logger.exception("Memory consolidation failed")
            return False
