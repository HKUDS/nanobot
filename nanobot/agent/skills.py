"""Skills loader for agent capabilities."""

import json
import os
import re
import shutil
from pathlib import Path

from nanobot.agent.skill_validation import validate_skill_directory_name, validate_skill_md_content
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

    def list_skills(self, filter_unavailable: bool = True) -> list[dict[str, str]]:
        """
        List all available skills.

        Args:
            filter_unavailable: If True, filter out skills with unmet requirements.

        Returns:
            List of skill info dicts with 'name', 'path', 'source'.
        """
        skills = self._skill_entries_from_dir(self.workspace_skills, "workspace")
        workspace_names = {entry["name"] for entry in skills}
        if self.builtin_skills and self.builtin_skills.exists():
            skills.extend(
                self._skill_entries_from_dir(self.builtin_skills, "builtin", skip_names=workspace_names)
            )

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
        roots = [self.workspace_skills]
        if self.builtin_skills:
            roots.append(self.builtin_skills)
        for root in roots:
            path = root / name / "SKILL.md"
            if path.exists():
                return path.read_text(encoding="utf-8")
        return None

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

        This is used for progressive loading - the agent should load the full
        SKILL.md via ``manage_skill(operation=\"get\")``, not ``read_file``.

        Args:
            exclude: Set of skill names to omit from the summary.

        Returns:
            Markdown-formatted skills summary.
        """
        all_skills = self.list_skills(filter_unavailable=False)
        if not all_skills:
            return ""

        lines: list[str] = []
        for entry in all_skills:
            skill_name = entry["name"]
            if exclude and skill_name in exclude:
                continue
            meta = self._get_skill_meta(skill_name)
            available = self._check_requirements(meta)
            desc = self._get_skill_description(skill_name)
            if available:
                lines.append(f"- **{skill_name}** — {desc}  `{entry['path']}`")
            else:
                missing = self._get_missing_requirements(meta)
                suffix = f" (unavailable: {missing})" if missing else " (unavailable)"
                lines.append(f"- **{skill_name}** — {desc}{suffix}  `{entry['path']}`")
        return "\n".join(lines)

    def _get_missing_requirements(self, skill_meta: dict) -> str:
        """Get a description of missing requirements."""
        requires = skill_meta.get("requires", {})
        required_bins = requires.get("bins", [])
        required_env_vars = requires.get("env", [])
        return ", ".join(
            [f"CLI: {command_name}" for command_name in required_bins if not shutil.which(command_name)]
            + [f"ENV: {env_name}" for env_name in required_env_vars if not os.environ.get(env_name)]
        )

    def _get_skill_description(self, name: str) -> str:
        """Get the description of a skill from its frontmatter."""
        meta = self.get_skill_metadata(name)
        if meta and meta.get("description"):
            return meta["description"]
        return name  # Fallback to skill name

    def describe_skill(self, name: str) -> str:
        """Public alias for skill list UIs and tools."""
        return self._get_skill_description(name)

    def skill_availability(self, name: str) -> tuple[bool, str]:
        """Return (requirements_met, missing_requirements_text)."""
        meta = self._get_skill_meta(name)
        if self._check_requirements(meta):
            return True, ""
        return False, self._get_missing_requirements(meta)

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
        content = self.load_skill(name)
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

    def resolve_skill_location(self, name: str) -> dict[str, str] | None:
        """Return ``name``, ``source`` (workspace|builtin), ``path``, ``skill_dir`` for SKILL.md, or ``None``."""
        ws_file = self.workspace_skills / name / "SKILL.md"
        if ws_file.is_file():
            return {
                "name": name,
                "source": "workspace",
                "path": str(ws_file.resolve()),
                "skill_dir": str(ws_file.parent.resolve()),
            }
        if self.builtin_skills and self.builtin_skills.exists():
            bi_file = self.builtin_skills / name / "SKILL.md"
            if bi_file.is_file():
                return {
                    "name": name,
                    "source": "builtin",
                    "path": str(bi_file.resolve()),
                    "skill_dir": str(bi_file.parent.resolve()),
                }
        return None

    def create_workspace_skill(self, name: str, content: str) -> None:
        """Create ``workspace/skills/<name>/SKILL.md`` (fails if directory or file already exists)."""
        err = validate_skill_directory_name(name)
        if err:
            raise ValueError(err)
        skill_dir = self.workspace_skills / name
        if skill_dir.exists():
            raise ValueError(f"Skill '{name}' already exists under workspace skills")
        v_errs = validate_skill_md_content(content, folder_name=name)
        if v_errs:
            raise ValueError("; ".join(v_errs))
        self.workspace_skills.mkdir(parents=True, exist_ok=True)
        skill_dir.mkdir(parents=False)
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")

    def update_workspace_skill(self, name: str, content: str) -> None:
        """Overwrite workspace ``SKILL.md`` only; builtin-only skills are read-only."""
        err = validate_skill_directory_name(name)
        if err:
            raise ValueError(err)
        ws_file = self.workspace_skills / name / "SKILL.md"
        if ws_file.is_file():
            v_errs = validate_skill_md_content(content, folder_name=name)
            if v_errs:
                raise ValueError("; ".join(v_errs))
            ws_file.write_text(content, encoding="utf-8")
            return
        if self.resolve_skill_location(name) is not None:
            raise PermissionError(
                f"Skill '{name}' is built-in (read-only). Copy it to workspace/skills/ first or use a new name."
            )
        raise ValueError(f"Skill '{name}' not found")

    def delete_workspace_skill(self, name: str) -> None:
        """Remove ``workspace/skills/<name>`` recursively; builtin-only skills cannot be deleted."""
        err = validate_skill_directory_name(name)
        if err:
            raise ValueError(err)
        skill_dir = self.workspace_skills / name
        ws_md = skill_dir / "SKILL.md"
        if ws_md.is_file():
            shutil.rmtree(skill_dir)
            return
        if self.builtin_skills and (self.builtin_skills / name / "SKILL.md").is_file():
            raise PermissionError(
                f"Skill '{name}' is built-in (read-only); only workspace skills can be deleted."
            )
        raise ValueError(f"Skill '{name}' not found")
