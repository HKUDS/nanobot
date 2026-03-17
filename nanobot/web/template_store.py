"""Structured preset templates for the web experience."""

from __future__ import annotations

import json
from importlib.resources import files as pkg_files
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from nanobot.utils.helpers import ensure_dir


class TemplateConfig(BaseModel):
    """Structured preset template used when creating an agent."""

    id: str
    name: str
    description: str
    system_prompt: str
    user_identity: str
    agent_identity: str
    required_mcps: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    example_query: str = ""
    icon: str = "📋"


class TemplateStore:
    """Preset library combining bundled presets and editable workspace presets."""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.store_dir = ensure_dir(self.workspace / "web")
        self.store_path = self.store_dir / "presets.json"

    @staticmethod
    def _bundled_templates() -> list[TemplateConfig]:
        preset_dir = pkg_files("nanobot.web") / "presets"
        templates: list[TemplateConfig] = []
        for path in sorted(preset_dir.iterdir(), key=lambda item: item.name):
            if not path.is_file() or path.suffix.lower() != ".json":
                continue
            payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            templates.append(TemplateConfig.model_validate(payload))
        return templates

    def list_templates(self) -> list[TemplateConfig]:
        templates: dict[str, TemplateConfig] = {item.id: item for item in self._bundled_templates()}
        for item in self._load_custom_templates():
            templates[item.id] = item
        return sorted(templates.values(), key=lambda item: item.name.lower())

    def get_template(self, template_id: str | None) -> TemplateConfig | None:
        if not template_id:
            return None
        for template in self.list_templates():
            if template.id == template_id:
                return template
        return None

    def upsert_template(self, payload: TemplateConfig) -> TemplateConfig:
        templates = {item.id: item for item in self._load_custom_templates()}
        templates[payload.id] = payload
        self._save_custom_templates(list(templates.values()))
        return payload

    def delete_template(self, template_id: str) -> None:
        """Delete a custom template. Bundled templates cannot be deleted."""
        bundled_ids = {item.id for item in self._bundled_templates()}
        if template_id in bundled_ids:
            raise PermissionError(f'Bundled template "{template_id}" cannot be deleted')
        customs = {item.id: item for item in self._load_custom_templates()}
        if template_id not in customs:
            raise FileNotFoundError(template_id)
        del customs[template_id]
        self._save_custom_templates(list(customs.values()))

    def _load_custom_templates(self) -> list[TemplateConfig]:
        if not self.store_path.exists():
            return []
        payload = json.loads(self.store_path.read_text(encoding="utf-8"))
        return [TemplateConfig.model_validate(item) for item in payload]

    def _save_custom_templates(self, templates: list[TemplateConfig]) -> None:
        self.store_path.write_text(
            json.dumps([item.model_dump() for item in templates], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def load_templates() -> list[TemplateConfig]:
    """Load bundled web templates from JSON preset files."""
    preset_dir = pkg_files("nanobot.web") / "presets"
    templates: list[TemplateConfig] = []
    for path in sorted(preset_dir.iterdir(), key=lambda item: item.name):
        if not path.is_file() or path.suffix.lower() != ".json":
            continue
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        templates.append(TemplateConfig.model_validate(payload))
    return templates


def get_template(template_id: str | None) -> TemplateConfig | None:
    """Return a bundled template by id."""
    if not template_id:
        return None
    for template in load_templates():
        if template.id == template_id:
            return template
    return None
