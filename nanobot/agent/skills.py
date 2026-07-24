"""Skills loader for agent capabilities."""

import json
import os
import re
import shutil
from pathlib import Path

import yaml

# Default builtin skills directory (relative to this file)
BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "skills"

# Opening ---, YAML body (group 1), closing --- on its own line; supports CRLF.
_STRIP_SKILL_FRONTMATTER = re.compile(
    r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?",
    re.DOTALL,
)


class SkillsLoader:
    """
    Loader for agent skills.

    Skills are markdown files (SKILL.md) that teach the agent how to use
    specific tools or perform certain tasks.
    """

    def __init__(self, workspace: Path, builtin_skills_dir: Path | None = None, disabled_skills: set[str] | None = None):
        self.workspace = workspace
        self.workspace_skills = workspace / "skills"
        self.builtin_skills = builtin_skills_dir or BUILTIN_SKILLS_DIR
        self.disabled_skills = disabled_skills or set()
        self._entries_cache: list[dict[str, str]] | None = None
        self._entries_snapshot: tuple[tuple[str, str, int, int], ...] | None = None
        self._metadata_cache: dict[str, tuple[tuple[str, int, int], dict | None]] = {}

    def reload(self) -> None:
        """Clear skill caches so the next lookup reloads from disk."""
        self._entries_cache = None
        self._entries_snapshot = None
        self._metadata_cache.clear()

    def _skill_entries_from_dir(self, base: Path, source: str, *, skip_names: set[str] | None = None) -> list[dict[str, str]]:
        if not base.exists():
            return []
        entries: list[dict[str, str]] = []
        for skill_dir in base.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            name = skill_dir.name
            if skip_names is not None and name in skip_names:
                continue
            entries.append({"name": name, "path": str(skill_file), "source": source})
        return entries

    def _list_skill_entries_cached(self) -> list[dict[str, str]]:
        snapshot = self._skill_entries_snapshot()
        if self._entries_cache is not None and snapshot == self._entries_snapshot:
            return [dict(entry) for entry in self._entries_cache]

        skills = self._skill_entries_from_dir(self.workspace_skills, "workspace")
        workspace_names = {entry["name"] for entry in skills}
        if self.builtin_skills and self.builtin_skills.exists():
            skills.extend(
                self._skill_entries_from_dir(
                    self.builtin_skills,
                    "builtin",
                    skip_names=workspace_names,
                )
            )

        self._entries_snapshot = snapshot
        self._entries_cache = [dict(entry) for entry in skills]
        return [dict(entry) for entry in skills]

    def _skill_entries_snapshot(self) -> tuple[tuple[str, str, int, int], ...]:
        items: list[tuple[str, str, int, int]] = []
        roots = [("workspace", self.workspace_skills)]
        if self.builtin_skills:
            roots.append(("builtin", self.builtin_skills))

        for source, base in roots:
            if not base.exists():
                continue
            try:
                skill_dirs = sorted(base.iterdir(), key=lambda item: item.name)
            except OSError:
                continue
            for skill_dir in skill_dirs:
                if not skill_dir.is_dir():
                    continue
                skill_file = skill_dir / "SKILL.md"
                signature = self._skill_file_signature(skill_file)
                if signature is None:
                    continue
                resolved_path, mtime_ns, size = signature
                items.append((source, resolved_path, mtime_ns, size))
        return tuple(items)

    def _skill_file_signature(self, path: Path) -> tuple[str, int, int] | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        if not path.is_file():
            return None
        return (str(path.resolve()), stat.st_mtime_ns, stat.st_size)

    def _skill_file_for_name(self, name: str) -> Path | None:
        roots = [self.workspace_skills]
        if self.builtin_skills:
            roots.append(self.builtin_skills)
        for root in roots:
            path = root / name / "SKILL.md"
            if path.is_file():
                return path
        return None

    def list_skills(self, filter_unavailable: bool = True) -> list[dict[str, str]]:
        """
        List all available skills.

        Args:
            filter_unavailable: If True, filter out skills with unmet requirements.

        Returns:
            List of skill info dicts with 'name', 'path', 'source'.
        """
        skills = self._list_skill_entries_cached()

        if self.disabled_skills:
            skills = [s for s in skills if s["name"] not in self.disabled_skills]

        if filter_unavailable:
            return [skill for skill in skills if self._check_requirements(self._get_skill_meta(skill["name"]))]
        return skills

    def load_skill(self, name: str) -> str | None:
        """
        Load a skill by name.

        Args:
            name: Skill name (directory name).

        Returns:
            Skill content or None if not found.
        """
        path = self._skill_file_for_name(name)
        if path is None:
            return None
        return path.read_text(encoding="utf-8")

    def load_skills_for_context(self, skill_names: list[str]) -> str:
        """
        Load specific skills for inclusion in agent context.

        Args:
            skill_names: List of skill names to load.

        Returns:
            Formatted skills content.
        """
        parts = [
            f"### Skill: {name}\n\n{self._strip_frontmatter(markdown)}"
            for name in skill_names
            if (markdown := self.load_skill(name))
        ]
        return "\n\n---\n\n".join(parts)

    def build_skills_summary(self, exclude: set[str] | None = None) -> str:
        """
        Build a summary of all skills (name, description, path, availability).

        This is used for progressive loading - the agent can read the full
        skill content using read_file when needed.

        Args:
            exclude: Set of skill names to omit from the summary.

        Returns:
            Markdown-formatted skills summary.
        """
        all_skills = self.list_skills(filter_unavailable=False)
        if not all_skills:
            return ""

        sections: list[str] = []
        groups = (
            ("Workspace skills", "workspace", self.workspace_skills),
            ("Built-in skills", "builtin", self.builtin_skills),
        )
        for label, source, root in groups:
            entries = [
                entry
                for entry in all_skills
                if entry["source"] == source and (not exclude or entry["name"] not in exclude)
            ]
            if not entries:
                continue

            lines = [f"### {label} (`{root.expanduser().resolve()}`)"]
            for entry in entries:
                skill_name = entry["name"]
                meta = self._get_skill_meta(skill_name)
                available = self._check_requirements(meta)
                desc = self._get_skill_description(skill_name)
                suffix = ""
                if not available:
                    missing = self._get_missing_requirements(meta)
                    suffix = f" (unavailable: {missing})" if missing else " (unavailable)"
                relative_path = Path(entry["path"]).relative_to(root).as_posix()
                lines.append(f"- **{skill_name}** — {desc}{suffix}  `{relative_path}`")
            sections.append("\n".join(lines))
        return "\n\n".join(sections)

    def _get_missing_requirements(self, skill_meta: dict) -> str:
        """Get a description of missing requirements."""
        requires = skill_meta.get("requires", {})
        required_bins = requires.get("bins", [])
        required_env_vars = requires.get("env", [])
        return ", ".join(
            [f"CLI: {command_name}" for command_name in required_bins if not shutil.which(command_name)]
            + [f"ENV: {env_name}" for env_name in required_env_vars if not os.environ.get(env_name)]
        )

    def get_skill_availability(self, name: str) -> tuple[bool, str]:
        """Return whether a skill can run and why not when it cannot."""
        meta = self._get_skill_meta(name)
        available = self._check_requirements(meta)
        return available, "" if available else self._get_missing_requirements(meta)

    def get_skill_requirements(self, name: str) -> dict[str, list[str]]:
        """Return explicit command/env requirements and currently missing entries."""
        requires = self._get_skill_meta(name).get("requires", {})
        bins = [str(value) for value in requires.get("bins", [])]
        env = [str(value) for value in requires.get("env", [])]
        return {
            "bins": bins,
            "env": env,
            "missing_bins": [value for value in bins if not shutil.which(value)],
            "missing_env": [value for value in env if not os.environ.get(value)],
        }

    def _get_skill_description(self, name: str) -> str:
        """Get the description of a skill from its frontmatter."""
        meta = self.get_skill_metadata(name)
        if meta and meta.get("description"):
            return meta["description"]
        return name  # Fallback to skill name

    def _strip_frontmatter(self, content: str) -> str:
        """Remove YAML frontmatter from markdown content."""
        if not content.startswith("---"):
            return content
        match = _STRIP_SKILL_FRONTMATTER.match(content)
        if match:
            return content[match.end():].strip()
        return content

    def _parse_nanobot_metadata(self, raw: object) -> dict:
        """Extract nanobot/openclaw metadata from a frontmatter field.

        ``raw`` may be a dict (already parsed by yaml.safe_load) or a JSON str.
        """
        if isinstance(raw, dict):
            data = raw
        elif isinstance(raw, str):
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return {}
        else:
            return {}
        if not isinstance(data, dict):
            return {}
        payload = data.get("nanobot", data.get("openclaw", {}))
        return payload if isinstance(payload, dict) else {}

    def _check_requirements(self, skill_meta: dict) -> bool:
        """Check if skill requirements are met (bins, env vars)."""
        requires = skill_meta.get("requires", {})
        required_bins = requires.get("bins", [])
        required_env_vars = requires.get("env", [])
        return all(shutil.which(cmd) for cmd in required_bins) and all(
            os.environ.get(var) for var in required_env_vars
        )

    def _get_skill_meta(self, name: str) -> dict:
        """Get nanobot metadata for a skill (cached in frontmatter)."""
        raw_meta = self.get_skill_metadata(name) or {}
        return self._parse_nanobot_metadata(raw_meta.get("metadata"))

    def get_always_skills(self) -> list[str]:
        """Get skills marked as always=true that meet requirements."""
        return [
            entry["name"]
            for entry in self.list_skills(filter_unavailable=True)
            if (meta := self.get_skill_metadata(entry["name"]) or {})
            and (
                self._parse_nanobot_metadata(meta.get("metadata")).get("always")
                or meta.get("always")
            )
        ]

    def get_skill_metadata(self, name: str) -> dict | None:
        """
        Get metadata from a skill's frontmatter.

        Args:
            name: Skill name.

        Returns:
            Metadata dict or None.
        """
        path = self._skill_file_for_name(name)
        if path is None:
            return None
        signature = self._skill_file_signature(path)
        if signature is None:
            return None
        cached = self._metadata_cache.get(name)
        if cached is not None and cached[0] == signature:
            return cached[1]

        content = path.read_text(encoding="utf-8")
        metadata = self._parse_skill_frontmatter(content)
        self._metadata_cache[name] = (signature, metadata)
        return metadata

    def _parse_skill_frontmatter(self, content: str) -> dict | None:
        if not content or not content.startswith("---"):
            return None
        match = _STRIP_SKILL_FRONTMATTER.match(content)
        if not match:
            return None
        try:
            parsed = yaml.safe_load(match.group(1))
        except yaml.YAMLError:
            return None
        if not isinstance(parsed, dict):
            return None
        # yaml.safe_load returns native types (int, bool, list, etc.);
        # keep values as-is so downstream consumers get correct types.
        metadata: dict[str, object] = {}
        for key, value in parsed.items():
            metadata[str(key)] = value
        return metadata
