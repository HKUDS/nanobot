"""Skills loader for agent capabilities."""

import importlib.util
import json
import os
import re
import shutil
import sys
from pathlib import Path

from nanobot.agent.tools.skill import SkillFunctionTool

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
                        skills.append({"name": skill_dir.name, "path": str(skill_file), "source": "workspace"})
        
        # Built-in skills
        if self.builtin_skills and self.builtin_skills.exists():
            for skill_dir in self.builtin_skills.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists() and not any(s["name"] == skill_dir.name for s in skills):
                        skills.append({"name": skill_dir.name, "path": str(skill_file), "source": "builtin"})
        
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
            
            lines.append(f"  </skill>")
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
            return meta["description"]
        return name  # Fallback to skill name
    
    def _strip_frontmatter(self, content: str) -> str:
        """Remove YAML frontmatter from markdown content."""
        if content.startswith("---"):
            match = re.match(r"^---\n.*?\n---\n", content, re.DOTALL)
            if match:
                return content[match.end():].strip()
        return content
    
    def _parse_nanobot_metadata(self, raw: str) -> dict:
        """Parse skill metadata JSON from frontmatter (supports nanobot and openclaw keys)."""
        try:
            data = json.loads(raw)
            return data.get("nanobot", data.get("openclaw", {})) if isinstance(data, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    
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
                # Simple YAML parsing
                metadata = {}
                for line in match.group(1).split("\n"):
                    if ":" in line:
                        key, value = line.split(":", 1)
                        metadata[key.strip()] = value.strip().strip('"\')
                return metadata
        
        return None

    def load_skill_tools(self) -> list[SkillFunctionTool]:
        """
        Load tools from skill.py modules in available skills.

        Discovers skill.py in each skill directory (workspace and builtin),
        imports callable functions (excluding private names), and wraps them
        as SkillFunctionTool instances.

        Returns:
            List of SkillFunctionTool instances.
        """
        tools: list[SkillFunctionTool] = []
        seen_skill_dirs: set[Path] = set()

        def _try_load_skill_module(skill_dir: Path, skill_name: str) -> None:
            if skill_dir in seen_skill_dirs:
                return
            seen_skill_dirs.add(skill_dir)
            skill_py = skill_dir / "skill.py"
            if not skill_py.exists():
                return
            # Check requirements before loading
            skill_meta = self._get_skill_meta(skill_name)
            if not self._check_requirements(skill_meta):
                return
            try:
                spec = importlib.util.spec_from_file_location(
                    f"skill_{skill_name}", skill_py
                )
                if not spec or not spec.loader:
                    return
                module = importlib.util.module_from_spec(spec)
                # Ensure skill dir is on path for imports from same skill
                skill_dir_str = str(skill_dir)
                if skill_dir_str not in sys.path:
                    sys.path.insert(0, skill_dir_str)
                spec.loader.exec_module(module)
                mod_name = getattr(module, "__name__", "")
                for attr_name in dir(module):
                    if attr_name.startswith("_"):
                        continue
                    obj = getattr(module, attr_name)
                    if not (callable(obj) and not isinstance(obj, type)):
                        continue
                    # Only register functions defined in this module (not imports)
                    if getattr(obj, "__module__", "") != mod_name:
                        continue
                    tools.append(
                        SkillFunctionTool(
                            skill_name=skill_name,
                            func=obj,
                            working_dir=skill_dir,
                        )
                    )
            except Exception:
                pass  # Skip skills that fail to load

        # Workspace skills first (highest priority)
        workspace_skill_names: set[str] = set()
        if self.workspace_skills.exists():
            for skill_dir in self.workspace_skills.iterdir():
                if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                    workspace_skill_names.add(skill_dir.name)
                    _try_load_skill_module(skill_dir, skill_dir.name)

        # Built-in skills (skip if workspace overrides)
        if self.builtin_skills and self.builtin_skills.exists():
            for skill_dir in self.builtin_skills.iterdir():
                if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                    if skill_dir.name not in workspace_skill_names:
                        _try_load_skill_module(skill_dir, skill_dir.name)

        return tools
