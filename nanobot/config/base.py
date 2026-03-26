"""Base Pydantic model for nanobot configuration."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class Base(BaseModel):
    """Base model that accepts both camelCase and snake_case keys.

    Uses ``extra="forbid"`` so stale or mistyped fields in the config file
    cause an immediate validation error instead of being silently ignored.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")
