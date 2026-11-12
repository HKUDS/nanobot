"""Skill resource locations and validated YAML identity metadata."""

import re
from pathlib import Path
from typing import cast

import yaml

BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "skills"


SKILL_FRONTMATTER = re.compile(
    r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?",
    re.DOTALL,
)


SKILL_NAME = re.compile(r"^(?!.*--)[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


def parse_skill_metadata(content: str) -> dict[str, object] | None:
    """Parse a skill document's YAML frontmatter."""
    if not (match := SKILL_FRONTMATTER.match(content)):
        return None
    try:
        parsed = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None
    if not isinstance(parsed, dict):
        return None
    return {str(key): value for key, value in cast(dict[object, object], parsed).items()}


def valid_skill_metadata(metadata: dict[str, object], name: str) -> bool:
    """Return whether metadata satisfies the Agent Skills identity contract."""
    description = metadata.get("description")
    return (
        metadata.get("name") == name
        and len(name) <= 64
        and SKILL_NAME.fullmatch(name) is not None
        and isinstance(description, str)
        and 1 <= len(description.strip()) <= 1024
    )
