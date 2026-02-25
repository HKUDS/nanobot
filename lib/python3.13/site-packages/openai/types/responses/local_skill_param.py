# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Required, TypedDict

__all__ = ["LocalSkillParam"]


class LocalSkillParam(TypedDict, total=False):
    description: Required[str]
    """The description of the skill."""

    name: Required[str]
    """The name of the skill."""

    path: Required[str]
    """The path to the directory containing the skill."""
