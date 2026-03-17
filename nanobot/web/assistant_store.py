"""Persistent agent configuration store for the web UI."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from nanobot.agent.skills import SkillsLoader
from nanobot.utils.helpers import ensure_dir
from nanobot.web.template_store import TemplateConfig


class AssistantConfig(BaseModel):
    """Editable agent configuration."""

    id: str
    name: str
    description: str = ""
    icon: str = "○"
    model: str
    enabled_skills: list[str] = Field(default_factory=list)
    enabled_mcps: list[str] = Field(default_factory=list)
    user_identity: str = ""
    agent_identity: str = ""
    system_prompt: str = ""
    required_mcps: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    example_query: str = ""
    source_template_id: str | None = None
    created_at: str
    updated_at: str


class AssistantUpdate(BaseModel):
    """Mutable agent fields."""

    name: str | None = None
    description: str | None = None
    icon: str | None = None
    model: str | None = None
    enabled_skills: list[str] | None = None
    enabled_mcps: list[str] | None = None
    user_identity: str | None = None
    agent_identity: str | None = None
    system_prompt: str | None = None


def serialize_assistant_prompt(assistant: AssistantConfig) -> dict[str, object]:
    """Project agent config into prompt-relevant metadata."""
    return {
        "id": assistant.id,
        "name": assistant.name,
        "description": assistant.description,
        "icon": assistant.icon,
        "model": assistant.model,
        "enabled_skills": assistant.enabled_skills,
        "enabled_mcps": assistant.enabled_mcps,
        "user_identity": assistant.user_identity,
        "agent_identity": assistant.agent_identity,
        "system_prompt": assistant.system_prompt,
        "required_mcps": assistant.required_mcps,
        "required_tools": assistant.required_tools,
        "example_query": assistant.example_query,
        "source_template_id": assistant.source_template_id,
    }


class AssistantStore:
    """Simple JSON-backed agent store."""

    def __init__(self, workspace: Path, default_model: str):
        self.workspace = workspace
        self.default_model = default_model
        self.store_dir = ensure_dir(self.workspace / "web")
        self.store_path = self.store_dir / "assistants.json"

    def _default_enabled_skills(self) -> list[str]:
        """Enable all globally available skills for newly created agents by default."""
        loader = SkillsLoader(self.workspace)
        return [item["name"] for item in loader.list_skills(filter_unavailable=False)]

    def list_assistants(self) -> list[AssistantConfig]:
        assistants = self._load()
        if not assistants:
            default = self.ensure_default()
            assistants = [default]
        return assistants

    def ensure_default(self) -> AssistantConfig:
        assistants = self._load()
        for assistant in assistants:
            if assistant.id == "default":
                return assistant
        now = datetime.now().isoformat()
        default = AssistantConfig(
            id="default",
            name="Default Agent",
            description="A blank agent with no additional prompt instructions.",
            icon="🐈",
            model=self.default_model,
            enabled_skills=self._default_enabled_skills(),
            created_at=now,
            updated_at=now,
        )
        assistants.insert(0, default)
        self._save(assistants)
        return default

    def get_assistant(self, assistant_id: str) -> AssistantConfig | None:
        for assistant in self.list_assistants():
            if assistant.id == assistant_id:
                return assistant
        return None

    def create_from_template(self, template: TemplateConfig | None, assistant_id: str, name: str | None = None) -> AssistantConfig:
        now = datetime.now().isoformat()
        template_name = template.name if template else "Custom Agent"
        final_name = (name or template_name).strip() or template_name
        assistant = AssistantConfig(
            id=assistant_id,
            name=final_name,
            description=template.description if template else "",
            icon=template.icon if template else "🐈",
            model=self.default_model,
            enabled_skills=self._default_enabled_skills(),
            user_identity=template.user_identity if template else "",
            agent_identity=template.agent_identity if template else "",
            system_prompt=template.system_prompt if template else "",
            required_mcps=list(template.required_mcps) if template else [],
            required_tools=list(template.required_tools) if template else [],
            example_query=template.example_query if template else "",
            source_template_id=template.id if template else None,
            created_at=now,
            updated_at=now,
        )
        assistants = self.list_assistants()
        if any(item.id == assistant.id for item in assistants):
            raise FileExistsError(assistant.id)
        # Check for name uniqueness
        if any(item.name == final_name for item in assistants):
            raise ValueError(f'Assistant name "{final_name}" already exists')
        assistants.insert(0, assistant)
        self._save(assistants)
        return assistant

    def delete_assistant(self, assistant_id: str) -> None:
        if assistant_id == "default":
            raise PermissionError('Assistant "default" cannot be deleted')
        assistants = self.list_assistants()
        remaining = [a for a in assistants if a.id != assistant_id]
        if len(remaining) == len(assistants):
            raise FileNotFoundError(assistant_id)
        self._save(remaining)

    def update_assistant(self, assistant_id: str, payload: AssistantUpdate) -> AssistantConfig:
        assistants = self.list_assistants()
        for index, assistant in enumerate(assistants):
            if assistant.id != assistant_id:
                continue
            data = assistant.model_dump()
            updates = payload.model_dump(exclude_unset=True)
            
            # Check for name uniqueness when updating name
            if "name" in updates and updates["name"]:
                new_name = updates["name"].strip()
                for other in assistants:
                    if other.id != assistant_id and other.name == new_name:
                        raise ValueError(f'Assistant name "{new_name}" already exists')
            
            data.update(updates)
            data["updated_at"] = datetime.now().isoformat()
            updated = AssistantConfig.model_validate(data)
            assistants[index] = updated
            self._save(assistants)
            return updated
        raise FileNotFoundError(assistant_id)

    def _load(self) -> list[AssistantConfig]:
        if not self.store_path.exists():
            return []
        payload = json.loads(self.store_path.read_text(encoding="utf-8"))
        return [AssistantConfig.model_validate(item) for item in payload]

    def _save(self, assistants: list[AssistantConfig]) -> None:
        self.store_path.write_text(
            json.dumps([assistant.model_dump() for assistant in assistants], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
