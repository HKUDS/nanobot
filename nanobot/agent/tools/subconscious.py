"""Subconscious tool — Obsidian vault search and memory sync.

Exposes four agent-callable tools:
  subconscious_search   : FTS search over the Obsidian vault
  subconscious_recall   : list recently modified vault notes
  subconscious_sync     : trigger a vault re-scan and memory export
  subconscious_entities : return knowledge graph of entities

Inspired by OpenHuman's memory_tools read-layer and memory_sync subsystems.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool, tool_parameters

_daemon = None   # module-level singleton, initialised lazily on first tool call


def _get_daemon(ctx: Any):
    global _daemon
    if _daemon is not None:
        return _daemon

    try:
        from nanobot.subconscious.sync import SubconsciousDaemon
    except ImportError as e:
        logger.error("Subconscious module not found: {}", e)
        return None

    config = getattr(ctx, "config", None)
    vault_path = None
    if config:
        tools_cfg = getattr(config, "tools", None)
        if tools_cfg:
            vault_path = getattr(tools_cfg, "subconscious_vault", None)

    if not vault_path:
        import os
        vault_path = os.environ.get("NANOBOT_OBSIDIAN_VAULT", "")

    if not vault_path:
        logger.warning(
            "Subconscious: vault not configured — set tools.subconsciousVault in config.json "
            "or export NANOBOT_OBSIDIAN_VAULT"
        )
        return None

    workspace = getattr(config, "workspace_path", None) if config else None
    if workspace is None:
        from pathlib import Path
        workspace = Path.home() / ".nanobot"

    from pathlib import Path
    _daemon = SubconsciousDaemon(
        vault_path=Path(vault_path),
        nanobot_workspace=Path(workspace),
    )
    _daemon.start()
    logger.info("Subconscious daemon started — vault: {}", vault_path)
    return _daemon


def start_daemon(vault_path: Any, workspace: Any) -> None:
    """Eagerly initialize the daemon without a tool ctx (called at agent startup)."""
    global _daemon
    if _daemon is not None:
        return
    try:
        from nanobot.subconscious.sync import SubconsciousDaemon
    except ImportError as e:
        logger.warning("Subconscious module not found: {}", e)
        return
    _daemon = SubconsciousDaemon(vault_path=vault_path, nanobot_workspace=workspace)
    _daemon.start()
    logger.info("Subconscious daemon eagerly started — vault: {}", vault_path)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@tool_parameters({
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Search query (keywords, phrases, or note titles)"},
        "limit": {"type": "integer", "description": "Max results (default 8, max 20)", "default": 8},
    },
    "required": ["query"],
})
class SubconsciousSearchTool(Tool):
    """Search Obsidian vault notes with full-text search."""

    name = "subconscious_search"
    description = (
        "Search your Obsidian vault notes using full-text search. "
        "Returns matching excerpts with note path, heading, tags, and linked entities. "
        "Always call this before answering questions that may be covered in your personal notes."
    )
    _scopes = {"core", "subagent"}

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return True

    @classmethod
    def create(cls, ctx: Any) -> "SubconsciousSearchTool":
        return cls(ctx)

    def __init__(self, ctx: Any) -> None:
        self._ctx = ctx

    async def execute(self, query: str, limit: int = 8) -> str:
        daemon = _get_daemon(self._ctx)
        if daemon is None:
            return "Subconscious not available — vault not configured. Check tools.subconsciousVault in ~/.nanobot/config.json"

        limit = min(int(limit), 20)
        results = daemon.search(query, limit=limit)
        if not results:
            return f"No vault notes found matching: {query!r}"

        lines = [f"Found {len(results)} vault excerpts for: {query!r}\n"]
        for i, r in enumerate(results, 1):
            tags_str = ", ".join(r["tags"]) if r["tags"] else "—"
            entities_str = ", ".join(r["entities"][:5]) if r["entities"] else "—"
            lines.append(
                f"### {i}. {r['source_path']} — {r['heading']}\n"
                f"**Tags:** {tags_str}  |  **Links:** {entities_str}\n\n"
                f"{r['content']}\n"
            )
        return "\n---\n".join(lines)


# ---------------------------------------------------------------------------
# Recall
# ---------------------------------------------------------------------------

@tool_parameters({
    "type": "object",
    "properties": {
        "limit": {"type": "integer", "description": "Number of recent notes (default 15)", "default": 15},
    },
    "required": [],
})
class SubconsciousRecallTool(Tool):
    """Return recently modified Obsidian vault notes."""

    name = "subconscious_recall"
    description = (
        "Retrieve recently modified notes from the Obsidian vault. "
        "Useful for understanding what the user has been working on lately."
    )
    _scopes = {"core", "subagent"}

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return True

    @classmethod
    def create(cls, ctx: Any) -> "SubconsciousRecallTool":
        return cls(ctx)

    def __init__(self, ctx: Any) -> None:
        self._ctx = ctx

    async def execute(self, limit: int = 15) -> str:
        daemon = _get_daemon(self._ctx)
        if daemon is None:
            return "Subconscious not available — vault not configured."

        results = daemon.recall(limit=int(limit))
        if not results:
            return "No vault notes indexed yet. Try running subconscious_sync first."

        lines = [f"## Recent vault notes ({len(results)} excerpts)\n"]
        seen: set[str] = set()
        for r in results:
            path = r["source_path"]
            if path in seen:
                continue
            seen.add(path)
            tags_str = ", ".join(r["tags"]) if r["tags"] else "—"
            lines.append(f"**{path}** ({tags_str})\n> {r['content'][:300]}\n")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

@tool_parameters({
    "type": "object",
    "properties": {
        "force": {"type": "boolean", "description": "Force re-ingest all files even if unchanged", "default": False},
    },
    "required": [],
})
class SubconsciousSyncTool(Tool):
    """Trigger vault re-scan and export nanobot memory to Obsidian."""

    name = "subconscious_sync"
    description = (
        "Trigger an immediate sync of the Obsidian vault: ingest new/modified notes "
        "and export nanobot memory (MEMORY.md, USER.md) to the vault under _nanobot/. "
        "Run this after editing notes in Obsidian."
    )
    _scopes = {"core"}

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return True

    @classmethod
    def create(cls, ctx: Any) -> "SubconsciousSyncTool":
        return cls(ctx)

    def __init__(self, ctx: Any) -> None:
        self._ctx = ctx

    async def execute(self, force: bool = False) -> str:
        daemon = _get_daemon(self._ctx)
        if daemon is None:
            return "Subconscious not available — vault not configured."

        result = daemon.trigger_sync(force=bool(force))
        stats = result.pop("stats", {})
        lines = [
            "## Vault sync complete",
            f"- Notes ingested: {result.get('ingested', 0)}",
            f"- Notes skipped (unchanged): {result.get('skipped', 0)}",
            f"- Errors: {result.get('errors', 0)}",
            "",
            f"**Index:** {stats.get('total_files', 0)} files, {stats.get('total_chunks', 0)} chunks",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entity Graph
# ---------------------------------------------------------------------------

@tool_parameters({
    "type": "object",
    "properties": {
        "limit": {"type": "integer", "description": "Max entities to return (default 30)", "default": 30},
    },
    "required": [],
})
class SubconsciousEntitiesTool(Tool):
    """Return the vault knowledge graph of entities and their connections."""

    name = "subconscious_entities"
    description = (
        "Return top entities (people, projects, wiki-linked notes) from the Obsidian vault "
        "with the notes they appear in. Useful for understanding knowledge connections."
    )
    _scopes = {"core", "subagent"}

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return True

    @classmethod
    def create(cls, ctx: Any) -> "SubconsciousEntitiesTool":
        return cls(ctx)

    def __init__(self, ctx: Any) -> None:
        self._ctx = ctx

    async def execute(self, limit: int = 30) -> str:
        daemon = _get_daemon(self._ctx)
        if daemon is None:
            return "Subconscious not available — vault not configured."

        entities = daemon.entity_graph(limit=int(limit))
        if not entities:
            return "No entities found. Run subconscious_sync to index the vault first."

        lines = ["## Vault Knowledge Graph — Top Entities\n"]
        for e in entities:
            notes = ", ".join(e["mentions_in"][:3])
            more = f" (+{len(e['mentions_in']) - 3} more)" if len(e["mentions_in"]) > 3 else ""
            lines.append(f"- **{e['entity']}** ({e['count']} mentions) — {notes}{more}")
        return "\n".join(lines)
