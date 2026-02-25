# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Literal, Required, TypedDict

__all__ = ["InlineSkillSourceParam"]


class InlineSkillSourceParam(TypedDict, total=False):
    """Inline skill payload"""

    data: Required[str]
    """Base64-encoded skill zip bundle."""

    media_type: Required[Literal["application/zip"]]
    """The media type of the inline skill payload. Must be `application/zip`."""

    type: Required[Literal["base64"]]
    """The type of the inline skill source. Must be `base64`."""
