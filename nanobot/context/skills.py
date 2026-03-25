"""Skills loader for agent capabilities."""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any, ClassVar

import yaml  # type: ignore[import-untyped]
from loguru import logger

from nanobot.tools.base import Tool

# size-exception: skill discovery + matching + summary are tightly coupled;
# extraction deferred until file approaches 600 LOC

# Default builtin skills directory (relative to this file)
BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "skills"

# P-04/P-14: process-lifetime cache for shutil.which() — binary locations are
# stable for the process lifetime and repeated calls are unnecessary syscalls.
_which_cache: dict[str, str | None] = {}


def _which(binary: str) -> str | None:
    if binary not in _which_cache:
        _which_cache[binary] = shutil.which(binary)
    return _which_cache[binary]


# Claude Code → nanobot tool mapping.
# Keys: Claude Code tool names (case-sensitive, matched with word boundaries).
# Values: (nanobot_tool, usage_hint) — tool name for text rewriting, hint for preamble.
CLAUDE_TOOL_MAPPING: dict[str, tuple[str, str]] = {
    "Bash": ("exec", "use the `exec` tool"),
    "Read": ("read_file", "use the `read_file` tool"),
    "Write": ("write_file", "use the `write_file` tool"),
    "Edit": ("edit_file", "use the `edit_file` tool"),
    "Glob": ("exec", "use the `exec` tool with `find` or `ls`"),
    "Grep": ("exec", "use the `exec` tool with `grep` or `rg`"),
    "WebFetch": ("web_fetch", "use the `web_fetch` tool"),
    "WebSearch": ("web_search", "use the `web_search` tool"),
    "Agent": (
        "delegate",
        "use the `delegate` tool (approximate — nanobot delegation, not autonomous sub-agents)",
    ),
    "TodoWrite": ("write_scratchpad", "use the `write_scratchpad` tool"),
    "TodoRead": ("read_scratchpad", "use the `read_scratchpad` tool"),
    "ListDir": ("list_dir", "use the `list_dir` tool"),
    "AskUserQuestion": ("message", "use the `message` tool to ask the user"),
}


def _detect_skill_tools(content: str) -> dict[str, str]:
    """Scan skill content for Claude Code tool references and bash code blocks.

    Returns a dict mapping detected source → preamble hint string.
    The synthetic key ``__bash_blocks__`` indicates bash/shell/sh fenced blocks.
    """
    detected: dict[str, str] = {}

    # 1. Bash code blocks
    if re.search(r"```(?:bash|shell|sh)\b", content):
        detected["__bash_blocks__"] = "use the `exec` tool"

    # 2. Claude Code tool names — detection uses the SAME patterns as rewrite
    # to avoid detecting names we can't reliably rewrite (e.g., bare "Bash" in prose).
    for tool_name, (_nanobot_name, hint) in CLAUDE_TOOL_MAPPING.items():
        # Both safe and ambiguous names use contextual matching:
        # backtick-wrapped, "the X tool", or "X tool".
        pattern = rf"`{tool_name}`|the\s+{tool_name}\s+tool|\b{tool_name}\s+tool\b"
        if re.search(pattern, content):
            detected[tool_name] = hint

    return detected


def _rewrite_skill_content(content: str, detected: dict[str, str]) -> str:
    """Replace Claude Code tool names with nanobot equivalents in prose sections.

    Fenced code blocks are preserved — only prose outside fences is rewritten.
    The synthetic ``__bash_blocks__`` key is skipped (it drives the preamble, not rewrites).
    """
    # Filter to only Claude Code tool names (skip __bash_blocks__ and other synthetic keys)
    tool_names = [k for k in detected if k in CLAUDE_TOOL_MAPPING]
    if not tool_names:
        return content

    # Split into prose and code-block segments using a state machine.
    segments = _split_fenced_blocks(content)

    # Rewrite only prose segments.
    for i, (is_code, text) in enumerate(segments):
        if is_code:
            continue
        for tool_name in tool_names:
            nanobot_name = CLAUDE_TOOL_MAPPING[tool_name][0]
            # Same contextual patterns for all tool names (safe and ambiguous):
            # backtick-wrapped, "the X tool", or "X tool".
            text = re.sub(rf"`{tool_name}`", f"`{nanobot_name}`", text)
            text = re.sub(rf"\bthe\s+{tool_name}\s+tool\b", f"the {nanobot_name} tool", text)
            text = re.sub(rf"\b{tool_name}\s+tool\b", f"{nanobot_name} tool", text)
        segments[i] = (False, text)

    return "".join(text for _, text in segments)


