# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import List, Optional
from typing_extensions import Literal

from ..._models import BaseModel
from .local_skill import LocalSkill

__all__ = ["LocalEnvironment"]


class LocalEnvironment(BaseModel):
    type: Literal["local"]
    """Use a local computer environment."""

    skills: Optional[List[LocalSkill]] = None
    """An optional list of skills."""
