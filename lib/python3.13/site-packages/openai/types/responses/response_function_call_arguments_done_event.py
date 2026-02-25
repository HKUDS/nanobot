# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["ResponseFunctionCallArgumentsDoneEvent"]


class ResponseFunctionCallArgumentsDoneEvent(BaseModel):
    """Emitted when function-call arguments are finalized."""

    arguments: str
    """The function-call arguments."""

    item_id: str
    """The ID of the item."""

    name: str
    """The name of the function that was called."""

    output_index: int
    """The index of the output item."""

    sequence_number: int
    """The sequence number of this event."""

    type: Literal["response.function_call_arguments.done"]
