"""Memory migration tool for cross-instance memory sharing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool


def discover_instances() -> dict[str, Path]:
    """Discover all nanobot instances on this machine.

    Returns a mapping of instance_name -> instance_root_dir.
    """
    home = Path.home()
    instances: dict[str, Path] = {}

    # Main instance: ~/.nanobot/
    main_root = home / ".nanobot"
    if (main_root / "config.json").exists():
        instances["main"] = main_root

    # Named instances: ~/.nanobot-{name}/
    for d in sorted(home.iterdir()):
        if d.name.startswith(".nanobot-") and d.is_dir():
            config = d / "config.json"
            if config.exists():
                name = d.name.removeprefix(".nanobot-")
                instances[name] = d

    return instances


def _load_instance_config(instance_root: Path) -> dict[str, Any]:
    """Load and parse an instance's config.json."""
    config_path = instance_root / "config.json"
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


def _check_sharing_permission(
    config: dict[str, Any], requester: str
) -> tuple[bool, str]:
    """Check if the target instance allows memory sharing to the requester.

    Returns (allowed, reason).
    """
    defaults = config.get("agents", {}).get("defaults", {})
    sharing = defaults.get("memorySharing", {})

    # Default: enabled=True if not configured
    enabled = sharing.get("enabled", True)
    if not enabled:
        return False, "Target instance has disabled memory sharing."

    allow_from = sharing.get("allowFrom", [])
    # Empty allowFrom = allow all (when enabled)
    if allow_from and requester not in allow_from:
        return False, (
            f"Requester '{requester}' is not in the target instance's "
            f"sharing whitelist: {allow_from}"
        )

    return True, "OK"


def _get_current_instance_name() -> str:
    """Derive the current instance name from the active config path."""
    from nanobot.config.loader import get_config_path

    config_path = get_config_path()
    parent_name = config_path.parent.name

    if parent_name == ".nanobot":
        return "main"
    elif parent_name.startswith(".nanobot-"):
        return parent_name.removeprefix(".nanobot-")
    return "unknown"


def _resolve_workspace(config: dict[str, Any], instance_root: Path) -> Path:
    """Resolve the workspace path from an instance's config."""
    workspace = config.get("agents", {}).get("defaults", {}).get("workspace", "")
    if workspace:
        return Path(workspace).expanduser()
    return instance_root / "workspace"


