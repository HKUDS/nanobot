# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import List, Union, Optional
from typing_extensions import Literal, Annotated, TypeAlias

from ..._utils import PropertyInfo
from ..._models import BaseModel

__all__ = [
    "ResponseFunctionWebSearch",
    "Action",
    "ActionSearch",
    "ActionSearchSource",
    "ActionOpenPage",
    "ActionFind",
]


class ActionSearchSource(BaseModel):
    """A source used in the search."""

    type: Literal["url"]
    """The type of source. Always `url`."""

    url: str
    """The URL of the source."""


class ActionSearch(BaseModel):
    """Action type "search" - Performs a web search query."""

    query: str
    """[DEPRECATED] The search query."""

    type: Literal["search"]
    """The action type."""

    queries: Optional[List[str]] = None
    """The search queries."""

    sources: Optional[List[ActionSearchSource]] = None
    """The sources used in the search."""


class ActionOpenPage(BaseModel):
    """Action type "open_page" - Opens a specific URL from search results."""

    type: Literal["open_page"]
    """The action type."""

    url: Optional[str] = None
    """The URL opened by the model."""


class ActionFind(BaseModel):
    """Action type "find_in_page": Searches for a pattern within a loaded page."""

    pattern: str
    """The pattern or text to search for within the page."""

    type: Literal["find_in_page"]
    """The action type."""

    url: str
    """The URL of the page searched for the pattern."""


Action: TypeAlias = Annotated[Union[ActionSearch, ActionOpenPage, ActionFind], PropertyInfo(discriminator="type")]


class ResponseFunctionWebSearch(BaseModel):
    """The results of a web search tool call.

    See the
    [web search guide](https://platform.openai.com/docs/guides/tools-web-search) for more information.
    """

    id: str
    """The unique ID of the web search tool call."""

    action: Action
    """
    An object describing the specific action taken in this web search call. Includes
    details on how the model used the web (search, open_page, find_in_page).
    """

    status: Literal["in_progress", "searching", "completed", "failed"]
    """The status of the web search tool call."""

    type: Literal["web_search_call"]
    """The type of the web search tool call. Always `web_search_call`."""
