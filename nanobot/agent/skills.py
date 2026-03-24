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

# Default builtin skills directory (relative to this file)
BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "skills"

# P-04/P-14: process-lifetime cache for shutil.which() — binary locations are
# stable for the process lifetime and repeated calls are unnecessary syscalls.
_which_cache: dict[str, str | None] = {}


def _which(binary: str) -> str | None:
    if binary not in _which_cache:
        _which_cache[binary] = shutil.which(binary)
    return _which_cache[binary]


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
                        "path": str(skill_dir / "SKILL.md"),
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
                        "path": str(skill_dir / "SKILL.md"),
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
        """Build a compact plain-text listing of all skills (one line per skill).

        Used for progressive loading — the agent can read the full skill content
        via read_file when needed.
        """
        all_skills = self.list_skills(filter_unavailable=False)
        if not all_skills:
            return ""

        lines = ["## Available Skills"]
        for s in all_skills:
            skill_meta = self._get_skill_meta(s["name"])
            available = self._check_requirements(skill_meta)
            status = "✓" if available else "✗"
            desc = self._get_skill_description(s["name"])
            lines.append(f"- {status} **{s['name']}**: {desc}")
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

    def detect_relevant_skills(self, message: str, max_skills: int = 4) -> list[str]:
        """Select skills that match the user message via triggers or description."""
        text = self._normalize_text(message)
        if not text:
            return []

        matches: list[str] = []
        remaining: list[dict[str, str]] = []

        # Pass 1: exact trigger matching (high confidence)
        for skill in self.list_skills(filter_unavailable=True):
            name = skill["name"]
            triggers = self._skill_triggers(name)
            if any(t in text for t in triggers):
                matches.append(name)
                if len(matches) >= max_skills:
                    return matches
            else:
                remaining.append(skill)

        # Pass 2: description keyword matching (lower confidence, fills remaining slots)
        #
        # Scoring uses max(precision, recall) so description length does not
        # penalise skills with detailed descriptions:
        #   precision = hits / desc_keywords   (original metric — biased against long descs)
        #   recall    = hits / msg_keywords    (new — how much of the query the skill covers)
        #   score     = max(precision, recall)
        #
        # Both sets are stemmed before comparison so word-form variants
        # ("summarize" / "summary", "analyze" / "analysis") match correctly.
        if remaining and len(matches) < max_skills:
            msg_keywords = self._description_keywords(text)
            msg_stems = {self._stem(w) for w in msg_keywords}
            scored: list[tuple[float, str]] = []
            for skill in remaining:
                name = skill["name"]
                desc = self._get_skill_description(name)
                keywords = self._description_keywords(desc)
                if len(keywords) < 2:
                    continue
                desc_stems = {self._stem(w) for w in keywords}
                hits = len(msg_stems & desc_stems)
                if hits < 2:
                    continue
                precision = hits / len(desc_stems)
                recall = hits / len(msg_stems) if msg_stems else 0.0
                score = max(precision, recall)
                if score >= 0.2:
                    scored.append((score, name))
            scored.sort(reverse=True)
            for _score, name in scored:
                matches.append(name)
                if len(matches) >= max_skills:
                    break

        return matches

    def _skill_triggers(self, name: str) -> list[str]:
        """Build normalized trigger phrases from metadata and skill name."""
        meta = self.get_skill_metadata(name) or {}
        triggers: list[str] = []

        raw_triggers = meta.get("triggers")
        if isinstance(raw_triggers, list):
            for t in raw_triggers:
                if isinstance(t, str):
                    triggers.append(t)
        elif isinstance(raw_triggers, str):
            triggers.append(raw_triggers)

        triggers.append(name)
        triggers.append(name.replace("-", " "))
        triggers.append(name.replace("_", " "))

        deduped: list[str] = []
        for t in triggers:
            norm = self._normalize_text(t)
            if norm and norm not in deduped:
                deduped.append(norm)
        return deduped

    @staticmethod
    def _normalize_text(value: str) -> str:
        text = value.lower()
        text = re.sub(r"[^a-z0-9\s_-]+", " ", text)
        text = text.replace("-", " ").replace("_", " ")
        return re.sub(r"\s+", " ", text).strip()

    # Stopwords filtered out of skill descriptions for keyword matching
    _STOPWORDS: frozenset[str] = frozenset(
        "a an the and or but is are was were be been being "
        "do does did have has had will would shall should may might can could "
        "to for of in on at by from with as it its this that these those "
        "not no nor so if when how what which who whom whose where why "
        "use using used any all each every some such than then also very "
        "about into through during before after above below between out up down "
        "own only just more most other another need needs".split()
    )

    @classmethod
    def _description_keywords(cls, description: str) -> list[str]:
        """Extract unique significant keywords from a skill description."""
        text = cls._normalize_text(description)
        seen: set[str] = set()
        keywords: list[str] = []
        for w in text.split():
            if w not in cls._STOPWORDS and len(w) > 2 and w not in seen:
                seen.add(w)
                keywords.append(w)
        return keywords

    @staticmethod
    def _stem(word: str) -> str:
        """Reduce a word to an approximate stem by stripping common suffixes.

        Handles the most frequent English inflections so that word-form
        variants match during skill detection (e.g. "summarize"/"summary",
        "analyze"/"analysis", "schedule"/"schedules", "gate"/"gates").
        """
        # Longest suffixes first to avoid partial stripping.
        suffixes = (
            "ization",
            "isation",
            "ization",
            "ation",
            "iness",
            "iness",
            "ness",
            "ment",
            "tion",
            "ize",
            "ise",
            "ing",
            "ies",
            "ied",
            "ers",
            "est",
            "ed",
            "er",
            "es",
            "ly",
        )
        for s in suffixes:
            if word.endswith(s) and len(word) - len(s) >= 3:
                return word[: -len(s)]
        # Strip a plain trailing 's' (plurals) when stem would be ≥ 3 chars.
        if word.endswith("s") and len(word) > 3:
            return word[:-1]
        return word
