# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing_extensions import Literal

from ..._models import BaseModel

__all__ = ["ResponseFunctionCallArgumentsDoneEvent"]


class ResponseFunctionCallArgumentsDoneEvent(BaseModel):
    """
    Returned when the model-generated function call arguments are done streaming.
    Also emitted when a Response is interrupted, incomplete, or cancelled.
    """

    arguments: str
    """The final arguments as a JSON string."""

    call_id: str
    """The ID of the function call."""

    event_id: str
    """The unique ID of the server event."""

    item_id: str
    """The ID of the function call item."""

    name: str
    """The name of the function that was called."""

    output_index: int
    """The index of the output item in the response."""

    response_id: str
    """The ID of the response."""

    type: Literal["response.function_call_arguments.done"]
    """The event type, must be `response.function_call_arguments.done`."""
