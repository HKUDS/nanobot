"""Unified agent runtime configuration — single hierarchical model."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field, model_validator

from nanobot.config.base import Base
from nanobot.config.memory import MemoryConfig
from nanobot.config.mission import MissionConfig

# Fields removed in 2026-03-29 (delegation subsystem removal).
# Stripped from raw config dicts so existing config.json files don't break.
_AGENT_REMOVED_FIELDS = frozenset({"delegation_enabled", "max_delegation_depth"})


class AgentConfig(Base):
    """Unified agent runtime configuration.

    This is the single config model — it IS the config file schema AND the
    runtime model. No manual mapping, no ``AgentDefaults``, no ``from_defaults()``.

    Nested sections (``memory``, ``mission``) group related fields and are
    passed directly to their consuming subsystems.
    """

    # Core
    workspace: str = "~/.nanobot/workspace"
    model: str = "anthropic/claude-opus-4-5"
    max_tokens: int = 8192
    temperature: float = 0.1
    max_iterations: int = 40
    context_window_tokens: int = 128_000

    # Nested sections
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    mission: MissionConfig = Field(default_factory=MissionConfig)

    # Feature flags (applied from Config.features kill-switches)
    planning_enabled: bool = True
    verification_mode: str = "on_uncertainty"  # always | on_uncertainty | off
    memory_enabled: bool = True
    skills_enabled: bool = True
    streaming_enabled: bool = True

    # Tools
    shell_mode: str = "denylist"  # allowlist | denylist
    restrict_to_workspace: bool = True
    tool_result_max_chars: int = 2000
    tool_result_context_tokens: int = 500
    tool_summary_model: str = ""
    vision_model: str = "gpt-4o-mini"

    # Summary/Compression
    summary_model: str | None = None

    # Session
    message_timeout: int = 300
    max_session_cost_usd: float = 0.0
    max_session_wall_time_seconds: int = 0

    @model_validator(mode="before")
    @classmethod
    def _strip_removed(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if k not in _AGENT_REMOVED_FIELDS}
        return data

    @property
    def workspace_path(self) -> Path:
        return Path(self.workspace).expanduser()

    @classmethod
    def from_raw(cls, raw: dict[str, Any], **overrides: Any) -> AgentConfig:
        """Construct from config file data with overrides applied last."""
        data = {k: v for k, v in raw.items() if k not in _AGENT_REMOVED_FIELDS}
        data.update(overrides)
        return cls.model_validate(data)
