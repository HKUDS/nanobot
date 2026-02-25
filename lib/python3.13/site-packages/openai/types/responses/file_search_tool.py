# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import List, Union, Optional
from typing_extensions import Literal, TypeAlias

from ..._models import BaseModel
from ..shared.compound_filter import CompoundFilter
from ..shared.comparison_filter import ComparisonFilter

__all__ = ["FileSearchTool", "Filters", "RankingOptions", "RankingOptionsHybridSearch"]

Filters: TypeAlias = Union[ComparisonFilter, CompoundFilter, None]


class RankingOptionsHybridSearch(BaseModel):
    """
    Weights that control how reciprocal rank fusion balances semantic embedding matches versus sparse keyword matches when hybrid search is enabled.
    """

    embedding_weight: float
    """The weight of the embedding in the reciprocal ranking fusion."""

    text_weight: float
    """The weight of the text in the reciprocal ranking fusion."""


class RankingOptions(BaseModel):
    """Ranking options for search."""

    hybrid_search: Optional[RankingOptionsHybridSearch] = None
    """
    Weights that control how reciprocal rank fusion balances semantic embedding
    matches versus sparse keyword matches when hybrid search is enabled.
    """

    ranker: Optional[Literal["auto", "default-2024-11-15"]] = None
    """The ranker to use for the file search."""

    score_threshold: Optional[float] = None
    """The score threshold for the file search, a number between 0 and 1.

    Numbers closer to 1 will attempt to return only the most relevant results, but
    may return fewer results.
    """


class FileSearchTool(BaseModel):
    """A tool that searches for relevant content from uploaded files.

    Learn more about the [file search tool](https://platform.openai.com/docs/guides/tools-file-search).
    """

    type: Literal["file_search"]
    """The type of the file search tool. Always `file_search`."""

    vector_store_ids: List[str]
    """The IDs of the vector stores to search."""

    filters: Optional[Filters] = None
    """A filter to apply."""

    max_num_results: Optional[int] = None
    """The maximum number of results to return.

    This number should be between 1 and 50 inclusive.
    """

    ranking_options: Optional[RankingOptions] = None
    """Ranking options for search."""
