# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from .response_function_tool_call import ResponseFunctionToolCall

__all__ = ["ResponseFunctionToolCallItem"]


class ResponseFunctionToolCallItem(ResponseFunctionToolCall):
    """A tool call to run a function.

    See the
    [function calling guide](https://platform.openai.com/docs/guides/function-calling) for more information.
    """

    id: str  # type: ignore
    """The unique ID of the function tool call."""
