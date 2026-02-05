# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import List, Union, Iterable, Optional
from typing_extensions import Literal, TypeAlias, TypedDict

from ..shared_params.metadata import Metadata
from .conversation_item_param import ConversationItemParam
from .realtime_function_tool_param import RealtimeFunctionToolParam
from ..responses.tool_choice_options import ToolChoiceOptions
from ..responses.response_prompt_param import ResponsePromptParam
from ..responses.tool_choice_mcp_param import ToolChoiceMcpParam
from ..responses.tool_choice_function_param import ToolChoiceFunctionParam
from .realtime_response_create_mcp_tool_param import RealtimeResponseCreateMcpToolParam
from .realtime_response_create_audio_output_param import RealtimeResponseCreateAudioOutputParam

__all__ = ["RealtimeResponseCreateParamsParam", "ToolChoice", "Tool"]

ToolChoice: TypeAlias = Union[ToolChoiceOptions, ToolChoiceFunctionParam, ToolChoiceMcpParam]

Tool: TypeAlias = Union[RealtimeFunctionToolParam, RealtimeResponseCreateMcpToolParam]


class RealtimeResponseCreateParamsParam(TypedDict, total=False):
    """Create a new Realtime response with these parameters"""

    audio: RealtimeResponseCreateAudioOutputParam
    """Configuration for audio input and output."""

    conversation: Union[str, Literal["auto", "none"]]
    """Controls which conversation the response is added to.

    Currently supports `auto` and `none`, with `auto` as the default value. The
    `auto` value means that the contents of the response will be added to the
    default conversation. Set this to `none` to create an out-of-band response which
    will not add items to default conversation.
    """

    input: Iterable[ConversationItemParam]
    """Input items to include in the prompt for the model.

    Using this field creates a new context for this Response instead of using the
    default conversation. An empty array `[]` will clear the context for this
    Response. Note that this can include references to items that previously
    appeared in the session using their id.
    """

    instructions: str
    """The default system instructions (i.e.

    system message) prepended to model calls. This field allows the client to guide
    the model on desired responses. The model can be instructed on response content
    and format, (e.g. "be extremely succinct", "act friendly", "here are examples of
    good responses") and on audio behavior (e.g. "talk quickly", "inject emotion
    into your voice", "laugh frequently"). The instructions are not guaranteed to be
    followed by the model, but they provide guidance to the model on the desired
    behavior. Note that the server sets default instructions which will be used if
    this field is not set and are visible in the `session.created` event at the
    start of the session.
    """

    max_output_tokens: Union[int, Literal["inf"]]
    """
    Maximum number of output tokens for a single assistant response, inclusive of
    tool calls. Provide an integer between 1 and 4096 to limit output tokens, or
    `inf` for the maximum available tokens for a given model. Defaults to `inf`.
    """

    metadata: Optional[Metadata]
    """Set of 16 key-value pairs that can be attached to an object.

    This can be useful for storing additional information about the object in a
    structured format, and querying for objects via API or the dashboard.

    Keys are strings with a maximum length of 64 characters. Values are strings with
    a maximum length of 512 characters.
    """

    output_modalities: List[Literal["text", "audio"]]
    """
    The set of modalities the model used to respond, currently the only possible
    values are `[\"audio\"]`, `[\"text\"]`. Audio output always include a text
    transcript. Setting the output to mode `text` will disable audio output from the
    model.
    """

    prompt: Optional[ResponsePromptParam]
    """
    Reference to a prompt template and its variables.
    [Learn more](https://platform.openai.com/docs/guides/text?api-mode=responses#reusable-prompts).
    """

    tool_choice: ToolChoice
    """How the model chooses tools.

    Provide one of the string modes or force a specific function/MCP tool.
    """

    tools: Iterable[Tool]
    """Tools available to the model."""