def _split_fenced_blocks(content: str) -> list[tuple[bool, str]]:
    """Split markdown content into (is_code, text) segments.

    Uses a state machine to track fenced code blocks (3+ backticks).
    Handles nested fences by matching fence length on close.
    """
    segments: list[tuple[bool, str]] = []
    fence_pattern = re.compile(r"^(`{3,})\s*(\w*)\s*$", re.MULTILINE)
    pos = 0
    open_fence: str | None = None  # The backtick string that opened the current block

    for match in fence_pattern.finditer(content):
        backticks = match.group(1)
        if open_fence is None:
            # Opening a code block — flush prose before it
            if match.start() > pos:
                segments.append((False, content[pos : match.start()]))
            open_fence = backticks
            pos = match.start()
        elif len(backticks) >= len(open_fence) and not match.group(2):
            # Closing a code block — fence length must match or exceed opener,
            # and closing fence must have no info string.
            segments.append((True, content[pos : match.end()]))
            pos = match.end()
            open_fence = None

    # Remaining content
    if pos < len(content):
        segments.append((open_fence is not None, content[pos:]))

    return segments


def _build_skill_preamble(detected: dict[str, str]) -> str:
    """Build a dynamic preamble from detected tool references.

    Returns an empty string if nothing was detected.
    """
    if not detected:
        return ""

    lines: list[str] = []
    has_bash_blocks = "__bash_blocks__" in detected
    has_bash_tool = "Bash" in detected

    # Bash blocks / Bash tool — merge into a single line
    if has_bash_blocks or has_bash_tool:
        lines.append("- To run the bash/CLI commands in these instructions, use the `exec` tool")

    # Other Claude Code tool mappings
    for key, hint in detected.items():
        if key in ("__bash_blocks__", "Bash"):
            continue  # already handled above
        lines.append(f"- `{key}` \u2192 {hint}")

    if not lines:
        return ""

    return "## Tool Instructions\n\n" + "\n".join(lines)


