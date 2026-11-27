"""Skill discovery locations, in precedence order for a single project."""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NamedTuple

from loguru import logger

from nanobot.agent.skill_metadata import parse_skill_metadata, valid_skill_metadata
from nanobot.security.workspace_policy import is_path_within


class SkillCandidate(NamedTuple):
    name: str
    path: Path
    content: str | None = None
    metadata: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class SkillSource:
    key: Literal["project", "workspace", "shared", "plugin", "builtin"]
    label: str
    root: Path

    def candidates(self) -> Iterator[SkillCandidate]:
        if self.key == "plugin":
            from nanobot.agent.plugins import enabled_agent_plugin_skill_documents

            for doc in enabled_agent_plugin_skill_documents(self.root.parent):
                yield SkillCandidate(doc.name, doc.path, doc.content, doc.metadata)
            return

        standard = self.key in {"project", "shared"}
        try:
            if self.key == "shared" and self.root.resolve() != self.root:
                logger.warning("Ignoring redirected user skills directory: {}", self.root)
                return
            children = sorted(self.root.iterdir())
        except (FileNotFoundError, NotADirectoryError):
            return
        except (OSError, RuntimeError) as exc:
            logger.warning("Cannot scan skills in {}: {}", self.root, exc)
            return
        for package in children:
            path = package / "SKILL.md"
            try:
                if not path.is_file():
                    continue
                if not standard:
                    yield SkillCandidate(package.name, path)
                    continue
                target = path.resolve(strict=True)
                if not is_path_within(target, self.root):
                    logger.warning("Ignoring skill outside {}: {}", self.root, path)
                    continue
                content = target.read_text(encoding="utf-8")
                metadata = parse_skill_metadata(content)
                if metadata is None or not valid_skill_metadata(metadata, package.name):
                    logger.warning("Ignoring skill with invalid name or description: {}", path)
                    continue
                yield SkillCandidate(package.name, path, content, metadata)
            except (OSError, UnicodeError, RuntimeError) as exc:
                logger.warning("Cannot load skill {}: {}", path, exc)


def ordered_sources(project: Path, workspace: Path, shared: Path, builtin: Path) -> Iterator[SkillSource]:
    project_skills = project / ".agents" / "skills"
    if is_path_within(project_skills, project):
        yield SkillSource("project", "Project skills", project_skills)
    yield SkillSource("workspace", "Workspace skills", workspace / "skills")
    yield SkillSource("shared", "Shared skills", shared)
    yield SkillSource("plugin", "Agent Plugin skills", workspace / "plugins")
    yield SkillSource("builtin", "Built-in skills", builtin)
