# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Literal, TypedDict

__all__ = ["VideoDownloadContentParams"]


class VideoDownloadContentParams(TypedDict, total=False):
    variant: Literal["video", "thumbnail", "spritesheet"]
    """Which downloadable asset to return. Defaults to the MP4 video."""
