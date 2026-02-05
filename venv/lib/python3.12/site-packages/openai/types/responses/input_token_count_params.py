# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Union, Iterable, Optional
from typing_extensions import Literal, TypeAlias, TypedDict

from .tool_param import ToolParam
from .tool_choice_options import ToolChoiceOptions
from .tool_choice_mcp_param import ToolChoiceMcpParam
from .tool_choice_shell_param import ToolChoiceShellParam
from .tool_choice_types_param import ToolChoiceTypesParam
from ..shared_params.reasoning import Reasoning
from .tool_choice_custom_param import ToolChoiceCustomParam
from .response_input_item_param import ResponseInputItemParam
from .tool_choice_allowed_param import ToolChoiceAllowedParam
from .tool_choice_function_param import ToolChoiceFunctionParam
from .response_conversation_param import ResponseConversationParam
from .tool_choice_apply_patch_param import ToolChoiceApplyPatchParam
from .response_format_text_config_param import ResponseFormatTextConfigParam

__all__ = ["InputTokenCountParams", "Conversation", "Text", "ToolChoice"]


class InputTokenCountParams(TypedDict, total=False):
    conversation: Optional[Conversation]
    """The conversation that this response belongs to.

    Items from this conversation are prepended to `input_items` for this response
    request. Input items and output items from this response are automatically added
    to this conversation after this response completes.
    """

    input: Union[str, Iterable[ResponseInputItemParam], None]
    """Text, image, or file inputs to the model, used to generate a response"""

    instructions: Optional[str]
    """
    A system (or developer) message inserted into the model's context. When used
    along with `previous_response_id`, the instructions from a previous response
    will not be carried over to the next response. This makes it simple to swap out
    system (or developer) messages in new responses.
    """

    model: Optional[str]
    """Model ID used to generate the response, like `gpt-4o` or `o3`.

    OpenAI offers a wide range of models with different capabilities, performance
    characteristics, and price points. Refer to the
    [model guide](https://platform.openai.com/docs/models) to browse and compare
    available models.
    """

    parallel_tool_calls: Optional[bool]
    """Whether to allow the model to run tool calls in parallel."""

    previous_response_id: Optional[str]
    """The unique ID of the previous response to the model.

    Use this to create multi-turn conversations. Learn more about
    [conversation state](https://platform.openai.com/docs/guides/conversation-state).
    Cannot be used in conjunction with `conversation`.
    """

    reasoning: Optional[Reasoning]
    """
    **gpt-5 and o-series models only** Configuration options for
    [reasoning models](https://platform.openai.com/docs/guides/reasoning).
    """

    text: Optional[Text]
    """Configuration options for a text response from the model.

    Can be plain text or structured JSON data. Learn more:

    - [Text inputs and outputs](https://platform.openai.com/docs/guides/text)
    - [Structured Outputs](https://platform.openai.com/docs/guides/structured-outputs)
    """

    tool_choice: Optional[ToolChoice]
    """Controls which tool the model should use, if any."""

    tools: Optional[Iterable[ToolParam]]
    """An array of tools the model may call while generating a response.

    You can specify which tool to use by setting the `tool_choice` parameter.
    """

    truncation: Literal["auto", "disabled"]
    """The truncation strategy to use for the model response.

    - `auto`: If the input to this Response exceeds the model's context window size,
      the model will truncate the response to fit the context window by dropping
      items from the beginning of the conversation. - `disabled` (default): If the
      input size will exceed the context window size for a model, the request will
      fail with a 400 error.
    """


Conversation: TypeAlias = Union[str, ResponseConversationParam]


class Text(TypedDict, total=False):
    """Configuration options for a text response from the model.

    Can be plain
    text or structured JSON data. Learn more:
    - [Text inputs and outputs](https://platform.openai.com/docs/guides/text)
    - [Structured Outputs](https://platform.openai.com/docs/guides/structured-outputs)
    """

    format: ResponseFormatTextConfigParam
    """An object specifying the format that the model must output.

    Configuring `{ "type": "json_schema" }` enables Structured Outputs, which
    ensures the model will match your supplied JSON schema. Learn more in the
    [Structured Outputs guide](https://platform.openai.com/docs/guides/structured-outputs).

    The default format is `{ "type": "text" }` with no additional options.

    **Not recommended for gpt-4o and newer models:**

    Setting to `{ "type": "json_object" }` enables the older JSON mode, which
    ensures the message the model generates is valid JSON. Using `json_schema` is
    preferred for models that support it.
    """

    verbosity: Optional[Literal["low", "medium", "high"]]
    """Constrains the verbosity of the model's response.

    Lower values will result in more concise responses, while higher values will
    result in more verbose responses. Currently supported values are `low`,
    `medium`, and `high`.
    """


ToolChoice: TypeAlias = Union[
    ToolChoiceOptions,
    ToolChoiceAllowedParam,
    ToolChoiceTypesParam,
    ToolChoiceFunctionParam,
    ToolChoiceMcpParam,
    ToolChoiceCustomParam,
    ToolChoiceApplyPatchParam,
    ToolChoiceShellParam,
]
