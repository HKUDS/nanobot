"""Memory tools: memory_search, memory_get, memory_write.

Provides Tool subclasses for agent memory operations, following nanobot's
Tool ABC pattern. These tools allow the agent to search, read, and write
to its memory files.

Reference: OpenClaw src/agents/tools/memory-tool.ts
           createMemorySearchTool() + createMemoryGetTool()
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

try:
    from nanobot.agent.tools.base import Tool
except ImportError:
    # Fallback: define a minimal Tool ABC if full agent package is not available
    from abc import ABC, abstractmethod

    class Tool(ABC):
        @property
        @abstractmethod
        def name(self) -> str: ...
        @property
        @abstractmethod
        def description(self) -> str: ...
        @property
        @abstractmethod
        def parameters(self) -> dict[str, Any]: ...
        @abstractmethod
        async def execute(self, **kwargs: Any) -> str: ...
        def to_schema(self) -> dict[str, Any]:
            return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}
        def validate_params(self, params: dict[str, Any]) -> list[str]:
            schema = self.parameters or {}
            errors = []
            for k in schema.get("required", []):
                if k not in params:
                    errors.append(f"missing required {k}")
            return errors
from nanobot.soul.search import MemorySearchIndex, SEARCH_MAX_RESULTS, SEARCH_MIN_SCORE


class MemoryManager:
    """Manages memory read/write operations for an agent workspace.

    Handles daily memory logs and long-term MEMORY.md, providing safe
    file access within the workspace boundary.

    Reference: OpenClaw src/memory/manager.ts
    """

    def __init__(self, workspace_dir: Path):
        self.workspace_dir = workspace_dir
        self.memory_dir = workspace_dir / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self._search_index = MemorySearchIndex(workspace_dir)

    def write_daily(self, content: str, category: str = "general") -> str:
        """Append timestamped entry to today's memory/YYYY-MM-DD.md."""
        today = date.today().isoformat()
        path = self.memory_dir / f"{today}.md"
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"\n## [{ts}] {category}\n\n{content}\n"

        if not path.exists():
            path.write_text(f"# Memory Log: {today}\n", encoding="utf-8")
        with open(path, "a", encoding="utf-8") as f:
            f.write(entry)
        return f"memory/{today}.md"

    def read_file(
        self,
        rel_path: str,
        from_line: int | None = None,
        n_lines: int | None = None,
    ) -> dict:
        """Safely read a memory file within workspace bounds.

        Reference: OpenClaw src/agents/tools/memory-tool.ts  createMemoryGetTool()
        """
        normalized = rel_path.replace("\\", "/")
        allowed = (
            normalized in ("MEMORY.md", "memory.md")
            or normalized.startswith("memory/")
        )
        if not allowed or ".." in normalized:
            return {"path": rel_path, "text": "", "error": "Access denied"}

        full = self.workspace_dir / normalized
        if not full.exists():
            return {"path": rel_path, "text": "", "error": f"Not found: {rel_path}"}
        if full.is_symlink():
            return {"path": rel_path, "text": "", "error": "Symlinks rejected"}

        try:
            text = full.read_text(encoding="utf-8")
        except Exception as e:
            return {"path": rel_path, "text": "", "error": str(e)}

        lines = text.split("\n")
        if from_line is not None:
            start = max(0, from_line - 1)
            end = (start + n_lines) if n_lines else len(lines)
            lines = lines[start:end]
        return {"path": rel_path, "text": "\n".join(lines), "totalLines": len(lines)}

    def load_evergreen(self) -> str:
        """Read MEMORY.md (long-term memory)."""
        for name in ("MEMORY.md", "memory.md"):
            p = self.workspace_dir / name
            if p.exists() and not p.is_symlink():
                try:
                    return p.read_text(encoding="utf-8").strip()
                except Exception:
                    pass
        return ""

    def get_recent_daily(self, days: int = 3) -> list[dict]:
        """Get the most recent N days of daily logs."""
        results = []
        today = date.today()
        for i in range(days):
            d = today - timedelta(days=i)
            path = self.memory_dir / f"{d.isoformat()}.md"
            if path.exists():
                try:
                    content = path.read_text(encoding="utf-8").strip()
                    results.append({
                        "path": f"memory/{d.isoformat()}.md",
                        "date": d.isoformat(),
                        "content": content,
                    })
                except Exception:
                    pass
        return results

    def search(self, query: str, **kwargs) -> list[dict]:
        """Delegate to search index."""
        return self._search_index.search(query, **kwargs)


