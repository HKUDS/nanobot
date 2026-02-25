# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["SkillVersion"]


class SkillVersion(BaseModel):
    id: str
    """Unique identifier for the skill version."""

    created_at: int
    """Unix timestamp (seconds) for when the version was created."""

    description: str
    """Description of the skill version."""

    name: str
    """Name of the skill version."""

    object: Literal["skill.version"]
    """The object type, which is `skill.version`."""

    skill_id: str
    """Identifier of the skill for this version."""

    version: str
    """Version number for this skill."""
