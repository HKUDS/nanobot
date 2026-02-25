# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from ..._models import BaseModel

__all__ = ["LocalSkill"]


class LocalSkill(BaseModel):
    description: str
    """The description of the skill."""

    name: str
    """The name of the skill."""

    path: str
    """The path to the directory containing the skill."""
