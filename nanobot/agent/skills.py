"""Skills loader for agent capabilities.

Supports both nanobot's native skill format and the AgentSkills.io
open standard (https://agentskills.io/specification).
"""

import json
import logging
import os
import re
import shutil
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# Default builtin skills directory (relative to this file)
BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "skills"

logger = logging.getLogger(__name__)

# AgentSkills.io name validation pattern
_SKILL_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


def _parse_yaml_frontmatter(raw: str) -> dict[str, Any]:
    """Parse YAML frontmatter with support for nested mappings.

    Handles both simple ``key: value`` lines and one-level nested mappings
    (like ``metadata:`` with indented children).  This keeps nanobot free of
    external YAML dependencies while being compatible with the AgentSkills.io
    spec.
    """
    result: dict[str, Any] = {}
    current_key: str | None = None
    current_map: dict[str, str] | None = None

    for line in raw.split("\n"):
        # Skip blank lines and comments
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip())

        # Nested value (indented under a mapping key)
        if indent >= 2 and current_key is not None and ":" in stripped:
            k, v = stripped.split(":", 1)
            k = k.strip()
            v = v.strip().strip("\"'")
            if current_map is None:
                current_map = {}
            current_map[k] = v
            continue

        # Flush previous nested mapping
        if current_key is not None and current_map is not None:
            result[current_key] = current_map
            current_map = None
            current_key = None

        if ":" not in stripped:
            continue

        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip().strip("\"'")

        if not value:
            # Start of a nested mapping (e.g. ``metadata:``)
            current_key = key
            current_map = {}
        else:
            result[key] = value
            current_key = None

    # Flush trailing nested mapping
    if current_key is not None and current_map is not None:
        result[current_key] = current_map

    return result


def validate_skill_name(name: str) -> list[str]:
    """Validate a skill name against the AgentSkills.io spec.

    Returns a list of error strings (empty means valid).
    """
    errors: list[str] = []
    if not name:
        errors.append("name must not be empty")
        return errors
    if len(name) > 64:
        errors.append(f"name must be <= 64 chars, got {len(name)}")
    if not _SKILL_NAME_RE.match(name):
        errors.append("name must be lowercase alphanumeric + hyphens, no leading/trailing/consecutive hyphens")
    if "--" in name:
        errors.append("name must not contain consecutive hyphens")
    return errors


