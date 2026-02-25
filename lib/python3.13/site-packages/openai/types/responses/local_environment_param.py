# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Iterable
from typing_extensions import Literal, Required, TypedDict

from .local_skill_param import LocalSkillParam

__all__ = ["LocalEnvironmentParam"]


class LocalEnvironmentParam(TypedDict, total=False):
    type: Required[Literal["local"]]
    """Use a local computer environment."""

    skills: Iterable[LocalSkillParam]
    """An optional list of skills."""
