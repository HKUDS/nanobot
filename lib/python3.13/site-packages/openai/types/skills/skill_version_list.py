# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import List, Optional
from typing_extensions import Literal

from ..._models import BaseModel
from .skill_version import SkillVersion

__all__ = ["SkillVersionList"]


class SkillVersionList(BaseModel):
    data: List[SkillVersion]
    """A list of items"""

    first_id: Optional[str] = None
    """The ID of the first item in the list."""

    has_more: bool
    """Whether there are more items available."""

    last_id: Optional[str] = None
    """The ID of the last item in the list."""

    object: Literal["list"]
    """The type of object returned, must be `list`."""
