"""Shared validation for nanobot skills (SKILL.md + optional directory layout).

Used by :class:`~nanobot.agent.skills.SkillsLoader`, :class:`~nanobot.agent.tools.skills.ManageSkillTool`,
and the ``skill-creator`` CLI (``quick_validate.py``).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

try:
    import yaml
except ModuleNotFoundError:
    yaml = None

MAX_SKILL_NAME_LENGTH = 64
ALLOWED_FRONTMATTER_KEYS = frozenset(
    {
        "name",
        "description",
        "metadata",
        "always",
        "license",
        "allowed-tools",
    }
)
ALLOWED_RESOURCE_DIRS = frozenset({"scripts", "references", "assets"})
PLACEHOLDER_MARKERS = ("[todo", "todo:")


def _extract_frontmatter(content: str) -> Optional[str]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i])
    return None


def _parse_simple_frontmatter(frontmatter_text: str) -> Optional[dict[str, str]]:
    """Fallback parser for simple frontmatter when PyYAML is unavailable."""
    parsed: dict[str, str] = {}
    current_key: Optional[str] = None
    multiline_key: Optional[str] = None

    for raw_line in frontmatter_text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        is_indented = raw_line[:1].isspace()
        if is_indented:
            if current_key is None:
                return None
            current_value = parsed[current_key]
            parsed[current_key] = f"{current_value}\n{stripped}" if current_value else stripped
            continue

        if ":" not in stripped:
            return None

        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            return None

        if value in {"|", ">"}:
            parsed[key] = ""
            current_key = key
            multiline_key = key
            continue

        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        parsed[key] = value
        current_key = key
        multiline_key = None

    if multiline_key is not None and multiline_key not in parsed:
        return None
    return parsed


def _load_frontmatter(frontmatter_text: str) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    if yaml is not None:
        try:
            frontmatter = yaml.safe_load(frontmatter_text)
        except yaml.YAMLError as exc:
            return None, f"Invalid YAML in frontmatter: {exc}"
        if not isinstance(frontmatter, dict):
            return None, "Frontmatter must be a YAML dictionary"
        return frontmatter, None

    frontmatter = _parse_simple_frontmatter(frontmatter_text)
    if frontmatter is None:
        return None, "Invalid YAML in frontmatter: unsupported syntax without PyYAML installed"
    return frontmatter, None


def validate_skill_directory_name(name: str) -> Optional[str]:
    """Return an error message if ``name`` is not a valid skill directory name, else ``None``."""
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        return (
            f"Name '{name}' should be hyphen-case "
            "(lowercase letters, digits, and single hyphens only)"
        )
    if len(name) > MAX_SKILL_NAME_LENGTH:
        return (
            f"Name is too long ({len(name)} characters). "
            f"Maximum is {MAX_SKILL_NAME_LENGTH} characters."
        )
    return None


def _validate_skill_name_matches_folder(raw_name: str, folder_name: str) -> Optional[str]:
    name = raw_name.strip()
    name_err = validate_skill_directory_name(name)
    if name_err:
        return name_err
    if name != folder_name:
        return f"Skill name '{name}' must match directory name '{folder_name}'"
    return None


def _validate_description(description: str) -> Optional[str]:
    trimmed = description.strip()
    if not trimmed:
        return "Description cannot be empty"
    lowered = trimmed.lower()
    if any(marker in lowered for marker in PLACEHOLDER_MARKERS):
        return "Description still contains TODO placeholder text"
    if "<" in trimmed or ">" in trimmed:
        return "Description cannot contain angle brackets (< or >)"
    if len(trimmed) > 1024:
        return f"Description is too long ({len(trimmed)} characters). Maximum is 1024 characters."
    return None


def validate_skill_md_content(content: str, *, folder_name: str) -> list[str]:
    """
    Validate SKILL.md body and frontmatter. Does not inspect sibling files on disk.

    Returns a list of error messages; empty means valid.
    """
    frontmatter_text = _extract_frontmatter(content)
    if frontmatter_text is None:
        return ["Invalid frontmatter format"]

    frontmatter, error = _load_frontmatter(frontmatter_text)
    if error:
        return [error]

    unexpected_keys = sorted(set(frontmatter.keys()) - ALLOWED_FRONTMATTER_KEYS)
    if unexpected_keys:
        allowed = ", ".join(sorted(ALLOWED_FRONTMATTER_KEYS))
        unexpected = ", ".join(unexpected_keys)
        return [
            f"Unexpected key(s) in SKILL.md frontmatter: {unexpected}. Allowed properties are: {allowed}",
        ]

    if "name" not in frontmatter:
        return ["Missing 'name' in frontmatter"]
    if "description" not in frontmatter:
        return ["Missing 'description' in frontmatter"]

    raw_name = frontmatter["name"]
    if not isinstance(raw_name, str):
        return [f"Name must be a string, got {type(raw_name).__name__}"]
    name_error = _validate_skill_name_matches_folder(raw_name, folder_name)
    if name_error:
        return [name_error]

    raw_desc = frontmatter["description"]
    if not isinstance(raw_desc, str):
        return [f"Description must be a string, got {type(raw_desc).__name__}"]
    desc_error = _validate_description(raw_desc)
    if desc_error:
        return [desc_error]

    always = frontmatter.get("always")
    if always is not None and not isinstance(always, bool):
        return [f"'always' must be a boolean, got {type(always).__name__}"]

    return []


def validate_skill_root_layout(skill_path: Path) -> list[str]:
    """
    Ensure only SKILL.md and optional allowed subdirs exist at the skill root.

    Returns a list of error messages; empty means valid.
    """
    for child in skill_path.iterdir():
        if child.name == "SKILL.md":
            continue
        if child.is_dir() and child.name in ALLOWED_RESOURCE_DIRS:
            continue
        if child.is_symlink():
            continue
        return [
            f"Unexpected file or directory in skill root: {child.name}. "
            "Only SKILL.md, scripts/, references/, and assets/ are allowed.",
        ]
    return []


def validate_skill(skill_path: str | Path) -> tuple[bool, str]:
    """Validate a skill folder structure and required frontmatter (CLI / tests)."""
    skill_path = Path(skill_path).resolve()

    if not skill_path.exists():
        return False, f"Skill folder not found: {skill_path}"
    if not skill_path.is_dir():
        return False, f"Path is not a directory: {skill_path}"

    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        return False, "SKILL.md not found"

    try:
        content = skill_md.read_text(encoding="utf-8")
    except OSError as exc:
        return False, f"Could not read SKILL.md: {exc}"

    errors = validate_skill_md_content(content, folder_name=skill_path.name)
    if errors:
        return False, errors[0]

    layout_errors = validate_skill_root_layout(skill_path)
    if layout_errors:
        return False, layout_errors[0]

    return True, "Skill is valid!"
