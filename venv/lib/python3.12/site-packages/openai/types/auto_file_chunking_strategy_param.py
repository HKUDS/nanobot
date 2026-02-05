# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing_extensions import Literal, Required, TypedDict

__all__ = ["AutoFileChunkingStrategyParam"]


class AutoFileChunkingStrategyParam(TypedDict, total=False):
    """The default strategy.

    This strategy currently uses a `max_chunk_size_tokens` of `800` and `chunk_overlap_tokens` of `400`.
    """

    type: Required[Literal["auto"]]
    """Always `auto`."""
