# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import List, Union, Optional
from typing_extensions import Literal, Required, TypedDict

from .realtime_truncation_param import RealtimeTruncationParam
from .realtime_audio_config_param import RealtimeAudioConfigParam
from .realtime_tools_config_param import RealtimeToolsConfigParam
from .realtime_tracing_config_param import RealtimeTracingConfigParam
from ..responses.response_prompt_param import ResponsePromptParam
from .realtime_tool_choice_config_param import RealtimeToolChoiceConfigParam

__all__ = ["RealtimeSessionCreateRequestParam"]


class RealtimeSessionCreateRequestParam(TypedDict, total=False):
    """Realtime session object configuration."""

    type: Required[Literal["realtime"]]
    """The type of session to create. Always `realtime` for the Realtime API."""

    audio: RealtimeAudioConfigParam
    """Configuration for input and output audio."""

    include: List[Literal["item.input_audio_transcription.logprobs"]]
    """Additional fields to include in server outputs.

    `item.input_audio_transcription.logprobs`: Include logprobs for input audio
    transcription.
    """

    instructions: str
    """The default system instructions (i.e.

    system message) prepended to model calls. This field allows the client to guide
    the model on desired responses. The model can be instructed on response content
    and format, (e.g. "be extremely succinct", "act friendly", "here are examples of
    good responses") and on audio behavior (e.g. "talk quickly", "inject emotion
    into your voice", "laugh frequently"). The instructions are not guaranteed to be
    followed by the model, but they provide guidance to the model on the desired
    behavior.

    Note that the server sets default instructions which will be used if this field
    is not set and are visible in the `session.created` event at the start of the
    session.
    """

    max_output_tokens: Union[int, Literal["inf"]]
    """
    Maximum number of output tokens for a single assistant response, inclusive of
    tool calls. Provide an integer between 1 and 4096 to limit output tokens, or
    `inf` for the maximum available tokens for a given model. Defaults to `inf`.
    """

    model: Union[
        str,
        Literal[
            "gpt-realtime",
            "gpt-realtime-2025-08-28",
            "gpt-4o-realtime-preview",
            "gpt-4o-realtime-preview-2024-10-01",
            "gpt-4o-realtime-preview-2024-12-17",
            "gpt-4o-realtime-preview-2025-06-03",
            "gpt-4o-mini-realtime-preview",
            "gpt-4o-mini-realtime-preview-2024-12-17",
            "gpt-realtime-mini",
            "gpt-realtime-mini-2025-10-06",
            "gpt-realtime-mini-2025-12-15",
            "gpt-audio-mini",
            "gpt-audio-mini-2025-10-06",
            "gpt-audio-mini-2025-12-15",
        ],
    ]
    """The Realtime model used for this session."""

    output_modalities: List[Literal["text", "audio"]]
    """The set of modalities the model can respond with.

    It defaults to `["audio"]`, indicating that the model will respond with audio
    plus a transcript. `["text"]` can be used to make the model respond with text
    only. It is not possible to request both `text` and `audio` at the same time.
    """

    prompt: Optional[ResponsePromptParam]
    """
    Reference to a prompt template and its variables.
    [Learn more](https://platform.openai.com/docs/guides/text?api-mode=responses#reusable-prompts).
    """

    tool_choice: RealtimeToolChoiceConfigParam
    """How the model chooses tools.

    Provide one of the string modes or force a specific function/MCP tool.
    """

    tools: RealtimeToolsConfigParam
    """Tools available to the model."""

    tracing: Optional[RealtimeTracingConfigParam]
    """
    Realtime API can write session traces to the
    [Traces Dashboard](/logs?api=traces). Set to null to disable tracing. Once
    tracing is enabled for a session, the configuration cannot be modified.

    `auto` will create a trace for the session with default values for the workflow
    name, group id, and metadata.
    """

    truncation: RealtimeTruncationParam
    """
    When the number of tokens in a conversation exceeds the model's input token
    limit, the conversation be truncated, meaning messages (starting from the
    oldest) will not be included in the model's context. A 32k context model with
    4,096 max output tokens can only include 28,224 tokens in the context before
    truncation occurs.

    Clients can configure truncation behavior to truncate with a lower max token
    limit, which is an effective way to control token usage and cost.

    Truncation will reduce the number of cached tokens on the next turn (busting the
    cache), since messages are dropped from the beginning of the context. However,
    clients can also configure truncation to retain messages up to a fraction of the
    maximum context size, which will reduce the need for future truncations and thus
    improve the cache rate.

    Truncation can be disabled entirely, which means the server will never truncate
    but would instead return an error if the conversation exceeds the model's input
    token limit.
    """
