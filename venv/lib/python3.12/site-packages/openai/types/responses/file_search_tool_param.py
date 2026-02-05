# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Union, Optional
from typing_extensions import Literal, Required, TypeAlias, TypedDict

from ..._types import SequenceNotStr
from ..shared_params.compound_filter import CompoundFilter
from ..shared_params.comparison_filter import ComparisonFilter

__all__ = ["FileSearchToolParam", "Filters", "RankingOptions", "RankingOptionsHybridSearch"]

Filters: TypeAlias = Union[ComparisonFilter, CompoundFilter]


class RankingOptionsHybridSearch(TypedDict, total=False):
    """
    Weights that control how reciprocal rank fusion balances semantic embedding matches versus sparse keyword matches when hybrid search is enabled.
    """

    embedding_weight: Required[float]
    """The weight of the embedding in the reciprocal ranking fusion."""

    text_weight: Required[float]
    """The weight of the text in the reciprocal ranking fusion."""


class RankingOptions(TypedDict, total=False):
    """Ranking options for search."""

    hybrid_search: RankingOptionsHybridSearch
    """
    Weights that control how reciprocal rank fusion balances semantic embedding
    matches versus sparse keyword matches when hybrid search is enabled.
    """

    ranker: Literal["auto", "default-2024-11-15"]
    """The ranker to use for the file search."""

    score_threshold: float
    """The score threshold for the file search, a number between 0 and 1.

    Numbers closer to 1 will attempt to return only the most relevant results, but
    may return fewer results.
    """


class FileSearchToolParam(TypedDict, total=False):
    """A tool that searches for relevant content from uploaded files.

    Learn more about the [file search tool](https://platform.openai.com/docs/guides/tools-file-search).
    """

    type: Required[Literal["file_search"]]
    """The type of the file search tool. Always `file_search`."""

    vector_store_ids: Required[SequenceNotStr[str]]
    """The IDs of the vector stores to search."""

    filters: Optional[Filters]
    """A filter to apply."""

    max_num_results: int
    """The maximum number of results to return.

    This number should be between 1 and 50 inclusive.
    """

    ranking_options: RankingOptions
    """Ranking options for search."""
