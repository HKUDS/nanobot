"""Skills loader for agent capabilities."""

import importlib.util
import inspect
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from loguru import logger

from nanobot.agent.tools.base import Tool

# Default builtin skills directory (relative to this file)
BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "skills"


class SkillsLoader:
    """
    Loader for agent skills.

    Skills are markdown files (SKILL.md) that teach the agent how to use
    specific tools or perform certain tasks.
    """

    def __init__(self, workspace: Path, builtin_skills_dir: Path | None = None):
        self.workspace = workspace
        self.workspace_skills = workspace / "skills"
        self.builtin_skills = builtin_skills_dir or BUILTIN_SKILLS_DIR

    def list_skills(self, filter_unavailable: bool = True) -> list[dict[str, str]]:
        """
        List all available skills.

        Args:
            filter_unavailable: If True, filter out skills with unmet requirements.

        Returns:
            List of skill info dicts with 'name', 'path', 'source'.
        """
        skills = []

        # Workspace skills (highest priority)
        if self.workspace_skills.exists():
            for skill_dir in self.workspace_skills.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists():
                        skills.append(
                            {"name": skill_dir.name, "path": str(skill_file), "source": "workspace"}
                        )

        # Built-in skills
        if self.builtin_skills and self.builtin_skills.exists():
            for skill_dir in self.builtin_skills.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists() and not any(s["name"] == skill_dir.name for s in skills):
                        skills.append(
                            {"name": skill_dir.name, "path": str(skill_file), "source": "builtin"}
                        )

        # Filter by requirements
        if filter_unavailable:
            return [s for s in skills if self._check_requirements(self._get_skill_meta(s["name"]))]
        return skills

    def load_skill(self, name: str) -> str | None:
        """
        Load a skill by name.

        Args:
            name: Skill name (directory name).

        Returns:
            Skill content or None if not found.
        """
        # Check workspace first
        workspace_skill = self.workspace_skills / name / "SKILL.md"
        if workspace_skill.exists():
            return workspace_skill.read_text(encoding="utf-8")

        # Check built-in
        if self.builtin_skills:
            builtin_skill = self.builtin_skills / name / "SKILL.md"
            if builtin_skill.exists():
                return builtin_skill.read_text(encoding="utf-8")

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
        """
        Build a summary of all skills (name, description, path, availability).

        This is used for progressive loading - the agent can read the full
        skill content using read_file when needed.

        Returns:
            XML-formatted skills summary.
        """
        all_skills = self.list_skills(filter_unavailable=False)
        if not all_skills:
            return ""

        def escape_xml(s: str) -> str:
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        lines = ["<skills>"]
        for s in all_skills:
            name = escape_xml(s["name"])
            path = s["path"]
            desc = escape_xml(self._get_skill_description(s["name"]))
            skill_meta = self._get_skill_meta(s["name"])
            available = self._check_requirements(skill_meta)

            lines.append(f'  <skill available="{str(available).lower()}">')
            lines.append(f"    <name>{name}</name>")
            lines.append(f"    <description>{desc}</description>")
            lines.append(f"    <location>{path}</location>")

            # Show missing requirements for unavailable skills
            if not available:
                missing = self._get_missing_requirements(skill_meta)
                if missing:
                    lines.append(f"    <requires>{escape_xml(missing)}</requires>")

            lines.append("  </skill>")
        lines.append("</skills>")

        return "\n".join(lines)

    def _get_missing_requirements(self, skill_meta: dict) -> str:
        """Get a description of missing requirements."""
        missing = []
        requires = skill_meta.get("requires", {})
        for b in requires.get("bins", []):
            if not shutil.which(b):
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
            if not shutil.which(b):
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
        # Workspace skills take priority
        workspace_path = self.workspace_skills / name / "tools.py"
        if workspace_path.is_file():
            return workspace_path
        if self.builtin_skills:
            builtin_path = self.builtin_skills / name / "tools.py"
            if builtin_path.is_file():
                return builtin_path
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
                except Exception:  # crash-barrier: third-party YAML library
                    pass

        return None

    def detect_relevant_skills(self, message: str, max_skills: int = 4) -> list[str]:
        """Select skills that match the user message via trigger phrases."""
        text = self._normalize_text(message)
        if not text:
            return []

        matches: list[str] = []
        for skill in self.list_skills(filter_unavailable=True):
            name = skill["name"]
            triggers = self._skill_triggers(name)
            if any(t in text for t in triggers):
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