class SkillsLoader:
    """
    Loader for agent skills.

    Skills are markdown files (SKILL.md) that teach the agent how to use
    specific tools or perform certain tasks.
    """

    # P-04: TTL for the skills list cache (builtin skills never change at
    # runtime; workspace skills rarely do).  30 s is well below any perceptible
    # latency while avoiding repeated rglob + YAML parses per turn.
    _LIST_CACHE_TTL: ClassVar[float] = 30.0

    def __init__(self, workspace: Path, builtin_skills_dir: Path | None = None):
        self.workspace = workspace
        self.workspace_skills = workspace / "skills"
        self.builtin_skills = builtin_skills_dir or BUILTIN_SKILLS_DIR
        self._list_cache: list[dict[str, str]] | None = None
        self._list_cache_ts: float = 0.0

    def list_skills(self, filter_unavailable: bool = True) -> list[dict[str, str]]:
        """
        List all available skills.

        Args:
            filter_unavailable: If True, filter out skills with unmet requirements.

        Returns:
            List of skill info dicts with 'name', 'path', 'source'.
        """
        # P-04: serve from TTL cache — rglob + YAML parses are expensive per turn.
        now = time.monotonic()
        if self._list_cache is None or (now - self._list_cache_ts) > self._LIST_CACHE_TTL:
            self._list_cache = self._discover_skills()
            self._list_cache_ts = now

        skills = self._list_cache

        # Filter by requirements
        if filter_unavailable:
            return [s for s in skills if self._check_requirements(self._get_skill_meta(s["name"]))]
        return list(skills)

    def _discover_skills(self) -> list[dict[str, str]]:
        """Perform the actual filesystem scan for SKILL.md files."""
        skills: list[dict[str, str]] = []
        seen_names: set[str] = set()

        # Workspace skills (highest priority) — recursive discovery
        for skill_dir in self._find_all_skill_dirs(self.workspace_skills):
            if skill_dir.name not in seen_names:
                skills.append(
                    {
                        "name": skill_dir.name,
                        "path": (skill_dir / "SKILL.md").as_posix(),
                        "source": "workspace",
                    }
                )
                seen_names.add(skill_dir.name)

        # Built-in skills — recursive discovery
        for skill_dir in self._find_all_skill_dirs(self.builtin_skills):
            if skill_dir.name not in seen_names:
                skills.append(
                    {
                        "name": skill_dir.name,
                        "path": (skill_dir / "SKILL.md").as_posix(),
                        "source": "builtin",
                    }
                )
                seen_names.add(skill_dir.name)

        return skills

    def load_skill(self, name: str) -> str | None:
        """
        Load a skill by name.

        Args:
            name: Skill name (directory name).

        Returns:
            Skill content or None if not found.
        """
        skill_dir = self._resolve_skill_dir(name)
        if skill_dir is not None:
            return (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        return None

    def load_skills_for_context(self, skill_names: list[str]) -> str:
        """
        Load specific skills for inclusion in agent context.

        Args:
            skill_names: List of skill names to load.

        Returns:
            Formatted skills content.
        """
        parts = []
        for name in skill_names:
            content = self.load_skill(name)
            if content:
                content = self._strip_frontmatter(content)
                parts.append(f"### Skill: {name}\n\n{content}")

        return "\n\n---\n\n".join(parts) if parts else ""

    def build_skills_summary(self) -> str:
        """Build a flat listing of all available skills.

        Always-on skills are excluded (they are already fully injected).
        The agent calls ``load_skill`` by name to get full instructions.
        """
        all_skills = self.list_skills(filter_unavailable=False)
        if not all_skills:
            return ""

        always_set = set(self.get_always_skills())
        lines: list[str] = []

        for s in all_skills:
            name = s["name"]
            if name in always_set:
                continue
            desc = self._get_skill_description(name)
            skill_meta = self._get_skill_meta(name)
            available = self._check_requirements(skill_meta)
            status = "✓" if available else "✗"
            lines.append(f"- {status} **{name}**: {desc}")

        return "\n".join(lines)

    def _get_missing_requirements(self, skill_meta: dict) -> str:
        """Get a description of missing requirements."""
        missing = []
        requires = skill_meta.get("requires", {})
        for b in requires.get("bins", []):
            if not _which(b):
                missing.append(f"CLI: {b}")
        for env in requires.get("env", []):
            if not os.environ.get(env):
                missing.append(f"ENV: {env}")
        return ", ".join(missing)

    def _get_skill_description(self, name: str) -> str:
        """Get the description of a skill from its frontmatter."""
        meta = self.get_skill_metadata(name)
        if meta and meta.get("description"):
            return str(meta["description"])
        return name  # Fallback to skill name

    def _strip_frontmatter(self, content: str) -> str:
        """Remove YAML frontmatter from markdown content."""
        if content.startswith("---"):
            match = re.match(r"^---\n.*?\n---\n", content, re.DOTALL)
            if match:
                return content[match.end() :].strip()
        return content

    def _parse_nanobot_metadata(self, raw: Any) -> dict:
        """Parse skill metadata from frontmatter (stringified JSON or YAML object)."""
        data: Any = raw
        if isinstance(raw, str):
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return {}

        if not isinstance(data, dict):
            return {}

        # Accept historical aliases used by third-party skills.
        if isinstance(data.get("nanobot"), dict):
            return dict(data["nanobot"])
        if isinstance(data.get("openclaw"), dict):
            return dict(data["openclaw"])
        if isinstance(data.get("clawdbot"), dict):
            return dict(data["clawdbot"])
        return dict(data)

    def _check_requirements(self, skill_meta: dict) -> bool:
        """Check if skill requirements are met (bins, env vars)."""
        requires = skill_meta.get("requires", {})
        for b in requires.get("bins", []):
            if not _which(b):
                return False
        for env in requires.get("env", []):
            if not os.environ.get(env):
                return False
        return True

    def _get_skill_meta(self, name: str) -> dict:
        """Get nanobot metadata for a skill (cached in frontmatter)."""
        meta = self.get_skill_metadata(name) or {}
        return self._parse_nanobot_metadata(meta.get("metadata", ""))

    def get_always_skills(self) -> list[str]:
        """Get skills marked as always=true that meet requirements."""
        result = []
        for s in self.list_skills(filter_unavailable=True):
            meta = self.get_skill_metadata(s["name"]) or {}
            skill_meta = self._parse_nanobot_metadata(meta.get("metadata", ""))
            if skill_meta.get("always") or meta.get("always"):
                result.append(s["name"])
        return result

    # ------------------------------------------------------------------
    # Custom tool discovery (Step 14)
    # ------------------------------------------------------------------

    def discover_tools(self, skill_names: list[str] | None = None) -> list[Tool]:
        """Discover ``Tool`` subclasses from skill ``tools.py`` files.

        For each activated skill that contains a ``tools.py`` module in its
        directory, the module is imported and all public classes that inherit
        from :class:`Tool` are instantiated (with no arguments) and returned.

        Args:
            skill_names: If provided, only inspect these skills.  Otherwise
                inspect all available skills.

        Returns:
            List of Tool instances ready for registration.
        """
        names = skill_names or [s["name"] for s in self.list_skills()]
        tools: list[Tool] = []

        for name in names:
            tool_module_path = self._find_skill_tools_py(name)
            if tool_module_path is None:
                continue
            try:
                instances = self._load_tools_from_module(name, tool_module_path)
                tools.extend(instances)
                if instances:
                    logger.info(
                        "Skill '{}' registered {} custom tool(s): {}",
                        name,
                        len(instances),
                        ", ".join(t.name for t in instances),
                    )
            except Exception:  # crash-barrier: dynamic module loading
                logger.exception("Failed to load custom tools from skill '{}'", name)
        return tools

    def _find_skill_tools_py(self, name: str) -> Path | None:
        """Return the path to a skill's ``tools.py`` if it exists."""
        skill_dir = self._resolve_skill_dir(name)
        if skill_dir is not None:
            tools_path = skill_dir / "tools.py"
            if tools_path.is_file():
                return tools_path
        return None

    @staticmethod
    def _load_tools_from_module(skill_name: str, module_path: Path) -> list[Tool]:
        """Import a Python module by file path and extract ``Tool`` subclasses.

        Each concrete (non-abstract) ``Tool`` subclass found in the module is
        instantiated with no arguments.  If instantiation fails (e.g. the
        tool requires constructor args), it is skipped with a warning.
        """
        module_name = f"nanobot_skill_{skill_name}_tools"
        spec = importlib.util.spec_from_file_location(module_name, str(module_path))
        if spec is None or spec.loader is None:
            return []

        mod = importlib.util.module_from_spec(spec)
        # Temporarily add the module so relative imports within it work
        sys.modules[module_name] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception:  # crash-barrier: arbitrary module execution
            sys.modules.pop(module_name, None)
            raise

        instances: list[Tool] = []
        for attr_name in dir(mod):
            if attr_name.startswith("_"):
                continue
            obj = getattr(mod, attr_name)
            if (
                inspect.isclass(obj)
                and issubclass(obj, Tool)
                and obj is not Tool
                and not inspect.isabstract(obj)
            ):
                try:
                    instances.append(obj())
                except Exception:  # crash-barrier: arbitrary constructor
                    logger.warning(
                        "Skill '{}': could not instantiate tool class '{}'",
                        skill_name,
                        attr_name,
                    )
        return instances

    @staticmethod
    def _find_all_skill_dirs(root: Path | None) -> list[Path]:
        """Recursively find all directories containing SKILL.md under *root*."""
        if root is None or not root.exists():
            return []
        return sorted(
            {p.parent for p in root.rglob("SKILL.md") if p.parent != root},
            key=lambda d: d.name,
        )

    def _resolve_skill_dir(self, name: str) -> Path | None:
        """Resolve a skill name to its directory (workspace first, then builtin)."""
        for skill_dir in self._find_all_skill_dirs(self.workspace_skills):
            if skill_dir.name == name:
                return skill_dir
        for skill_dir in self._find_all_skill_dirs(self.builtin_skills):
            if skill_dir.name == name:
                return skill_dir
        return None

    def get_skill_metadata(self, name: str) -> dict | None:
        """
        Get metadata from a skill's frontmatter.

        Args:
            name: Skill name.

        Returns:
            Metadata dict or None.
        """
        content = self.load_skill(name)
        if not content:
            return None

        if content.startswith("---"):
            match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
            if match:
                try:
                    raw = yaml.safe_load(match.group(1))
                    if isinstance(raw, dict):
                        return raw
                except Exception as exc:  # crash-barrier: third-party YAML library
                    logger.debug("YAML frontmatter parse failed: {}", exc)

        return None
