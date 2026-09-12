"""Explicit operator configuration for self-development, separate from Evolution."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from nanobot.config_base import Base


class DevelopmentConfig(Base):
    enable: bool = False
    owner_session_key: str = ""
    repository: str = ""
    daily_token_budget: int = Field(default=100_000, ge=1000, le=10_000_000)
    max_repair_attempts: int = Field(default=2, ge=0, le=2)
    check_timeout_seconds: int = Field(default=600, ge=10, le=3600)
    checks: list[list[str]] = Field(default_factory=list)
    read_only_dependencies: list[str] = Field(default_factory=list)
    source_dependencies: list[str] = Field(default_factory=list)
    builder_protocol: Literal["auto", "tools", "json"] = "auto"
    worker_backend: Literal["process", "systemd"] = "process"
    resume_on_restart: bool = True

    @model_validator(mode="after")
    def validate_scope(self) -> DevelopmentConfig:
        if self.enable and (not self.owner_session_key or not self.repository):
            raise ValueError("development requires an owner session and repository")
        if self.repository and not Path(self.repository).expanduser().is_absolute():
            raise ValueError("development repository must be absolute")
        for command in self.checks:
            if not command or any(not arg or "\x00" in arg for arg in command):
                raise ValueError("development checks must be non-empty argv lists")
        for directory in self.read_only_dependencies:
            if not Path(directory).expanduser().is_absolute():
                raise ValueError("development dependencies must use absolute paths")
        for directory in self.source_dependencies:
            path = Path(directory)
            if path.is_absolute() or ".." in path.parts or path.name != "node_modules":
                raise ValueError("source dependencies must be relative node_modules directories")
        return self
