"""Discover portable Agent Plugins from the agent workspace."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml
from loguru import logger

AGENT_PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"

_PLUGIN_NAME = re.compile(r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
_SKILL_NAME = re.compile(r"^(?!.*--)[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
_SKILL_FRONTMATTER = re.compile(r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?", re.DOTALL)
_MANIFEST_FIELDS = {
    "$schema",
    "name",
    "version",
    "description",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
    "extensions",
}
_STRING_FIELDS = {"version", "description", "homepage", "repository", "license"}
_AUTHOR_FIELDS = {"name", "email", "url"}


@dataclass(frozen=True)
class AgentPluginSkill:
    """One skill supplied by a valid Agent Plugins v1 package."""

    name: str
    path: Path
    plugin: str


def discover_agent_plugin_skills(workspace: Path) -> list[AgentPluginSkill]:
    """Discover direct-child skills under ``<workspace>/plugins/*``.

    Agent Plugins does not prescribe an install location. nanobot uses the
    workspace ``plugins`` directory so packages stay explicit and portable
    with the rest of the agent workspace.
    """
    workspace = workspace.expanduser().resolve()
    plugins_root = workspace / "plugins"
    if not plugins_root.is_dir():
        return []
    try:
        resolved_plugins_root = plugins_root.resolve(strict=True)
    except OSError:
        return []
    if not resolved_plugins_root.is_relative_to(workspace):
        logger.warning("Ignoring Agent Plugins directory outside the workspace")
        return []

    try:
        candidates = sorted(plugins_root.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        logger.warning("Could not inspect Agent Plugins directory: {}", exc)
        return []

    skills: list[AgentPluginSkill] = []
    for candidate in candidates:
        plugin_root = _contained_directory(candidate, resolved_plugins_root)
        if plugin_root is None:
            continue
        plugin_name = _load_manifest_name(plugin_root)
        if plugin_name is None:
            continue
        skills.extend(_discover_plugin_skills(plugin_name, plugin_root))
    return skills


def _load_manifest_name(plugin_root: Path) -> str | None:
    manifest = _contained_file(plugin_root / "plugin.json", plugin_root)
    if manifest is None:
        return None
    try:
        value = cast(object, json.loads(manifest.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring invalid Agent Plugin manifest '{}': {}", manifest, exc)
        return None
    if not isinstance(value, dict):
        logger.warning("Ignoring Agent Plugin manifest '{}': expected a JSON object", manifest)
        return None

    payload = cast(dict[str, Any], value)
    if payload.get("$schema") != AGENT_PLUGIN_SCHEMA:
        return None
    name = payload.get("name")
    if (
        not isinstance(name, str)
        or len(name) > 64
        or _PLUGIN_NAME.fullmatch(name) is None
    ):
        logger.warning("Ignoring Agent Plugin manifest '{}': invalid name", manifest)
        return None
    if not _valid_optional_fields(payload):
        logger.warning("Ignoring Agent Plugin manifest '{}': invalid metadata", manifest)
        return None

    for field in payload.keys() - _MANIFEST_FIELDS:
        logger.warning("Ignoring unknown Agent Plugin manifest field '{}' in '{}'", field, manifest)
    if "extensions" in payload and not isinstance(payload["extensions"], dict):
        logger.warning("Ignoring non-object Agent Plugin extensions in '{}'", manifest)
    return name


def _valid_optional_fields(payload: dict[str, Any]) -> bool:
    if any(field in payload and not isinstance(payload[field], str) for field in _STRING_FIELDS):
        return False
    keywords = payload.get("keywords")
    if "keywords" in payload and (
        not isinstance(keywords, list)
        or not all(isinstance(keyword, str) for keyword in cast(list[object], keywords))
    ):
        return False
    author = payload.get("author")
    if "author" not in payload:
        return True
    if not isinstance(author, dict):
        return False
    author_payload = cast(dict[str, object], author)
    return not (author_payload.keys() - _AUTHOR_FIELDS) and all(
        isinstance(value, str) for value in author_payload.values()
    )


def _discover_plugin_skills(plugin_name: str, plugin_root: Path) -> list[AgentPluginSkill]:
    skills_root = plugin_root / "skills"
    if not skills_root.exists():
        return []
    resolved_skills_root = _contained_directory(skills_root, plugin_root)
    if resolved_skills_root is None:
        logger.warning("Ignoring invalid skills component in Agent Plugin '{}'", plugin_name)
        return []

    try:
        candidates = sorted(skills_root.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        logger.warning("Could not inspect Agent Plugin '{}' skills: {}", plugin_name, exc)
        return []

    skills: list[AgentPluginSkill] = []
    for candidate in candidates:
        skill_root = _contained_directory(candidate, resolved_skills_root)
        if skill_root is None:
            continue
        skill_file = _contained_file(skill_root / "SKILL.md", plugin_root)
        if skill_file is None or not _valid_skill(skill_file, candidate.name, plugin_name):
            continue
        skills.append(
            AgentPluginSkill(name=candidate.name, path=skill_file, plugin=plugin_name)
        )
    return skills


def _valid_skill(path: Path, directory_name: str, plugin_name: str) -> bool:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    match = _SKILL_FRONTMATTER.match(content)
    if match is None:
        logger.warning("Ignoring Agent Plugin '{}' skill '{}': invalid frontmatter", plugin_name, directory_name)
        return False
    try:
        metadata = cast(object, yaml.safe_load(match.group(1)))
    except yaml.YAMLError:
        metadata = None
    if not isinstance(metadata, dict):
        logger.warning("Ignoring Agent Plugin '{}' skill '{}': invalid frontmatter", plugin_name, directory_name)
        return False
    payload = cast(dict[object, object], metadata)
    name = payload.get("name")
    description = payload.get("description")
    valid = (
        name == directory_name
        and isinstance(name, str)
        and len(name) <= 64
        and _SKILL_NAME.fullmatch(name) is not None
        and isinstance(description, str)
        and 1 <= len(description.strip()) <= 1024
    )
    if not valid:
        logger.warning("Ignoring Agent Plugin '{}' skill '{}': invalid metadata", plugin_name, directory_name)
    return valid


def _contained_directory(path: Path, root: Path) -> Path | None:
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return None
    return resolved if resolved.is_dir() and resolved.is_relative_to(root) else None


def _contained_file(path: Path, root: Path) -> Path | None:
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return None
    return resolved if resolved.is_file() and resolved.is_relative_to(root) else None
