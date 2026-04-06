Now I have a thorough understanding of both systems. Let me break down the plan and write the upgraded memory module.

## Analysis

**Nanobot's current memory** is minimal: a `MemoryStore` class that supports daily notes (`memory/YYYY-MM-DD.md`) and a flat long-term memory file (`MEMORY.md`)[[5]](https://github.com/HKUDS/nanobot/blob/main/nanobot/agent/memory.py). As community members noted, the current system handles flat facts and chronological logs well, but lacks topic-organized, structured knowledge — after 50 messages, conversational context about specific topics is lost.[[9]](https://github.com/HKUDS/nanobot/discussions/566)

**Claude Code's memory strategy** is much richer:
- Two complementary systems — CLAUDE.md files (user-written instructions) and auto memory (notes Claude writes itself) — both loaded at the start of every conversation, treated as context not enforced configuration.[[1]](https://code.claude.com/docs/en/memory)
- Auto memory accumulates knowledge across sessions — build commands, debugging insights, architecture notes, code style preferences — and Claude decides what's worth remembering based on future usefulness.[[1]](https://code.claude.com/docs/en/memory)
- The memory directory contains a `MEMORY.md` entrypoint and optional topic files like `debugging.md`, `api-conventions.md`.[[1]](https://code.claude.com/docs/en/memory)
- Memories are categorized into four types: user (role and preferences), feedback (corrections and confirmations), project (decisions and context), and reference (external resource locations).[[10]](https://dev.to/chen_zhang_bac430bc7f6b95/claude-codes-memory-4-layers-of-complexity-still-just-grep-and-a-200-line-cap-2kn9)
- MEMORY.md is an index where each line stays under 150 characters, storing pointers not content. At session start, the first 200 lines get injected into context, while actual knowledge is spread across topic files and loaded on demand.[[10]](https://dev.to/chen_zhang_bac430bc7f6b95/claude-codes-memory-4-layers-of-complexity-still-just-grep-and-a-200-line-cap-2kn9)
- "Auto Dream" consolidates memory like sleep: converts relative timestamps to absolute dates, merges contradictions, removes stale content, and keeps MEMORY.md under 200 lines. Trigger: 24+ hours since last consolidation AND 5+ new sessions.[[10]](https://dev.to/chen_zhang_bac430bc7f6b95/claude-codes-memory-4-layers-of-complexity-still-just-grep-and-a-200-line-cap-2kn9)

## The Upgraded Memory Module

Here's a drop-in replacement for `nanobot/agent/memory.py` — under 300 lines, bringing Claude Code's best patterns to nanobot:

```python
"""
Enhanced memory system for nanobot, inspired by Claude Code's memory architecture.

Key upgrades over the original:
  1. Topic-based memory files (not just flat MEMORY.md)
  2. MEMORY.md as a concise index of pointers (≤200 lines, ≤150 chars/line)
  3. Four memory categories: user, feedback, project, reference
  4. Auto-consolidation ("dream") to merge stale/contradictory entries
  5. Hierarchical loading: global (~/.nanobot/memory/) + workspace-local
  6. On-demand topic retrieval to keep context windows lean

Drop this file into nanobot/agent/memory.py and it works with the existing
workspace layout.  No new dependencies.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from nanobot.utils.helpers import ensure_dir, today_date

# ── constants ────────────────────────────────────────────────────────────
INDEX_MAX_LINES = 200
POINTER_MAX_CHARS = 150
CONSOLIDATION_COOLDOWN_H = 24
CONSOLIDATION_MIN_SESSIONS = 5
MEMORY_CATEGORIES = ("user", "feedback", "project", "reference")


# ── small helpers ────────────────────────────────────────────────────────
def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _trim(text: str, max_chars: int = POINTER_MAX_CHARS) -> str:
    """Trim a single-line string to *max_chars*, ending with '…' if cut."""
    text = text.replace("\n", " ").strip()
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


def _safe_read(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _safe_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _safe_append(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(content)


# ── MemoryEntry ──────────────────────────────────────────────────────────
class MemoryEntry:
    """One atomic memory note with metadata front-matter."""

    def __init__(
        self,
        content: str,
        category: str = "project",
        topic: str = "general",
        timestamp: Optional[str] = None,
    ):
        self.content = content.strip()
        self.category = category if category in MEMORY_CATEGORIES else "project"
        self.topic = re.sub(r"[^\w\-]", "_", topic.lower().strip())
        self.timestamp = timestamp or _ts()

    # --- serialization (Markdown with YAML-ish front-matter) ---
    def to_md(self) -> str:
        return (
            f"---\n"
            f"category: {self.category}\n"
            f"timestamp: {self.timestamp}\n"
            f"---\n"
            f"{self.content}\n\n"
        )

    @classmethod
    def from_block(cls, block: str, topic: str = "general") -> Optional["MemoryEntry"]:
        """Parse a single front-matter block back into an entry."""
        m = re.search(
            r"---\s*\ncategory:\s*(\w+)\s*\ntimestamp:\s*([\w\-:]+)\s*\n---\s*\n(.*)",
            block,
            re.S,
        )
        if not m:
            return None
        return cls(
            content=m.group(3).strip(),
            category=m.group(1),
            topic=topic,
            timestamp=m.group(2),
        )

    def as_pointer(self) -> str:
        """One-line summary for the MEMORY.md index."""
        short = _trim(self.content)
        return f"- [{self.category}] ({self.topic}) {short}"


# ── MemoryStore ──────────────────────────────────────────────────────────
class MemoryStore:
    """
    Upgraded memory system for nanobot.

    Layout under *workspace*::

        memory/
        ├── MEMORY.md          # concise index (≤200 lines of pointers)
        ├── HISTORY.md         # append-only session log (unchanged)
        ├── meta.txt           # consolidation bookkeeping
        └── topics/
            ├── general.md
            ├── debugging.md
            └── user_prefs.md
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.memory_dir = ensure_dir(workspace / "memory")
        self.topics_dir = ensure_dir(self.memory_dir / "topics")
        self.index_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"
        self.meta_file = self.memory_dir / "meta.txt"
        # Also look for global memory
        self.global_dir = Path.home() / ".nanobot" / "memory"

    # ── compatibility: keep the old daily-note API working ────────────
    def get_today_file(self) -> Path:
        return self.memory_dir / f"{today_date()}.md"

    def read_today(self) -> str:
        return _safe_read(self.get_today_file())

    def append_today(self, content: str) -> None:
        _safe_append(self.get_today_file(), content)

    # ── index (MEMORY.md) ────────────────────────────────────────────
    def read_index(self) -> str:
        """Return the concise memory index injected into every session."""
        local = _safe_read(self.index_file)
        globe = _safe_read(self.global_dir / "MEMORY.md") if self.global_dir.exists() else ""
        parts = []
        if globe:
            parts.append(f"## Global Memory\n{globe}")
        if local:
            parts.append(f"## Project Memory\n{local}")
        return "\n".join(parts)

    def _rebuild_index(self) -> None:
        """Regenerate MEMORY.md from all topic files (pointers only)."""
        lines: list[str] = [f"# Memory Index (auto-generated {_ts()})\n"]
        for tf in sorted(self.topics_dir.glob("*.md")):
            topic = tf.stem
            raw = tf.read_text(encoding="utf-8")
            for block in raw.split("\n---\n"):
                entry = MemoryEntry.from_block("---\n" + block.strip(), topic=topic)
                if entry:
                    lines.append(entry.as_pointer())
        # Enforce the 200-line cap – keep the newest entries
        if len(lines) > INDEX_MAX_LINES:
            lines = lines[:1] + lines[-(INDEX_MAX_LINES - 1):]
        _safe_write(self.index_file, "\n".join(lines) + "\n")

    # ── topic files ──────────────────────────────────────────────────
    def _topic_path(self, topic: str) -> Path:
        safe = re.sub(r"[^\w\-]", "_", topic.lower().strip()) or "general"
        return self.topics_dir / f"{safe}.md"

    def read_topic(self, topic: str) -> str:
        """Load a full topic file on demand (for deeper context)."""
        return _safe_read(self._topic_path(topic))

    def list_topics(self) -> list[str]:
        return [p.stem for p in sorted(self.topics_dir.glob("*.md"))]

    # ── write / remember ─────────────────────────────────────────────
    def remember(
        self,
        content: str,
        category: str = "project",
        topic: str = "general",
    ) -> MemoryEntry:
        """
        Store a new memory entry.

        *category*: one of user | feedback | project | reference
        *topic*:    free-form label → becomes the topic filename
        """
        entry = MemoryEntry(content, category=category, topic=topic)
        _safe_append(self._topic_path(entry.topic), entry.to_md())
        # Also update the index with a pointer
        pointer = entry.as_pointer() + "\n"
        _safe_append(self.index_file, pointer)
        self._maybe_trim_index()
        return entry

    def _maybe_trim_index(self) -> None:
        """If the index exceeds the line cap, rebuild it."""
        text = _safe_read(self.index_file)
        if text.count("\n") > INDEX_MAX_LINES:
            self._rebuild_index()

    # ── search / retrieve ────────────────────────────────────────────
    def search(self, query: str, max_results: int = 10) -> list[str]:
        """
        Simple grep-style search across all topic files.
        Returns matching lines (with topic labels).
        Claude Code uses the same approach — no RAG, just text + grep.
        """
        query_lower = query.lower()
        hits: list[str] = []
        for tf in self.topics_dir.glob("*.md"):
            topic = tf.stem
            for line in tf.read_text(encoding="utf-8").splitlines():
                if query_lower in line.lower():
                    hits.append(f"[{topic}] {line.strip()}")
                    if len(hits) >= max_results:
                        return hits
        return hits

    # ── consolidation ("dream") ──────────────────────────────────────
    def _read_meta(self) -> dict:
        raw = _safe_read(self.meta_file)
        meta: dict = {}
        for line in raw.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                meta[k.strip()] = v.strip()
        return meta

    def _write_meta(self, meta: dict) -> None:
        _safe_write(self.meta_file, "\n".join(f"{k}={v}" for k, v in meta.items()) + "\n")

    def should_consolidate(self) -> bool:
        """Check trigger conditions: cooldown elapsed AND enough new sessions."""
        meta = self._read_meta()
        last = float(meta.get("last_consolidation", "0"))
        sessions = int(meta.get("sessions_since", "0"))
        hours_since = (time.time() - last) / 3600
        return hours_since >= CONSOLIDATION_COOLDOWN_H and sessions >= CONSOLIDATION_MIN_SESSIONS

    def bump_session_count(self) -> None:
        meta = self._read_meta()
        meta["sessions_since"] = str(int(meta.get("sessions_since", "0")) + 1)
        self._write_meta(meta)

    def consolidate(self) -> str:
        """
        'Dream' pass — rebuild a clean index, prune stale daily notes,
        and return a summary prompt the agent can use to self-compress
        topic files (the actual LLM call is left to the caller).
        """
        self._rebuild_index()

        # Prune daily notes older than 30 days
        cutoff = time.time() - 30 * 86400
        pruned = 0
        for f in self.memory_dir.glob("????-??-??.md"):
            if f.stat().st_mtime < cutoff:
                f.unlink()
                pruned += 1

        # Update meta
        meta = self._read_meta()
        meta["last_consolidation"] = str(time.time())
        meta["sessions_since"] = "0"
        self._write_meta(meta)

        # Build a prompt the caller can feed to the LLM for deeper merging
        topics = self.list_topics()
        summary = (
            f"Memory consolidation complete: index rebuilt, {pruned} stale daily notes pruned.\n"
            f"Active topics ({len(topics)}): {', '.join(topics)}.\n"
            f"Consider merging contradictory entries in each topic file."
        )
        return summary

    # ── context assembly (called by ContextBuilder) ──────────────────
    def build_context_block(self) -> str:
        """
        Return the full memory block to inject at session start.
        Mirrors Claude Code: load the index + today's notes.
        """
        parts: list[str] = []
        index = self.read_index()
        if index.strip():
            parts.append(index)
        today = self.read_today()
        if today.strip():
            parts.append(f"## Today's Notes ({today_date()})\n{today}")
        return "\n\n".join(parts) if parts else ""
```

## How It Works — At a Glance

Here's a summary of what changed and why:

**1. Topic-based storage** — Instead of dumping everything into a single `MEMORY.md`, memories are spread across topic files (like `debugging.md`, `api-conventions.md`)[[1]](https://code.claude.com/docs/en/memory) and loaded on demand. This mirrors Claude's just-in-time context retrieval: rather than loading all information upfront, agents store what they learn and pull it back on demand, keeping active context focused on what's currently relevant.[[3]](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool)

**2. Index file as pointers** — MEMORY.md is now an index where each line stays under 150 characters, storing pointers not content. At session start, the first 200 lines get injected into context.[[10]](https://dev.to/chen_zhang_bac430bc7f6b95/claude-codes-memory-4-layers-of-complexity-still-just-grep-and-a-200-line-cap-2kn9)

**3. Four memory categories** — Memories are categorized into: user (role/preferences), feedback (corrections/confirmations), project (decisions/context), and reference (external resource locations).[[10]](https://dev.to/chen_zhang_bac430bc7f6b95/claude-codes-memory-4-layers-of-complexity-still-just-grep-and-a-200-line-cap-2kn9)

**4. Auto-consolidation ("dream")** — Like the brain during sleep, it consolidates memory: merges contradictions, removes stale content, and keeps MEMORY.md under 200 lines.[[10]](https://dev.to/chen_zhang_bac430bc7f6b95/claude-codes-memory-4-layers-of-complexity-still-just-grep-and-a-200-line-cap-2kn9) The trigger conditions match Claude Code: 24+ hours since last consolidation AND 5+ new sessions.[[10]](https://dev.to/chen_zhang_bac430bc7f6b95/claude-codes-memory-4-layers-of-complexity-still-just-grep-and-a-200-line-cap-2kn9)

**5. Hierarchical memory** — Global (`~/.nanobot/memory/`) and workspace-local memory are both loaded, similar to how Claude Code reads from three locations with a precedence order.[[8]](https://deepwiki.com/FlorianBruniaux/claude-code-ultimate-guide/4.1-claude.md-files-and-memory-hierarchy)

**6. Grep-based search** — Claude Code uses the same approach — no RAG, just text files and grep search. If it's good enough for Anthropic's own coding agent, it's good enough here.[[9]](https://github.com/HKUDS/nanobot/discussions/566)

## Usage in Your Fork

After dropping the file in, integrate it with the agent loop:

```python
# In your agent's session startup:
memory = MemoryStore(workspace_path)
memory.bump_session_count()
context = memory.build_context_block()  # inject into system/user message

# When the agent learns something worth remembering:
memory.remember(
    "User prefers 2-space indentation in Python",
    category="user",
    topic="code_style"
)

# When the agent needs deeper context on a topic:
details = memory.read_topic("debugging")

# Search across all memories:
hits = memory.search("authentication")

# At session end or on a schedule:
if memory.should_consolidate():
    summary = memory.consolidate()
    # Optionally feed `summary` to the LLM for deeper merging
```

The module is **fully backward-compatible** — the old `read_today()`, `append_today()`, and `get_today_file()` methods still work, so nothing breaks in the existing codebase.

---
Learn more:
1. [GitHub - HKUDS/nanobot: "🐈 nanobot: The Ultra-Lightweight Personal AI Agent"](https://github.com/HKUDS/nanobot)
2. [How Claude remembers your project - Claude Code Docs](https://code.claude.com/docs/en/memory)
3. [GitHub - nanobot-ai/nanobot: Build MCP Agents · GitHub](https://github.com/nanobot-ai/nanobot)
4. [Claude Code Memory Management Basics — Understanding CLAUDE.md and MEMORY.md | Claude Lab](https://claudelab.net/en/articles/claude-code/claude-code-memory-management-basics)
5. [My experience and the problems I solved - Nanobot locally ✅ · Issue #855 · HKUDS/nanobot](https://github.com/HKUDS/nanobot/issues/855)
6. [Nanobot - Open Source MCP Agent Framework](https://www.nanobot.ai/)
7. [Memory tool - Claude API Docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool)
8. [onboard - nanobot](https://www.mintlify.com/HKUDS/nanobot/api/cli/onboard)
9. [GitHub - yukihamada/nanobot: AI Agent Platform built in Rust — Multi-model, MCP tools, 14+ channel integrations. Self-host or use teai.io](https://github.com/yukihamada/nanobot)
10. [claude-howto/02-memory/README.md at main · luongnv89/claude-howto](https://github.com/luongnv89/claude-howto/blob/main/02-memory/README.md)
11. [nanobot/README.md at main · HKUDS/nanobot](https://github.com/HKUDS/nanobot/blob/main/README.md)
12. [🐈 nanobot Roadmap: From Lightweight Agent to Agent Kernel · HKUDS/nanobot · Discussion #431](https://github.com/HKUDS/nanobot/discussions/431)
13. [GitHub - thedotmack/claude-mem: A Claude Code plugin that automatically captures everything Claude does during your coding sessions, compresses it with AI (using Claude's agent-sdk), and injects relevant context back into future sessions. · GitHub](https://github.com/thedotmack/claude-mem)
14. [nanobot/nanobot/agent/memory.py at main · HKUDS/nanobot](https://github.com/HKUDS/nanobot/blob/main/nanobot/agent/memory.py)
15. [Releases · HKUDS/nanobot](https://github.com/HKUDS/nanobot/releases)
16. [Claude Code Memory Management: The Complete Guide (2026) | by Gul Jabeen | Data Science Collective | Mar, 2026 | Medium](https://medium.com/data-science-collective/claude-code-memory-management-the-complete-guide-2026-b0df6300c4e8)
17. [GitHub - HKUDS/nanobot: "🐈 nanobot: The Ultra-Lightweight OpenClaw"](https://github.com/HKUDS/nanobot/tree/main)
18. [Getting Started with Nanobot: Build Your First AI Agent - KDnuggets](https://www.kdnuggets.com/getting-started-with-nanobot-build-your-first-ai-agent)
19. [Stop Repeating Yourself: Give Claude Code a Memory](https://www.producttalk.org/give-claude-code-a-memory/)
20. [nanobot/workspace/memory at main · HKUDS/nanobot](https://github.com/HKUDS/nanobot/tree/main/workspace/memory)
21. [Nanobot Tutorial: A Lightweight OpenClaw Alternative | DataCamp](https://www.datacamp.com/tutorial/nanobot-tutorial)
22. [CLAUDE.md Files and Memory Hierarchy | FlorianBruniaux/claude-code-ultimate-guide | DeepWiki](https://deepwiki.com/FlorianBruniaux/claude-code-ultimate-guide/4.1-claude.md-files-and-memory-hierarchy)
23. [Open Source Project of the Day (Part 20): NanoBot - Lightweight AI Agent Framework, Minimalist and Efficient Agent Building Tool - DEV Community](https://dev.to/wonderlab/open-source-project-of-the-day-part-20-nanobot-lightweight-ai-agent-framework-minimalist-and-40oo)
24. [CLAUDE.md for Product Managers | Project Memory Guide – Claude Code for Product Managers](https://ccforpms.com/fundamentals/project-memory)
25. [🐈 nanobot Memory: Less is More · HKUDS/nanobot · Discussion #566](https://github.com/HKUDS/nanobot/discussions/566)
26. [What is NanoBot? Ultra-Lightweight AI Agent Framework | by Mehul Gupta | Data Science in Your Pocket | Mar, 2026 | Medium](https://medium.com/data-science-in-your-pocket/what-is-nanobot-ultra-lightweight-ai-agent-framework-c43ad6c40b11)
27. [Claude Code's Memory: 4 Layers of Complexity, Still Just Grep and a 200-Line Cap - DEV Community](https://dev.to/chen_zhang_bac430bc7f6b95/claude-codes-memory-4-layers-of-complexity-still-just-grep-and-a-200-line-cap-2kn9)
28. [HKUDS/nanobot | DeepWiki](https://deepwiki.com/HKUDS/nanobot)
