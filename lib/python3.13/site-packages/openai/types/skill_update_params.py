# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Required, TypedDict

__all__ = ["SkillUpdateParams"]


class SkillUpdateParams(TypedDict, total=False):
    default_version: Required[str]
    """The skill version number to set as default."""
