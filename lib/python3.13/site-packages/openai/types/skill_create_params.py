# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Union
from typing_extensions import TypedDict

from .._types import FileTypes, SequenceNotStr

__all__ = ["SkillCreateParams"]


class SkillCreateParams(TypedDict, total=False):
    files: Union[SequenceNotStr[FileTypes], FileTypes]
    """Skill files to upload (directory upload) or a single zip file."""