class MemoryMigrateTool(Tool):
    """Tool for reading memory from other nanobot instances."""

    @property
    def name(self) -> str:
        return "memory_migrate"

    @property
    def description(self) -> str:
        return (
            "Read memory, history, session logs, or skill definitions from another "
            "nanobot instance. Returns the content from the target instance. "
            "The tool only reads — you decide what to save into your own memory."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source_instance": {
                    "type": "string",
                    "description": (
                        "Name of the source instance to read from "
                        "(e.g. 'main', 'zhangjuzheng', 'lvfang'). "
                        "Use 'list' to discover all available instances."
                    ),
                },
                "query": {
                    "type": "string",
                    "description": (
                        "Natural language description of what content you need. "
                        "Used to search HISTORY.md and session logs for relevant entries. "
                        "Leave empty to get full content (for memory/skills)."
                    ),
                },
                "scope": {
                    "type": "string",
                    "enum": ["memory", "history", "sessions", "skills", "all"],
                    "description": (
                        "What to read: "
                        "'memory' = MEMORY.md only, "
                        "'history' = HISTORY.md only, "
                        "'sessions' = conversation session logs, "
                        "'skills' = skill definitions (SKILL.md files), "
                        "'all' = memory + history + sessions + skills. "
                        "Default: 'all'"
                    ),
                },
                "session_id": {
                    "type": "string",
                    "description": (
                        "Specific session file to read (e.g. 'feishu_oc_xxx'). "
                        "If omitted when scope='sessions', lists available sessions. "
                        "Supports keyword filter: partial match on filename."
                    ),
                },
                "skill_name": {
                    "type": "string",
                    "description": (
                        "Specific skill name to read (e.g. 'ai-paper-daily'). "
                        "If omitted when scope='skills', lists available skills."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        "Max number of matching lines/messages to return (default: 50)."
                    ),
                },
            },
            "required": ["source_instance"],
        }

    async def execute(self, **kwargs: Any) -> str:
        source = kwargs.get("source_instance", "")
        query = kwargs.get("query", "")
        scope = kwargs.get("scope", "all")
        session_id = kwargs.get("session_id", "")
        skill_name = kwargs.get("skill_name", "")
        limit = kwargs.get("limit", 50)

        # Discovery mode
        if source == "list":
            return self._list_instances()

        instances = discover_instances()
        if source not in instances:
            available = ", ".join(sorted(instances.keys()))
            return (
                f"Error: Instance '{source}' not found. "
                f"Available instances: {available}. "
                f"Use source_instance='list' to see all."
            )

        target_root = instances[source]
        current = _get_current_instance_name()

        if source == current:
            return "Error: Cannot migrate memory from yourself. Use read_file instead."

        # Permission check
        try:
            config = _load_instance_config(target_root)
        except Exception as e:
            return f"Error: Failed to load config for instance '{source}': {e}"

        allowed, reason = _check_sharing_permission(config, current)
        if not allowed:
            return f"Error: Permission denied — {reason}"

        workspace = _resolve_workspace(config, target_root)
        results: list[str] = []

        if scope in ("memory", "all"):
            results.append(self._read_memory(workspace, source))

        if scope in ("history", "all"):
            results.append(self._read_history(workspace, source, query, limit))

        if scope in ("sessions", "all"):
            results.append(
                self._read_sessions(workspace, source, query, session_id, limit)
            )

        if scope in ("skills", "all"):
            results.append(self._read_skills(workspace, source, skill_name))

        logger.info(
            "memory_migrate: {} -> {}, scope={}, query='{}'",
            source, current, scope, query[:60],
        )
        return "\n\n".join(results)

    # ── Memory ──────────────────────────────────────────────

    @staticmethod
    def _read_memory(workspace: Path, source: str) -> str:
        memory_file = workspace / "memory" / "MEMORY.md"
        if memory_file.exists():
            content = memory_file.read_text(encoding="utf-8")
            return f"=== MEMORY.md from [{source}] ({len(content)} chars) ===\n{content}"
        return f"=== MEMORY.md from [{source}] === (not found)"

    # ── History ─────────────────────────────────────────────

    @staticmethod
    def _read_history(
        workspace: Path, source: str, query: str, limit: int
    ) -> str:
        history_file = workspace / "memory" / "HISTORY.md"
        if not history_file.exists():
            return f"=== HISTORY.md from [{source}] === (not found)"

        content = history_file.read_text(encoding="utf-8")

        if query:
            terms = [t.lower() for t in query.split() if len(t) >= 2]
            matched = [
                line
                for line in content.splitlines()
                if any(t in line.lower() for t in terms)
            ]
            tail = matched[-limit:]
            return (
                f"=== HISTORY.md from [{source}] "
                f"(searched: '{query}', {len(tail)} of {len(matched)} matches) ===\n"
                + "\n".join(tail)
            )

        lines = content.strip().splitlines()
        tail = lines[-limit:]
        return (
            f"=== HISTORY.md from [{source}] "
            f"(last {len(tail)} of {len(lines)} entries) ===\n"
            + "\n".join(tail)
        )

    # ── Sessions ────────────────────────────────────────────

    @staticmethod
    def _read_sessions(
        workspace: Path, source: str, query: str, session_id: str, limit: int
    ) -> str:
        sessions_dir = workspace / "sessions"
        if not sessions_dir.exists():
            return f"=== Sessions from [{source}] === (directory not found)"

        session_files = sorted(sessions_dir.glob("*.jsonl"))
        if not session_files:
            return f"=== Sessions from [{source}] === (no sessions)"

        # If no specific session requested, list available sessions
        if not session_id:
            lines = [
                f"=== Sessions from [{source}] ({len(session_files)} files) ===",
                "Available sessions (use session_id to read a specific one):\n",
            ]
            for f in session_files:
                size_kb = f.stat().st_size / 1024
                lines.append(f"  • {f.stem} ({size_kb:.1f} KB)")
            return "\n".join(lines)

        # Find matching session file(s)
        matches = [f for f in session_files if session_id in f.stem]
        if not matches:
            return (
                f"=== Sessions from [{source}] === "
                f"No session matching '{session_id}'"
            )

        results: list[str] = []
        for sf in matches:
            results.append(
                _extract_session_messages(sf, source, query, limit)
            )
        return "\n".join(results)

    # ── Skills ──────────────────────────────────────────────

    @staticmethod
    def _read_skills(workspace: Path, source: str, skill_name: str) -> str:
        skills_dir = workspace / "skills"
        if not skills_dir.exists():
            return f"=== Skills from [{source}] === (directory not found)"

        skill_dirs = sorted(
            d for d in skills_dir.iterdir() if d.is_dir() and not d.name.startswith(".")
        )
        if not skill_dirs:
            return f"=== Skills from [{source}] === (no skills)"

        # If no specific skill requested, list available skills
        if not skill_name:
            lines = [f"=== Skills from [{source}] ({len(skill_dirs)} skills) ===\n"]
            for d in skill_dirs:
                skill_md = d / "SKILL.md"
                if skill_md.exists():
                    # Extract description from frontmatter
                    desc = _extract_skill_description(skill_md)
                    lines.append(f"  • {d.name} — {desc}")
                else:
                    lines.append(f"  • {d.name} (no SKILL.md)")
            return "\n".join(lines)

        # Read specific skill
        target = skills_dir / skill_name
        if not target.exists():
            return (
                f"=== Skills from [{source}] === "
                f"Skill '{skill_name}' not found. "
                f"Available: {', '.join(d.name for d in skill_dirs)}"
            )

        parts = [f"=== Skill '{skill_name}' from [{source}] ===\n"]

        # Read SKILL.md
        skill_md = target / "SKILL.md"
        if skill_md.exists():
            parts.append(f"── SKILL.md ──\n{skill_md.read_text(encoding='utf-8')}")

        # List and read reference files
        refs_dir = target / "references"
        if refs_dir.exists():
            ref_files = sorted(refs_dir.glob("*"))
            if ref_files:
                parts.append(f"\n── References ({len(ref_files)} files) ──")
                for rf in ref_files:
                    if rf.is_file() and rf.stat().st_size < 50_000:
                        parts.append(
                            f"\n[{rf.name}]\n{rf.read_text(encoding='utf-8', errors='replace')}"
                        )
                    elif rf.is_file():
                        parts.append(f"\n[{rf.name}] ({rf.stat().st_size / 1024:.1f} KB, too large)")

        # List other files in skill dir
        other_files = [
            f for f in sorted(target.iterdir())
            if f.is_file() and f.name != "SKILL.md" and not f.name.startswith(".")
        ]
        if other_files:
            parts.append(f"\n── Other files ──")
            for of in other_files:
                if of.stat().st_size < 30_000:
                    parts.append(
                        f"\n[{of.name}]\n{of.read_text(encoding='utf-8', errors='replace')}"
                    )
                else:
                    parts.append(f"\n[{of.name}] ({of.stat().st_size / 1024:.1f} KB)")

        return "\n".join(parts)

    # ── Instance listing ────────────────────────────────────

    def _list_instances(self) -> str:
        instances = discover_instances()
        current = _get_current_instance_name()

        lines = [f"Discovered {len(instances)} instance(s) (current: {current}):\n"]
        for name, root in sorted(instances.items()):
            marker = " (self)" if name == current else ""
            try:
                config = _load_instance_config(root)
                defaults = config.get("agents", {}).get("defaults", {})
                sharing = defaults.get("memorySharing", {})
                enabled = sharing.get("enabled", True)
                allow_from = sharing.get("allowFrom", [])

                if not enabled:
                    status = "sharing: OFF"
                elif allow_from:
                    status = f"sharing: whitelist {allow_from}"
                else:
                    status = "sharing: ON (open)"

                model = defaults.get("model", "?")
            except Exception:
                status = "sharing: unknown (config error)"
                model = "?"

            lines.append(f"  • {name}{marker} — {model} — {status}")

        return "\n".join(lines)