# Global manager cache
_managers: dict[str, MemoryManager] = {}


def get_memory_manager(agent_id: str, workspace_dir: Path) -> MemoryManager:
    """Get or create a MemoryManager for the given agent."""
    if agent_id not in _managers:
        _managers[agent_id] = MemoryManager(workspace_dir)
    return _managers[agent_id]


class MemorySearchTool(Tool):
    """Semantically search MEMORY.md + memory/*.md files.

    Uses TF-IDF + BM25 hybrid search to find relevant memory chunks.
    """

    def __init__(self, workspace_dir: Path):
        self._workspace_dir = workspace_dir
        self._manager = MemoryManager(workspace_dir)

    @property
    def name(self) -> str:
        return "memory_search"

    @property
    def description(self) -> str:
        return (
            "Mandatory recall step: semantically search MEMORY.md + memory/*.md "
            "before answering questions about prior work, decisions, dates, people, "
            "preferences, or todos; returns top snippets with path + lines. "
            "Use memory_get after to pull only the needed lines and keep context small."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query.",
                },
                "maxResults": {
                    "type": "integer",
                    "description": f"Max results (default {SEARCH_MAX_RESULTS}).",
                },
                "minScore": {
                    "type": "number",
                    "description": f"Min relevance 0-1 (default {SEARCH_MIN_SCORE}).",
                },
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs: Any) -> str:
        query = kwargs.get("query", "")
        if not query.strip():
            return json.dumps({"results": [], "error": "Empty query"})
        max_r = kwargs.get("maxResults", SEARCH_MAX_RESULTS)
        min_s = kwargs.get("minScore", SEARCH_MIN_SCORE)
        results = self._manager.search(query, max_results=max_r, min_score=min_s)
        return json.dumps({
            "results": results,
            "provider": "tfidf+bm25",
            "model": "hybrid-local",
        })


class MemoryGetTool(Tool):
    """Safe snippet read from memory files with optional line range."""

    def __init__(self, workspace_dir: Path):
        self._workspace_dir = workspace_dir
        self._manager = MemoryManager(workspace_dir)

    @property
    def name(self) -> str:
        return "memory_get"

    @property
    def description(self) -> str:
        return (
            "Safe snippet read from MEMORY.md or memory/*.md with optional from/lines; "
            "use after memory_search to pull only the needed lines and keep context small."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Workspace-relative path (e.g. 'MEMORY.md', 'memory/2026-03-04.md').",
                },
                "from": {
                    "type": "integer",
                    "description": "Start line (1-indexed). Omit to read whole file.",
                },
                "lines": {
                    "type": "integer",
                    "description": "Number of lines to read.",
                },
            },
            "required": ["path"],
        }

    async def execute(self, **kwargs: Any) -> str:
        path = kwargs.get("path", "")
        if not path.strip():
            return json.dumps({"path": "", "text": "", "error": "Path required"})
        result = self._manager.read_file(
            path,
            from_line=kwargs.get("from"),
            n_lines=kwargs.get("lines"),
        )
        return json.dumps(result)


class MemoryWriteTool(Tool):
    """Append a timestamped entry to today's daily memory log.

    Teaching shortcut -- production OpenClaw writes via bash tools.
    """

    def __init__(self, workspace_dir: Path):
        self._workspace_dir = workspace_dir
        self._manager = MemoryManager(workspace_dir)

    @property
    def name(self) -> str:
        return "memory_write"

    @property
    def description(self) -> str:
        return (
            "Append a timestamped entry to today's memory/YYYY-MM-DD.md. "
            "Use for preferences, facts, decisions. "
            "(Teaching shortcut -- production OpenClaw writes via bash tools.)"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The information to remember.",
                },
                "category": {
                    "type": "string",
                    "description": "Tag: preference / fact / decision / todo / person.",
                },
            },
            "required": ["content"],
        }

    async def execute(self, **kwargs: Any) -> str:
        content = kwargs.get("content", "")
        if not content.strip():
            return json.dumps({"error": "Empty content"})
        cat = kwargs.get("category", "general")
        rel = self._manager.write_daily(content, cat)
        return json.dumps({"status": "saved", "path": rel, "category": cat})


def register_memory_tools(registry, workspace_dir: Path) -> None:
    """Register all memory tools into a ToolRegistry."""
    registry.register(MemorySearchTool(workspace_dir))
    registry.register(MemoryGetTool(workspace_dir))
    registry.register(MemoryWriteTool(workspace_dir))