class SkillsLoader:
    """Loader for agent skills.

    Skills are markdown files (SKILL.md) that teach the agent how to use
    specific tools or perform certain tasks.  Supports both nanobot's native
    format and the AgentSkills.io open standard.
    """

    def __init__(self, workspace: Path, builtin_skills_dir: Path | None = None):
        self.workspace = workspace
        self.workspace_skills = workspace / "skills"
        self.builtin_skills = builtin_skills_dir or BUILTIN_SKILLS_DIR

    # ------------------------------------------------------------------
    # Listing & loading
    # ------------------------------------------------------------------

    def list_skills(self, filter_unavailable: bool = True) -> list[dict[str, str]]:
        """List all available skills.

        Returns list of dicts with 'name', 'path', 'source'.
        """
        skills: list[dict[str, str]] = []

        # Workspace skills (highest priority)
        if self.workspace_skills.exists():
            for skill_dir in self.workspace_skills.iterdir():
                if skill_dir.is_dir():
                    skill_file = self._find_skill_md(skill_dir)
                    if skill_file:
                        skills.append({"name": skill_dir.name, "path": str(skill_file), "source": "workspace"})

        # Built-in skills
        if self.builtin_skills and self.builtin_skills.exists():
            for skill_dir in self.builtin_skills.iterdir():
                if skill_dir.is_dir():
                    skill_file = self._find_skill_md(skill_dir)
                    if skill_file and not any(s["name"] == skill_dir.name for s in skills):
                        skills.append({"name": skill_dir.name, "path": str(skill_file), "source": "builtin"})

        if filter_unavailable:
            return [s for s in skills if self._check_requirements(self._get_skill_meta(s["name"]))]
        return skills

    def load_skill(self, name: str) -> str | None:
        """Load a skill by name.  Returns content or None."""
        # Check workspace first
        ws_dir = self.workspace_skills / name
        if ws_dir.is_dir():
            f = self._find_skill_md(ws_dir)
            if f:
                return f.read_text(encoding="utf-8")

        # Check built-in
        if self.builtin_skills:
            bi_dir = self.builtin_skills / name
            if bi_dir.is_dir():
                f = self._find_skill_md(bi_dir)
                if f:
                    return f.read_text(encoding="utf-8")

        return None

    def load_skills_for_context(self, skill_names: list[str]) -> str:
        """Load specific skills for inclusion in agent context."""
        parts = []
        for name in skill_names:
            content = self.load_skill(name)
            if content:
                content = self._strip_frontmatter(content)
                parts.append(f"### Skill: {name}\n\n{content}")
        return "\n\n---\n\n".join(parts) if parts else ""

    def build_skills_summary(self) -> str:
        """Build XML summary of all skills for progressive loading."""
        all_skills = self.list_skills(filter_unavailable=False)
        if not all_skills:
            return ""

        def esc(s: str) -> str:
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        lines = ["<skills>"]
        for s in all_skills:
            name = esc(s["name"])
            path = s["path"]
            desc = esc(self._get_skill_description(s["name"]))
            skill_meta = self._get_skill_meta(s["name"])
            available = self._check_requirements(skill_meta)

            lines.append(f'  <skill available="{str(available).lower()}">')
            lines.append(f"    <name>{name}</name>")
            lines.append(f"    <description>{desc}</description>")
            lines.append(f"    <location>{path}</location>")

            if not available:
                missing = self._get_missing_requirements(skill_meta)
                if missing:
                    lines.append(f"    <requires>{esc(missing)}</requires>")

            lines.append("  </skill>")
        lines.append("</skills>")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # GitHub skill installer
    # ------------------------------------------------------------------

    def install_from_github(
        self,
        owner: str,
        repo: str,
        skill_name: str | None = None,
        skills_dir: str = "skills",
        ref: str = "main",
    ) -> list[str]:
        """Install skills from a GitHub repository.

        Supports repos following the AgentSkills.io directory convention
        (``skills/<name>/SKILL.md``).

        Args:
            owner: GitHub user or org (e.g. ``huggingface``).
            repo: Repository name (e.g. ``skills``).
            skill_name: Install a single skill.  When *None*, all skills
                found under *skills_dir* are installed.
            skills_dir: Subdirectory in the repo that contains skills.
            ref: Git ref (branch / tag / commit).

        Returns:
            List of installed skill names.
        """
        api = f"https://api.github.com/repos/{owner}/{repo}"
        installed: list[str] = []

        if skill_name:
            names = [skill_name]
        else:
            # List skills directory
            names = self._github_list_skills(api, skills_dir, ref)

        for name in names:
            try:
                self._install_one_skill(api, skills_dir, name, ref)
                installed.append(name)
                logger.info("Installed skill %s from %s/%s", name, owner, repo)
            except Exception as exc:
                logger.warning("Failed to install skill %s: %s", name, exc)

        return installed

    def _github_list_skills(self, api: str, skills_dir: str, ref: str) -> list[str]:
        """List skill directories in a GitHub repo."""
        url = f"{api}/contents/{skills_dir}?ref={ref}"
        data = self._github_get_json(url)
        return [item["name"] for item in data if item.get("type") == "dir"]

    def _install_one_skill(self, api: str, skills_dir: str, name: str, ref: str) -> None:
        """Download and install a single skill from GitHub."""
        dest = self.workspace_skills / name
        dest.mkdir(parents=True, exist_ok=True)

        # Recursively download skill directory
        self._github_download_dir(api, f"{skills_dir}/{name}", ref, dest)

        # Validate after download
        skill_md = self._find_skill_md(dest)
        if not skill_md:
            shutil.rmtree(dest, ignore_errors=True)
            raise FileNotFoundError(f"No SKILL.md found in {name}")

    def _github_download_dir(self, api: str, path: str, ref: str, dest: Path) -> None:
        """Recursively download a directory from GitHub."""
        url = f"{api}/contents/{path}?ref={ref}"
        items = self._github_get_json(url)

        for item in items:
            item_dest = dest / item["name"]
            if item["type"] == "file":
                self._github_download_file(item["download_url"], item_dest)
            elif item["type"] == "dir":
                item_dest.mkdir(parents=True, exist_ok=True)
                self._github_download_dir(api, f"{path}/{item['name']}", ref, item_dest)

    @staticmethod
    def _github_download_file(url: str, dest: Path) -> None:
        """Download a single file from GitHub."""
        req = urllib.request.Request(url, headers={"User-Agent": "nanobot"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            dest.write_bytes(resp.read())

    @staticmethod
    def _github_get_json(url: str) -> Any:
        """GET a GitHub API endpoint and return parsed JSON."""
        req = urllib.request.Request(url, headers={
            "User-Agent": "nanobot",
            "Accept": "application/vnd.github.v3+json",
        })
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")
        if token:
            req.add_header("Authorization", f"token {token}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())

    # ------------------------------------------------------------------
    # Metadata helpers
    # ------------------------------------------------------------------

    def get_skill_metadata(self, name: str) -> dict | None:
        """Get metadata from a skill's frontmatter.

        Uses the enhanced parser that supports both nanobot's legacy
        ``key: value`` format and AgentSkills.io nested YAML.
        """
        content = self.load_skill(name)
        if not content:
            return None

        if content.startswith("---"):
            match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
            if match:
                return _parse_yaml_frontmatter(match.group(1))

        return None

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
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_skill_md(skill_dir: Path) -> Path | None:
        """Find SKILL.md (case-insensitive) in a directory."""
        for name in ("SKILL.md", "skill.md"):
            p = skill_dir / name
            if p.exists():
                return p
        return None

    def _get_skill_description(self, name: str) -> str:
        """Get the description of a skill from its frontmatter."""
        meta = self.get_skill_metadata(name)
        if meta and meta.get("description"):
            return meta["description"]
        return name

    def _strip_frontmatter(self, content: str) -> str:
        """Remove YAML frontmatter from markdown content."""
        if content.startswith("---"):
            match = re.match(r"^---\n.*?\n---\n", content, re.DOTALL)
            if match:
                return content[match.end():].strip()
        return content

    def _parse_nanobot_metadata(self, raw: str | dict) -> dict:
        """Parse skill metadata from frontmatter.

        Handles both nanobot's legacy JSON-string format and
        AgentSkills.io's native dict format.
        """
        if isinstance(raw, dict):
            # AgentSkills.io style: metadata is already a dict
            return raw.get("nanobot", raw.get("openclaw", raw))
        if isinstance(raw, str) and raw:
            try:
                data = json.loads(raw)
                return data.get("nanobot", data.get("openclaw", {})) if isinstance(data, dict) else {}
            except (json.JSONDecodeError, TypeError):
                pass
        return {}

    def _check_requirements(self, skill_meta: dict) -> bool:
        """Check if skill requirements are met (bins, env vars, compatibility)."""
        requires = skill_meta.get("requires", {})
        if isinstance(requires, dict):
            for b in requires.get("bins", []):
                if not shutil.which(b):
                    return False
            for env in requires.get("env", []):
                if not os.environ.get(env):
                    return False
        return True

    def _get_missing_requirements(self, skill_meta: dict) -> str:
        """Get a description of missing requirements."""
        missing = []
        requires = skill_meta.get("requires", {})
        if isinstance(requires, dict):
            for b in requires.get("bins", []):
                if not shutil.which(b):
                    missing.append(f"CLI: {b}")
            for env in requires.get("env", []):
                if not os.environ.get(env):
                    missing.append(f"ENV: {env}")
        return ", ".join(missing)

    def _get_skill_meta(self, name: str) -> dict:
        """Get nanobot metadata for a skill."""
        meta = self.get_skill_metadata(name) or {}
        return self._parse_nanobot_metadata(meta.get("metadata", ""))


