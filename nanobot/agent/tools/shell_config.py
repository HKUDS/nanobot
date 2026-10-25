"""Execution configuration shared by shell/session tools and the root schema."""

from collections.abc import Mapping
from typing import Literal, cast

from pydantic import AliasChoices, Field, model_validator

from nanobot.config_base import Base


class ExecToolConfig(Base):
    """Shell exec tool configuration."""
    enable: bool = True
    max_runtime: int = Field(
        default=3600, ge=0,
        validation_alias=AliasChoices("maxRuntime", "max_runtime", "timeout"),
    )
    max_runtime_limit: int = Field(default=86400, gt=0)
    idle_timeout: int = Field(default=300, ge=0)
    idle_action: Literal["report", "terminate"] = "report"
    path_prepend: str = ""
    path_append: str = ""
    sandbox: str = ""
    sandbox_ro_binds: list[str] = Field(default_factory=list)
    sandbox_rw_binds: list[str] = Field(default_factory=list)
    allowed_env_keys: list[str] = Field(default_factory=list)
    allow_patterns: list[str] = Field(default_factory=list)
    deny_patterns: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _reject_runtime_alias_conflict(cls, value: object) -> object:
        if isinstance(value, Mapping):
            value = cast(Mapping[object, object], value)
            if "timeout" in value and ("maxRuntime" in value or "max_runtime" in value):
                raise ValueError("Use maxRuntime or legacy timeout, not both")
        return value

    @property
    def timeout(self) -> int:
        """Legacy hard-runtime setting backed by ``max_runtime``."""
        return self.max_runtime

    @timeout.setter
    def timeout(self, value: int) -> None:
        self.max_runtime = value
