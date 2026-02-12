"""Memory tool for nanobot, using Smriti as the underlying memory store."""

from __future__ import annotations
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.smriti_lite import MemoryStore

class MemoryTool(Tool):
    def __init__(self, memory: MemoryStore):
        self.m = memory

    @property
    def name(self) -> str:
        return "memory"

    @property
    def description(self) -> str:
        return "Durable memory: remember/recall/forget/restore/promote/list/trash/vocab/suggest_tags."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": [
                    "remember", "recall", "forget", "restore", "promote", "list", "trash", "vocab", "suggest_tags"
                ]},
                "text": {"type": "string"},
                "mid": {"type": "string"},
                "kind": {"type": "string", "enum": ["fact", "pref", "decision", "todo", "note"]},
                "scope": {"type": "string", "enum": ["daily", "long"]},
                "limit": {"type": "integer", "default": 8},
                "include_trash": {"type": "boolean", "default": False},
                "remove": {"type": "boolean", "default": True},
                "rows": {"type": "integer", "default": 5000},
                "max_tags": {"type": "integer", "default": 2},
                "min_count": {"type": "integer", "default": 2},
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str,
        text: str = "",
        mid: str | None = None,
        kind: str | None = None,
        scope: str | None = None,
        limit: int = 8,
        include_trash: bool = False,
        remove: bool = True,
        rows: int = 5000,
        max_tags: int = 2,
        min_count: int = 2,
        **kwargs,
    ) -> str:
        a = (action or "").strip()

        if a == "remember":
            t = (text or "").strip()
            if not t:
                return "Missing text."
            mid2 = self.m.remember(t, kind=kind, scope=(scope or "daily"))
            return f"✅ remembered ^{mid2}"

        if a == "recall":
            hits = self.m.recall((text or "").strip(), limit=int(limit), include_trash=bool(include_trash))
            if not hits:
                return "No hits."
            return "\n".join([f"- ({h.day} {h.time}) ^{h.id} ({h.kind}/{h.scope}) {h.snippet}" for h in hits])

        if a == "forget":
            if not mid:
                return "Missing mid."
            return self.m.soft_forget(mid)

        if a == "restore":
            if not mid:
                return "Missing mid."
            return self.m.restore(mid)

        if a == "promote":
            if not mid:
                return "Missing mid."
            return self.m.promote(mid, remove=bool(remove))

        if a == "list":
            return self.m.list_recent(limit=int(limit))

        if a == "trash":
            return self.m.list_trash(limit=int(limit))

        if a == "vocab":
            v = self.m.vocab(rows=int(rows), include_trash=bool(include_trash))
            tags = v.get("tags", [])[:20]
            ppl = v.get("people", [])[:20]
            return (
                "tags:\n" + "\n".join([f"- {t}: {c}" for t, c in tags]) +
                "\n\npeople:\n" + "\n".join([f"- {p}: {c}" for p, c in ppl])
            )

        if a == "suggest_tags":
            t = (text or "").strip()
            if not t:
                return "Missing text."
            sug = self.m.suggest_tags(t, max_tags=int(max_tags), min_count=int(min_count), rows=int(rows))
            return "suggested: " + (", ".join([f"#{x}" for x in sug]) if sug else "(none)")

        return f"Invalid action: {a}"
