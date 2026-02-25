# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from .._models import BaseModel

__all__ = ["Skill"]


class Skill(BaseModel):
    id: str
    """Unique identifier for the skill."""

    created_at: int
    """Unix timestamp (seconds) for when the skill was created."""

    default_version: str
    """Default version for the skill."""

    description: str
    """Description of the skill."""

    latest_version: str
    """Latest version for the skill."""

    name: str
    """Name of the skill."""

    object: Literal["skill"]
    """The object type, which is `skill`."""
