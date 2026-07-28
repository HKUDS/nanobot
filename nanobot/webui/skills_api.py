"""Lightweight skill summaries for the WebUI."""

from __future__ import annotations

import json
import shlex
import tempfile
from pathlib import Path
from typing import Any

from nanobot.agent.skills import SkillsLoader
from nanobot.config.loader import load_config, save_config
from nanobot.security.workspace_policy import WorkspaceBoundaryError, require_path_within


class SkillManagementError(Exception):
    """A safe skill-management error for the WebUI."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def webui_skills_payload(
    workspace_path: Path,
    *,
    disabled_skills: set[str] | None = None,
) -> dict[str, Any]:
    """Return agent skills without leaking local filesystem paths."""
    loader = SkillsLoader(workspace_path)
    entries = sorted(
        loader.list_skills(filter_unavailable=False),
        key=lambda entry: (entry.get("source") != "workspace", entry["name"]),
    )
    return {
        "skills": [
            _skill_payload(loader, entry, disabled_skills=disabled_skills)
            for entry in entries
        ]
    }


def webui_skill_detail_payload(
    workspace_path: Path,
    name: str,
    *,
    disabled_skills: set[str] | None = None,
) -> dict[str, Any] | None:
    """Return a single skill's safe detail payload."""
    loader = SkillsLoader(workspace_path)
    entries = loader.list_skills(filter_unavailable=False)
    entry = next((item for item in entries if item["name"] == name), None)
    if entry is None:
        return None
    metadata = loader.get_skill_metadata(name)
    return {
        **_skill_payload(
            loader,
            entry,
            metadata=metadata,
            disabled_skills=disabled_skills,
        ),
        "requirements": loader.get_skill_requirements(name),
        "install_options": _install_options(metadata),
        "raw_markdown": loader.load_skill(name) or "",
    }


def set_webui_skill_enabled(
    workspace_path: Path,
    name: str,
    *,
    enabled: bool,
    disabled_skills: set[str],
) -> dict[str, Any]:
    """Persist and apply one skill's enabled state."""
    _require_skill_entry(workspace_path, name)
    config = load_config()
    next_disabled = set(config.agents.defaults.disabled_skills)
    if enabled:
        next_disabled.discard(name)
    else:
        next_disabled.add(name)
    if next_disabled != set(config.agents.defaults.disabled_skills):
        config.agents.defaults.disabled_skills = sorted(next_disabled)
        save_config(config)
    disabled_skills.clear()
    disabled_skills.update(next_disabled)
    return {"name": name, "enabled": enabled, "deleted": False}


def delete_webui_skill(
    workspace_path: Path,
    name: str,
    *,
    disabled_skills: set[str],
) -> dict[str, Any]:
    """Delete one workspace skill and remove its disabled-state entry."""
    entry = _require_skill_entry(workspace_path, name)
    if entry.get("source") != "workspace":
        raise SkillManagementError("built-in skills cannot be deleted", status=403)

    workspace = workspace_path.expanduser().resolve()
    try:
        skills_root = require_path_within(
            workspace / "skills",
            workspace,
            message="skills directory must stay inside the workspace",
        )
    except WorkspaceBoundaryError as exc:
        raise SkillManagementError(str(exc), status=403) from exc
    target = skills_root / name
    if target.parent != skills_root:
        raise SkillManagementError("invalid skill name")
    if not target.is_symlink() and not target.is_dir():
        raise SkillManagementError("skill directory was not found", status=404)

    config = load_config()
    original_disabled = list(config.agents.defaults.disabled_skills)
    next_disabled = set(original_disabled)
    if name in next_disabled:
        next_disabled.remove(name)
    with tempfile.TemporaryDirectory(prefix=".nanobot-delete-", dir=skills_root) as staging:
        staged_target = Path(staging) / name
        target.replace(staged_target)
        try:
            if next_disabled != set(original_disabled):
                config.agents.defaults.disabled_skills = sorted(next_disabled)
                save_config(config)
        except Exception:
            config.agents.defaults.disabled_skills = original_disabled
            staged_target.replace(target)
            raise
    disabled_skills.clear()
    disabled_skills.update(next_disabled)
    return {"name": name, "enabled": False, "deleted": True}


def _require_skill_entry(workspace_path: Path, name: str) -> dict[str, str]:
    if not name or "/" in name or "\\" in name:
        raise SkillManagementError("invalid skill name")
    entry = next(
        (
            item
            for item in SkillsLoader(workspace_path).list_skills(filter_unavailable=False)
            if item["name"] == name
        ),
        None,
    )
    if entry is None:
        raise SkillManagementError("skill not found", status=404)
    return entry


def _skill_payload(
    loader: SkillsLoader,
    entry: dict[str, str],
    *,
    metadata: dict[str, Any] | None = None,
    disabled_skills: set[str] | None = None,
) -> dict[str, Any]:
    name = entry["name"]
    metadata = metadata if metadata is not None else loader.get_skill_metadata(name)
    available, unavailable_reason = loader.get_skill_availability(name)
    source = entry.get("source", "unknown")
    return {
        "name": name,
        "description": _description(metadata, name),
        "source": source,
        "enabled": name not in (disabled_skills or set()),
        "deletable": source == "workspace",
        "available": available,
        "unavailable_reason": unavailable_reason,
    }


def _description(metadata: dict[str, Any] | None, fallback: str) -> str:
    if metadata is None:
        return fallback
    value = metadata.get("description")
    return value.strip() if isinstance(value, str) and value.strip() else fallback


def _nanobot_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if metadata is None:
        return {}
    raw = metadata.get("metadata")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    if not isinstance(raw, dict):
        return {}
    payload = raw.get("nanobot", raw.get("openclaw", {}))
    return payload if isinstance(payload, dict) else {}


def _install_options(metadata: dict[str, Any] | None) -> list[dict[str, str]]:
    """Return safe, copyable setup commands declared by a skill."""
    install = _nanobot_metadata(metadata).get("install")
    if not isinstance(install, list):
        return []

    options: list[dict[str, str]] = []
    for item in install:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        package = item.get("formula") if kind == "brew" else item.get("package")
        if not isinstance(package, str) or not package.strip():
            continue
        if kind == "brew":
            command = f"brew install {shlex.quote(package.strip())}"
        elif kind == "apt":
            command = f"sudo apt-get install -y {shlex.quote(package.strip())}"
        else:
            continue
        option_id = item.get("id")
        label = item.get("label")
        options.append(
            {
                "id": option_id if isinstance(option_id, str) else kind,
                "kind": kind,
                "label": label if isinstance(label, str) else f"Install with {kind}",
                "command": command,
            }
        )
    return options
