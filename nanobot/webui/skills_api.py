"""Lightweight skill summaries for the WebUI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nanobot.agent.skills import SkillsLoader


def webui_skills_payload(
    workspace_path: Path,
    *,
    disabled_skills: set[str] | None = None,
) -> dict[str, Any]:
    """Return agent skills without leaking local filesystem paths."""
    loader = SkillsLoader(workspace_path, disabled_skills=disabled_skills)
    entries = sorted(
        loader.list_skills(filter_unavailable=False),
        key=lambda entry: (entry.get("source") != "workspace", entry["name"]),
    )
    return {"skills": [_skill_payload(loader, entry) for entry in entries]}


def webui_skill_detail_payload(
    workspace_path: Path,
    name: str,
    *,
    disabled_skills: set[str] | None = None,
) -> dict[str, Any] | None:
    """Return a single skill's safe detail payload."""
    loader = SkillsLoader(workspace_path, disabled_skills=disabled_skills)
    entries = loader.list_skills(filter_unavailable=False)
    entry = next((item for item in entries if item["name"] == name), None)
    if entry is None:
        return None
    return {
        **_skill_payload(loader, entry),
        "requirements": loader.get_skill_requirements(name),
        "raw_markdown": loader.load_skill(name) or "",
    }


def _skill_payload(loader: SkillsLoader, entry: dict[str, str]) -> dict[str, Any]:
    name = entry["name"]
    metadata = loader.get_skill_metadata(name)
    available, unavailable_reason = loader.get_skill_availability(name)
    return {
        "name": name,
        "description": _description(metadata, name),
        "source": entry.get("source", "unknown"),
        "available": available,
        "unavailable_reason": unavailable_reason,
    }


def _description(metadata: dict[str, Any] | None, fallback: str) -> str:
    if metadata is None:
        return fallback
    value = metadata.get("description")
    return value.strip() if isinstance(value, str) and value.strip() else fallback
