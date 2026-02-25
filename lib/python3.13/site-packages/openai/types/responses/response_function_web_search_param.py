# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Union, Iterable, Optional
from typing_extensions import Literal, Required, TypeAlias, TypedDict

from ..._types import SequenceNotStr

__all__ = [
    "ResponseFunctionWebSearchParam",
    "Action",
    "ActionSearch",
    "ActionSearchSource",
    "ActionOpenPage",
    "ActionFind",
]


class ActionSearchSource(TypedDict, total=False):
    """A source used in the search."""

    type: Required[Literal["url"]]
    """The type of source. Always `url`."""

    url: Required[str]
    """The URL of the source."""


class ActionSearch(TypedDict, total=False):
    """Action type "search" - Performs a web search query."""

    query: Required[str]
    """[DEPRECATED] The search query."""

    type: Required[Literal["search"]]
    """The action type."""

    queries: SequenceNotStr[str]
    """The search queries."""

    sources: Iterable[ActionSearchSource]
    """The sources used in the search."""


class ActionOpenPage(TypedDict, total=False):
    """Action type "open_page" - Opens a specific URL from search results."""

    type: Required[Literal["open_page"]]
    """The action type."""

    url: Optional[str]
    """The URL opened by the model."""


class ActionFind(TypedDict, total=False):
    """Action type "find_in_page": Searches for a pattern within a loaded page."""

    pattern: Required[str]
    """The pattern or text to search for within the page."""

    type: Required[Literal["find_in_page"]]
    """The action type."""

    url: Required[str]
    """The URL of the page searched for the pattern."""


Action: TypeAlias = Union[ActionSearch, ActionOpenPage, ActionFind]


class ResponseFunctionWebSearchParam(TypedDict, total=False):
    """The results of a web search tool call.

    See the
    [web search guide](https://platform.openai.com/docs/guides/tools-web-search) for more information.
    """

    id: Required[str]
    """The unique ID of the web search tool call."""

    action: Required[Action]
    """
    An object describing the specific action taken in this web search call. Includes
    details on how the model used the web (search, open_page, find_in_page).
    """

    status: Required[Literal["in_progress", "searching", "completed", "failed"]]
    """The status of the web search tool call."""

    type: Required[Literal["web_search_call"]]
    """The type of the web search tool call. Always `web_search_call`."""
