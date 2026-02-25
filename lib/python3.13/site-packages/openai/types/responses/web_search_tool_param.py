# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Optional
from typing_extensions import Literal, Required, TypedDict

from ..._types import SequenceNotStr

__all__ = ["WebSearchToolParam", "Filters", "UserLocation"]


class Filters(TypedDict, total=False):
    """Filters for the search."""

    allowed_domains: Optional[SequenceNotStr[str]]
    """Allowed domains for the search.

    If not provided, all domains are allowed. Subdomains of the provided domains are
    allowed as well.

    Example: `["pubmed.ncbi.nlm.nih.gov"]`
    """


class UserLocation(TypedDict, total=False):
    """The approximate location of the user."""

    city: Optional[str]
    """Free text input for the city of the user, e.g. `San Francisco`."""

    country: Optional[str]
    """
    The two-letter [ISO country code](https://en.wikipedia.org/wiki/ISO_3166-1) of
    the user, e.g. `US`.
    """

    region: Optional[str]
    """Free text input for the region of the user, e.g. `California`."""

    timezone: Optional[str]
    """
    The [IANA timezone](https://timeapi.io/documentation/iana-timezones) of the
    user, e.g. `America/Los_Angeles`.
    """

    type: Literal["approximate"]
    """The type of location approximation. Always `approximate`."""


class WebSearchToolParam(TypedDict, total=False):
    """Search the Internet for sources related to the prompt.

    Learn more about the
    [web search tool](https://platform.openai.com/docs/guides/tools-web-search).
    """

    type: Required[Literal["web_search", "web_search_2025_08_26"]]
    """The type of the web search tool.

    One of `web_search` or `web_search_2025_08_26`.
    """

    filters: Optional[Filters]
    """Filters for the search."""

    search_context_size: Literal["low", "medium", "high"]
    """High level guidance for the amount of context window space to use for the
    search.

    One of `low`, `medium`, or `high`. `medium` is the default.
    """

    user_location: Optional[UserLocation]
    """The approximate location of the user."""
