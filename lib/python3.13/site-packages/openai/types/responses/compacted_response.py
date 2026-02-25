# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import List
from typing_extensions import Literal

from ..._models import BaseModel
from .response_usage import ResponseUsage
from .response_output_item import ResponseOutputItem

__all__ = ["CompactedResponse"]


class CompactedResponse(BaseModel):
    id: str
    """The unique identifier for the compacted response."""

    created_at: int
    """Unix timestamp (in seconds) when the compacted conversation was created."""

    object: Literal["response.compaction"]
    """The object type. Always `response.compaction`."""

    output: List[ResponseOutputItem]
    """The compacted list of output items.

    This is a list of all user messages, followed by a single compaction item.
    """

    usage: ResponseUsage
    """
    Token accounting for the compaction pass, including cached, reasoning, and total
    tokens.
    """
