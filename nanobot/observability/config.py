"""Langfuse settings, independent of the optional tracing SDK."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from pydantic import Field

from nanobot.config_base import Base

if TYPE_CHECKING:
    from nanobot.config.schema import Config

DEFAULT_LANGFUSE_BASE_URL = "https://cloud.langfuse.com"


class LangfuseConfig(Base):
    """An explicit block owns all tracing settings, including disabled state."""

    enabled: bool = False
    base_url: str = DEFAULT_LANGFUSE_BASE_URL
    public_key: str = Field(default="", repr=False)
    secret_key: str = Field(default="", repr=False)

    @property
    def configured(self) -> bool:
        return bool(self.public_key.strip() and self.secret_key.strip())


class ObservabilityConfig(Base):
    """Omission preserves legacy environment configuration on unrelated saves."""

    langfuse: LangfuseConfig | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )


def editable_langfuse_config(config: Config | None = None) -> LangfuseConfig:
    """Return raw settings; legacy credentials become references, never copied secrets."""
    if config is not None and config.observability.langfuse is not None:
        return config.observability.langfuse.model_copy(deep=True)

    def reference(name: str, default: str = "") -> str:
        return "${" + name + "}" if os.environ.get(name) else default

    base_var = "LANGFUSE_BASE_URL" if os.environ.get("LANGFUSE_BASE_URL") else "LANGFUSE_HOST"
    return LangfuseConfig(
        enabled=bool(os.environ.get("LANGFUSE_SECRET_KEY"))
        and os.environ.get("LANGFUSE_TRACING_ENABLED", "true").lower() != "false",
        base_url=reference(base_var, DEFAULT_LANGFUSE_BASE_URL),
        public_key=reference("LANGFUSE_PUBLIC_KEY"),
        secret_key=reference("LANGFUSE_SECRET_KEY"),
    )


def resolve_langfuse_config(config: Config | None = None) -> LangfuseConfig:
    """Resolve an explicit whole block or legacy env without mutating either input.

    Missing references resolve to empty fields, like other optional integrations.
    Full runtime config loading retains its existing strict missing-env validation.
    """
    from nanobot.config.loader import resolve_env_refs

    raw = editable_langfuse_config(config)
    return LangfuseConfig(
        enabled=raw.enabled,
        base_url=resolve_env_refs(raw.base_url),
        public_key=resolve_env_refs(raw.public_key),
        secret_key=resolve_env_refs(raw.secret_key),
    )