# ── Helpers ─────────────────────────────────────────────────


def _extract_session_messages(
    session_file: Path, source: str, query: str, limit: int
) -> str:
    """Extract human-readable messages from a session JSONL file."""
    messages: list[str] = []

    with open(session_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Skip metadata lines
            if obj.get("_type") == "metadata":
                continue

            role = obj.get("role", "")
            content = obj.get("content", "")
            ts = obj.get("timestamp", "")

            if not content or role not in ("user", "assistant"):
                continue

            # Truncate very long messages
            display = content[:500] + "..." if len(content) > 500 else content
            messages.append(f"[{ts}] {role}: {display}")

    # Apply query filter if provided
    if query:
        terms = [t.lower() for t in query.split() if len(t) >= 2]
        if terms:
            messages = [
                m for m in messages if any(t in m.lower() for t in terms)
            ]

    tail = messages[-limit:]
    return (
        f"=== Session '{session_file.stem}' from [{source}] "
        f"({len(tail)} of {len(messages)} messages) ===\n"
        + "\n".join(tail)
    )


def _extract_skill_description(skill_md: Path) -> str:
    """Extract the description field from a SKILL.md frontmatter."""
    content = skill_md.read_text(encoding="utf-8")
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("description:"):
            return stripped.removeprefix("description:").strip()
    return "(no description)"
