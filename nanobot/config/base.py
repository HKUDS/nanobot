"""Base Pydantic model for nanobot configuration."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Base(BaseModel):
    """Base model for all config sections.

    Uses ``extra="forbid"`` so stale or mistyped fields in the config file
    cause an immediate validation error instead of being silently ignored.
    Config files use snake_case keys, matching Python field names.
    """

    model_config = ConfigDict(extra="forbid")
