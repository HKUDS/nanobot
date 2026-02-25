# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Literal, Required, TypedDict

from .inline_skill_source_param import InlineSkillSourceParam

__all__ = ["InlineSkillParam"]


class InlineSkillParam(TypedDict, total=False):
    description: Required[str]
    """The description of the skill."""

    name: Required[str]
    """The name of the skill."""

    source: Required[InlineSkillSourceParam]
    """Inline skill payload"""

    type: Required[Literal["inline"]]
    """Defines an inline skill for this request."""
