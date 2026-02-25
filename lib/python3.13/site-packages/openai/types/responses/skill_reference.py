# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Optional
from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["SkillReference"]


class SkillReference(BaseModel):
    skill_id: str
    """The ID of the referenced skill."""

    type: Literal["skill_reference"]
    """References a skill created with the /v1/skills endpoint."""

    version: Optional[str] = None
    """Optional skill version. Use a positive integer or 'latest'. Omit for default."""
