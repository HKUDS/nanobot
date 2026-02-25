# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel
from .inline_skill_source import InlineSkillSource

__all__ = ["InlineSkill"]


class InlineSkill(BaseModel):
    description: str
    """The description of the skill."""

    name: str
    """The name of the skill."""

    source: InlineSkillSource
    """Inline skill payload"""

    type: Literal["inline"]
    """Defines an inline skill for this request."""
