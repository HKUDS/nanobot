import json
import os
import re
import shutil
from collections.abc import Collection, Generator, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from loguru import logger

from nanobot.agent.skill_metadata import (
    BUILTIN_SKILLS_DIR as BUILTIN_SKILLS_DIR,
)
from nanobot.agent.skill_metadata import (
    SKILL_FRONTMATTER as _STRIP_SKILL_FRONTMATTER,
)
from nanobot.agent.skill_metadata import (
    parse_skill_metadata as parse_skill_metadata,
)
from nanobot.agent.skill_sources import SkillSource, ordered_sources
from nanobot.config import paths
from nanobot.context_sources import record_source
from nanobot.runtime_context import RuntimeContextBlock

_SKILL_REFERENCE = re.compile(r"(?<![\w$])\$([A-Za-z0-9_-]+)")


@dataclass
class _SkillSnapshot:
    entries: dict[str, dict[str, str]] | None = None
    aliases: dict[str, str] | None = None
    documents: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, dict[str, object] | None] = field(default_factory=dict)
    binaries: dict[str, bool] = field(default_factory=dict)


class SkillsLoader:
    """
    Loader for agent skills.

    Skills are markdown files (SKILL.md) that teach the agent how to use
    specific tools or perform certain tasks.
    """

    def __init__(
        self, workspace: Path, builtin_skills_dir: Path | None = None, disabled_skills: set[str] | None = None,
        *, project_workspace: Path | None = None,
    ):
        self.workspace = workspace
        self.project_workspace = project_workspace or workspace
        self.shared_skills = paths.get_shared_skills_dir()
        self.builtin_skills = builtin_skills_dir or BUILTIN_SKILLS_DIR
        self.disabled_skills: set[str] = disabled_skills if disabled_skills is not None else set()
        self._snapshot: ContextVar[_SkillSnapshot | None] = ContextVar("skill_snapshot", default=None)

    def for_project(self, project_workspace: Path) -> "SkillsLoader":
        if project_workspace == self.project_workspace:
            return self
        return SkillsLoader(self.workspace, self.builtin_skills, self.disabled_skills, project_workspace=project_workspace)

    def _sources(self) -> Iterator[SkillSource]:
        return ordered_sources(self.project_workspace, self.workspace, self.shared_skills, self.builtin_skills)

    def local_package_dirs(self, name: str) -> Iterator[Path]:
        """Package paths under the direct directory sources (not plugin-managed packages)."""
        return (source.root / name for source in self._sources() if source.key != "plugin")

    @contextmanager
    def snapshot(self) -> Generator[None, None, None]:
        """Reuse discovery, documents, metadata, and CLI checks until this scope exits."""
        if self._snapshot.get() is not None:
            yield
            return
        token = self._snapshot.set(_SkillSnapshot())
        try:
            yield
        finally:
            self._snapshot.reset(token)

    def _skill_aliases(self) -> dict[str, str]:
        from nanobot.apps.cli import CliAppManager

        snapshot = self._snapshot.get()
        if snapshot is not None and snapshot.aliases is not None:
            return snapshot.aliases
        try:
            aliases = CliAppManager(workspace=self.workspace).installed_skill_aliases()
        except OSError:
            aliases = {}
        if snapshot is not None:
            snapshot.aliases = aliases
        return aliases

    def list_skills(
        self, filter_unavailable: bool = True, *, exclude: Collection[str] = (),
    ) -> list[dict[str, str]]:
        """
        List all available skills.

        Args:
            filter_unavailable: If True, filter out skills with unmet requirements.

        Returns:
            List of skill info dicts with 'name', 'path', 'source'.
        """
        with self.snapshot():
            return [
                skill for name, skill in self._entries().items()
                if name not in exclude and (not filter_unavailable or self._check_requirements(self._get_skill_meta(name)))
            ]

    def _entries(self) -> dict[str, dict[str, str]]:
        snapshot = self._snapshot.get()
        assert snapshot is not None
        if snapshot.entries is None:
            snapshot.entries = self._discover_skills()
        return snapshot.entries

    def _discover_skills(self) -> dict[str, dict[str, str]]:
        disabled = set(self.disabled_skills)
        if disabled:
            for legacy, canonical in self._skill_aliases().items():
                if legacy in disabled or canonical in disabled:
                    disabled.update((legacy, canonical))
        entries: dict[str, dict[str, str]] = {}
        seen_paths: set[Path] = set()
        snapshot = self._snapshot.get()
        for source in self._sources():
            for skill in source.candidates():
                if skill.name in disabled:
                    continue
                if skill.name in entries:
                    logger.debug("Skill {} shadows {}", entries[skill.name]["path"], skill.path)
                    continue
                target = skill.path.resolve()
                if target in seen_paths:
                    continue
                seen_paths.add(target)
                entries[skill.name] = {"name": skill.name, "path": str(skill.path), "source": source.key}
                if snapshot is not None and skill.content is not None:
                    snapshot.documents[skill.name] = skill.content
                    snapshot.metadata[skill.name] = skill.metadata
        return entries

    def load_skill(self, name: str) -> str | None:
        """
        Load a skill by name.

        Args:
            name: Skill name (directory name).

        Returns:
            Skill content or None if not found.
        """
        with self.snapshot():
            return self._load_skill(name)

    def _load_skill(self, name: str, *, for_context: bool = False) -> str | None:
        entries = self._entries()
        resolved = name if name in entries else self._skill_aliases().get(name, name)
        entry = entries.get(resolved)
        if entry is None:
            return None
        snapshot = self._snapshot.get()
        if snapshot is not None and resolved in snapshot.documents:
            content = snapshot.documents[resolved]
        else:
            content = Path(entry["path"]).read_text(encoding="utf-8")
            if snapshot is not None:
                snapshot.documents[resolved] = content
        if for_context:
            content = self._strip_frontmatter(content)
            path = Path(entry["path"])
            record_source(path, content)
            if entry["source"] in {"project", "shared"}:
                content = f"Skill directory: `{path.parent}`\n\n{content}"
        return content

    def load_skills_for_context(self, skill_names: list[str]) -> str:
        """
        Load specific skills for inclusion in agent context.

        Args:
            skill_names: List of skill names to load.

        Returns:
            Formatted skills content.
        """
        with self.snapshot():
            parts = [
                f"### Skill: {name}\n\n{content}"
                for name in skill_names
                if (content := self._load_skill(name, for_context=True))
            ]
        return "\n\n---\n\n".join(parts)

    def get_explicitly_invoked_skills(self, text: str, *, exclude: Collection[str] = ()) -> list[str]:
        """Resolve ``$skill-name`` references to enabled, available skills."""
        references = list(_SKILL_REFERENCE.finditer(text))
        if not references:
            return []
        available = {
            entry["name"]
            for entry in self.list_skills(filter_unavailable=True, exclude=exclude)
        }
        aliases = self._skill_aliases()
        invoked: list[str] = []
        for match in references:
            requested = match.group(1)
            name = requested if requested in available else aliases.get(requested, requested)
            if name in available and name not in invoked:
                invoked.append(name)
        return invoked

    def build_explicit_skill_runtime_context(
        self,
        text: str,
        *,
        exclude: Collection[str] = (),
    ) -> RuntimeContextBlock | None:
        """Load non-always skills explicitly invoked by the current message."""
        with self.snapshot():
            return self._build_explicit_skill_runtime_context(text, exclude)

    def _build_explicit_skill_runtime_context(
        self, text: str, exclude: Collection[str],
    ) -> RuntimeContextBlock | None:
        skill_names = self.get_explicitly_invoked_skills(text, exclude=exclude)
        if not skill_names:
            return None
        always_active = set(self.get_always_skills(exclude=exclude))
        skill_names = [name for name in skill_names if name not in always_active]
        content = self.load_skills_for_context(skill_names)
        if not content:
            return None
        return RuntimeContextBlock(
            source="explicit_skills",
            content=(
                "[Active Skills — instructions for this user turn]\n"
                f"{content}\n"
                "[/Active Skills]"
            ),
        )

    def build_skills_summary(self, exclude: set[str] | None = None) -> str:
        """Describe available skills and where to read them from the selected project."""
        with self.snapshot():
            return self._build_skills_summary(exclude)

    def _build_skills_summary(self, exclude: set[str] | None) -> str:
        all_skills = self.list_skills(filter_unavailable=True, exclude=exclude or ())
        if not all_skills:
            return ""

        agent_workspace = self.workspace.expanduser().resolve()
        project_workspace = self.project_workspace.expanduser().resolve()
        use_relative_roots = project_workspace == agent_workspace
        sections: list[str] = []
        for source in self._sources():
            root = source.root
            entries = [entry for entry in all_skills if entry["source"] == source.key]
            if not entries:
                continue

            resolved_root = root.expanduser().resolve()
            # Directory tools need the real built-in root; only read_file resolves
            # workspace-relative skills/<name>/... aliases to bundled resources.
            if use_relative_roots and source.key in {"workspace", "plugin"}:
                display_root = root.relative_to(self.workspace)
            else:
                display_root = resolved_root
            lines = [f"### {source.label} (`{display_root}`)"]
            for entry in entries:
                skill_name = entry["name"]
                record_source(Path(entry["path"]), "", loaded=False)
                desc = self.get_skill_description(skill_name)
                relative_path = Path(entry["path"]).relative_to(root).as_posix()
                lines.append(f"- **{skill_name}** — {desc}  `{relative_path}`")
            sections.append("\n".join(lines))
        return "\n\n".join(sections)

    @staticmethod
    def _requirement_lists(skill_meta: dict[str, Any]) -> tuple[list[str], list[str]]:
        """Return (bins, env) lists from skill metadata, tolerating null/wrong shapes."""
        requires = cast(dict[str, Any], skill_meta.get("requires") or {})
        if not isinstance(skill_meta.get("requires") or {}, dict):
            return [], []
        bins_raw: object = requires.get("bins") or []
        env_raw: object = requires.get("env") or []
        bins = [value for value in cast(list[object], bins_raw) if isinstance(value, str) and value.strip()] if isinstance(bins_raw, list) else []
        env = [value for value in cast(list[object], env_raw) if isinstance(value, str) and value.strip()] if isinstance(env_raw, list) else []
        return bins, env

    def _get_missing_requirements(self, skill_meta: dict[str, Any]) -> str:
        required_bins, required_env_vars = self._requirement_lists(skill_meta)
        return ", ".join(
            [f"CLI: {command_name}" for command_name in required_bins if not self._binary_available(command_name)]
            + [f"ENV: {env_name}" for env_name in required_env_vars if not os.environ.get(env_name)]
        )

    def get_skill_availability(self, name: str) -> tuple[bool, str]:
        """Return whether a skill can run and why not when it cannot."""
        meta = self._get_skill_meta(name)
        available = self._check_requirements(meta)
        return available, "" if available else self._get_missing_requirements(meta)

    def get_skill_requirements(self, name: str) -> dict[str, list[str]]:
        """Return explicit command/env requirements and currently missing entries."""
        bins, env = self._requirement_lists(self._get_skill_meta(name))
        return {
            "bins": bins,
            "env": env,
            "missing_bins": [value for value in bins if not self._binary_available(value)],
            "missing_env": [value for value in env if not os.environ.get(value)],
        }

    def get_skill_description(self, name: str) -> str:
        """Get the description of a skill from its frontmatter."""
        meta = self.get_skill_metadata(name)
        description = meta.get("description") if meta else None
        if isinstance(description, str) and description:
            return description
        return name

    def _strip_frontmatter(self, content: str) -> str:
        if not content.startswith("---"):
            return content
        match = _STRIP_SKILL_FRONTMATTER.match(content)
        if match:
            return content[match.end():].strip()
        return content

    def _parse_nanobot_metadata(self, raw: object) -> dict[str, Any]:
        if isinstance(raw, dict):
            data = cast(dict[str, Any], raw)
        elif isinstance(raw, str):
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return {}
        else:
            return {}
        if not isinstance(data, dict):
            return {}
        data_object = cast(dict[str, Any], data)
        payload = data_object.get("nanobot", data_object.get("openclaw", {}))
        return cast(dict[str, Any], payload) if isinstance(payload, dict) else {}

    def _check_requirements(self, skill_meta: dict[str, Any]) -> bool:
        required_bins, required_env_vars = self._requirement_lists(skill_meta)
        return all(self._binary_available(cmd) for cmd in required_bins) and all(
            os.environ.get(var) for var in required_env_vars
        )

    def _binary_available(self, command: str) -> bool:
        snapshot = self._snapshot.get()
        if snapshot is not None and command in snapshot.binaries:
            return snapshot.binaries[command]
        available = shutil.which(command) is not None
        if snapshot is not None:
            snapshot.binaries[command] = available
        return available

    def _get_skill_meta(self, name: str) -> dict[str, Any]:
        raw_meta = self.get_skill_metadata(name) or {}
        return self._parse_nanobot_metadata(raw_meta.get("metadata"))

    def get_always_skills(self, *, exclude: Collection[str] = ()) -> list[str]:
        """Get skills marked as always=true that meet requirements."""
        with self.snapshot():
            return self._get_always_skills(exclude)

    def _get_always_skills(self, exclude: Collection[str]) -> list[str]:
        return [
            entry["name"]
            for entry in self.list_skills(filter_unavailable=True, exclude=exclude)
            if (meta := self.get_skill_metadata(entry["name"]) or {})
            and (
                self._parse_nanobot_metadata(meta.get("metadata")).get("always")
                or meta.get("always")
            )
        ]

    def get_skill_metadata(self, name: str) -> dict[str, object] | None:
        """
        Get metadata from a skill's frontmatter.

        Args:
            name: Skill name.

        Returns:
            Metadata dict or None.
        """
        snapshot = self._snapshot.get()
        if snapshot is not None and name in snapshot.metadata:
            return snapshot.metadata[name]
        metadata = parse_skill_metadata(self.load_skill(name) or "")
        if snapshot is not None:
            snapshot.metadata[name] = metadata
        return metadata
