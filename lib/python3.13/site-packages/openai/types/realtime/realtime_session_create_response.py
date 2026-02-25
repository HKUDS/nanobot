# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Dict, List, Union, Optional
from typing_extensions import Literal, Annotated, TypeAlias

from ..._utils import PropertyInfo
from ..._models import BaseModel
from .audio_transcription import AudioTranscription
from .realtime_truncation import RealtimeTruncation
from .noise_reduction_type import NoiseReductionType
from .realtime_audio_formats import RealtimeAudioFormats
from .realtime_function_tool import RealtimeFunctionTool
from ..responses.response_prompt import ResponsePrompt
from ..responses.tool_choice_mcp import ToolChoiceMcp
from ..responses.tool_choice_options import ToolChoiceOptions
from .realtime_session_client_secret import RealtimeSessionClientSecret
from ..responses.tool_choice_function import ToolChoiceFunction

__all__ = [
    "RealtimeSessionCreateResponse",
    "Audio",
    "AudioInput",
    "AudioInputNoiseReduction",
    "AudioInputTurnDetection",
    "AudioInputTurnDetectionServerVad",
    "AudioInputTurnDetectionSemanticVad",
    "AudioOutput",
    "ToolChoice",
    "Tool",
    "ToolMcpTool",
    "ToolMcpToolAllowedTools",
    "ToolMcpToolAllowedToolsMcpToolFilter",
    "ToolMcpToolRequireApproval",
    "ToolMcpToolRequireApprovalMcpToolApprovalFilter",
    "ToolMcpToolRequireApprovalMcpToolApprovalFilterAlways",
    "ToolMcpToolRequireApprovalMcpToolApprovalFilterNever",
    "Tracing",
    "TracingTracingConfiguration",
]


class AudioInputNoiseReduction(BaseModel):
    """Configuration for input audio noise reduction.

    This can be set to `null` to turn off.
    Noise reduction filters audio added to the input audio buffer before it is sent to VAD and the model.
    Filtering the audio can improve VAD and turn detection accuracy (reducing false positives) and model performance by improving perception of the input audio.
    """

    type: Optional[NoiseReductionType] = None
    """Type of noise reduction.

    `near_field` is for close-talking microphones such as headphones, `far_field` is
    for far-field microphones such as laptop or conference room microphones.
    """


class AudioInputTurnDetectionServerVad(BaseModel):
    """
    Server-side voice activity detection (VAD) which flips on when user speech is detected and off after a period of silence.
    """

    type: Literal["server_vad"]
    """Type of turn detection, `server_vad` to turn on simple Server VAD."""

    create_response: Optional[bool] = None
    """Whether or not to automatically generate a response when a VAD stop event
    occurs.

    If `interrupt_response` is set to `false` this may fail to create a response if
    the model is already responding.

    If both `create_response` and `interrupt_response` are set to `false`, the model
    will never respond automatically but VAD events will still be emitted.
    """

    idle_timeout_ms: Optional[int] = None
    """Optional timeout after which a model response will be triggered automatically.

    This is useful for situations in which a long pause from the user is unexpected,
    such as a phone call. The model will effectively prompt the user to continue the
    conversation based on the current context.

    The timeout value will be applied after the last model response's audio has
    finished playing, i.e. it's set to the `response.done` time plus audio playback
    duration.

    An `input_audio_buffer.timeout_triggered` event (plus events associated with the
    Response) will be emitted when the timeout is reached. Idle timeout is currently
    only supported for `server_vad` mode.
    """

    interrupt_response: Optional[bool] = None
    """
    Whether or not to automatically interrupt (cancel) any ongoing response with
    output to the default conversation (i.e. `conversation` of `auto`) when a VAD
    start event occurs. If `true` then the response will be cancelled, otherwise it
    will continue until complete.

    If both `create_response` and `interrupt_response` are set to `false`, the model
    will never respond automatically but VAD events will still be emitted.
    """

    prefix_padding_ms: Optional[int] = None
    """Used only for `server_vad` mode.

    Amount of audio to include before the VAD detected speech (in milliseconds).
    Defaults to 300ms.
    """

    silence_duration_ms: Optional[int] = None
    """Used only for `server_vad` mode.

    Duration of silence to detect speech stop (in milliseconds). Defaults to 500ms.
    With shorter values the model will respond more quickly, but may jump in on
    short pauses from the user.
    """

    threshold: Optional[float] = None
    """Used only for `server_vad` mode.

    Activation threshold for VAD (0.0 to 1.0), this defaults to 0.5. A higher
    threshold will require louder audio to activate the model, and thus might
    perform better in noisy environments.
    """


class AudioInputTurnDetectionSemanticVad(BaseModel):
    """
    Server-side semantic turn detection which uses a model to determine when the user has finished speaking.
    """

    type: Literal["semantic_vad"]
    """Type of turn detection, `semantic_vad` to turn on Semantic VAD."""

    create_response: Optional[bool] = None
    """
    Whether or not to automatically generate a response when a VAD stop event
    occurs.
    """

    eagerness: Optional[Literal["low", "medium", "high", "auto"]] = None
    """Used only for `semantic_vad` mode.

    The eagerness of the model to respond. `low` will wait longer for the user to
    continue speaking, `high` will respond more quickly. `auto` is the default and
    is equivalent to `medium`. `low`, `medium`, and `high` have max timeouts of 8s,
    4s, and 2s respectively.
    """

    interrupt_response: Optional[bool] = None
    """
    Whether or not to automatically interrupt any ongoing response with output to
    the default conversation (i.e. `conversation` of `auto`) when a VAD start event
    occurs.
    """


AudioInputTurnDetection: TypeAlias = Annotated[
    Union[AudioInputTurnDetectionServerVad, AudioInputTurnDetectionSemanticVad, None],
    PropertyInfo(discriminator="type"),
]


class AudioInput(BaseModel):
    format: Optional[RealtimeAudioFormats] = None
    """The format of the input audio."""

    noise_reduction: Optional[AudioInputNoiseReduction] = None
    """Configuration for input audio noise reduction.

    This can be set to `null` to turn off. Noise reduction filters audio added to
    the input audio buffer before it is sent to VAD and the model. Filtering the
    audio can improve VAD and turn detection accuracy (reducing false positives) and
    model performance by improving perception of the input audio.
    """

    transcription: Optional[AudioTranscription] = None
    """
    Configuration for input audio transcription, defaults to off and can be set to
    `null` to turn off once on. Input audio transcription is not native to the
    model, since the model consumes audio directly. Transcription runs
    asynchronously through
    [the /audio/transcriptions endpoint](https://platform.openai.com/docs/api-reference/audio/createTranscription)
    and should be treated as guidance of input audio content rather than precisely
    what the model heard. The client can optionally set the language and prompt for
    transcription, these offer additional guidance to the transcription service.
    """

    turn_detection: Optional[AudioInputTurnDetection] = None
    """Configuration for turn detection, ether Server VAD or Semantic VAD.

    This can be set to `null` to turn off, in which case the client must manually
    trigger model response.

    Server VAD means that the model will detect the start and end of speech based on
    audio volume and respond at the end of user speech.

    Semantic VAD is more advanced and uses a turn detection model (in conjunction
    with VAD) to semantically estimate whether the user has finished speaking, then
    dynamically sets a timeout based on this probability. For example, if user audio
    trails off with "uhhm", the model will score a low probability of turn end and
    wait longer for the user to continue speaking. This can be useful for more
    natural conversations, but may have a higher latency.
    """


class AudioOutput(BaseModel):
    format: Optional[RealtimeAudioFormats] = None
    """The format of the output audio."""

    speed: Optional[float] = None
    """
    The speed of the model's spoken response as a multiple of the original speed.
    1.0 is the default speed. 0.25 is the minimum speed. 1.5 is the maximum speed.
    This value can only be changed in between model turns, not while a response is
    in progress.

    This parameter is a post-processing adjustment to the audio after it is
    generated, it's also possible to prompt the model to speak faster or slower.
    """

    voice: Union[
        str, Literal["alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse", "marin", "cedar"], None
    ] = None
    """The voice the model uses to respond.

    Voice cannot be changed during the session once the model has responded with
    audio at least once. Current voice options are `alloy`, `ash`, `ballad`,
    `coral`, `echo`, `sage`, `shimmer`, `verse`, `marin`, and `cedar`. We recommend
    `marin` and `cedar` for best quality.
    """


class Audio(BaseModel):
    """Configuration for input and output audio."""

    input: Optional[AudioInput] = None

    output: Optional[AudioOutput] = None


ToolChoice: TypeAlias = Union[ToolChoiceOptions, ToolChoiceFunction, ToolChoiceMcp]


class ToolMcpToolAllowedToolsMcpToolFilter(BaseModel):
    """A filter object to specify which tools are allowed."""

    read_only: Optional[bool] = None
    """Indicates whether or not a tool modifies data or is read-only.

    If an MCP server is
    [annotated with `readOnlyHint`](https://modelcontextprotocol.io/specification/2025-06-18/schema#toolannotations-readonlyhint),
    it will match this filter.
    """

    tool_names: Optional[List[str]] = None
    """List of allowed tool names."""


ToolMcpToolAllowedTools: TypeAlias = Union[List[str], ToolMcpToolAllowedToolsMcpToolFilter, None]


class ToolMcpToolRequireApprovalMcpToolApprovalFilterAlways(BaseModel):
    """A filter object to specify which tools are allowed."""

    read_only: Optional[bool] = None
    """Indicates whether or not a tool modifies data or is read-only.

    If an MCP server is
    [annotated with `readOnlyHint`](https://modelcontextprotocol.io/specification/2025-06-18/schema#toolannotations-readonlyhint),
    it will match this filter.
    """

    tool_names: Optional[List[str]] = None
    """List of allowed tool names."""


class ToolMcpToolRequireApprovalMcpToolApprovalFilterNever(BaseModel):
    """A filter object to specify which tools are allowed."""

    read_only: Optional[bool] = None
    """Indicates whether or not a tool modifies data or is read-only.

    If an MCP server is
    [annotated with `readOnlyHint`](https://modelcontextprotocol.io/specification/2025-06-18/schema#toolannotations-readonlyhint),
    it will match this filter.
    """

    tool_names: Optional[List[str]] = None
    """List of allowed tool names."""


class ToolMcpToolRequireApprovalMcpToolApprovalFilter(BaseModel):
    """Specify which of the MCP server's tools require approval.

    Can be
    `always`, `never`, or a filter object associated with tools
    that require approval.
    """

    always: Optional[ToolMcpToolRequireApprovalMcpToolApprovalFilterAlways] = None
    """A filter object to specify which tools are allowed."""

    never: Optional[ToolMcpToolRequireApprovalMcpToolApprovalFilterNever] = None
    """A filter object to specify which tools are allowed."""


ToolMcpToolRequireApproval: TypeAlias = Union[
    ToolMcpToolRequireApprovalMcpToolApprovalFilter, Literal["always", "never"], None
]


class ToolMcpTool(BaseModel):
    """
    Give the model access to additional tools via remote Model Context Protocol
    (MCP) servers. [Learn more about MCP](https://platform.openai.com/docs/guides/tools-remote-mcp).
    """

    server_label: str
    """A label for this MCP server, used to identify it in tool calls."""

    type: Literal["mcp"]
    """The type of the MCP tool. Always `mcp`."""

    allowed_tools: Optional[ToolMcpToolAllowedTools] = None
    """List of allowed tool names or a filter object."""

    authorization: Optional[str] = None
    """
    An OAuth access token that can be used with a remote MCP server, either with a
    custom MCP server URL or a service connector. Your application must handle the
    OAuth authorization flow and provide the token here.
    """

    connector_id: Optional[
        Literal[
            "connector_dropbox",
            "connector_gmail",
            "connector_googlecalendar",
            "connector_googledrive",
            "connector_microsoftteams",
            "connector_outlookcalendar",
            "connector_outlookemail",
            "connector_sharepoint",
        ]
    ] = None
    """Identifier for service connectors, like those available in ChatGPT.

    One of `server_url` or `connector_id` must be provided. Learn more about service
    connectors
    [here](https://platform.openai.com/docs/guides/tools-remote-mcp#connectors).

    Currently supported `connector_id` values are:

    - Dropbox: `connector_dropbox`
    - Gmail: `connector_gmail`
    - Google Calendar: `connector_googlecalendar`
    - Google Drive: `connector_googledrive`
    - Microsoft Teams: `connector_microsoftteams`
    - Outlook Calendar: `connector_outlookcalendar`
    - Outlook Email: `connector_outlookemail`
    - SharePoint: `connector_sharepoint`
    """

    headers: Optional[Dict[str, str]] = None
    """Optional HTTP headers to send to the MCP server.

    Use for authentication or other purposes.
    """

    require_approval: Optional[ToolMcpToolRequireApproval] = None
    """Specify which of the MCP server's tools require approval."""

    server_description: Optional[str] = None
    """Optional description of the MCP server, used to provide more context."""

    server_url: Optional[str] = None
    """The URL for the MCP server.

    One of `server_url` or `connector_id` must be provided.
    """


Tool: TypeAlias = Union[RealtimeFunctionTool, ToolMcpTool]


class TracingTracingConfiguration(BaseModel):
    """Granular configuration for tracing."""

    group_id: Optional[str] = None
    """
    The group id to attach to this trace to enable filtering and grouping in the
    Traces Dashboard.
    """

    metadata: Optional[object] = None
    """
    The arbitrary metadata to attach to this trace to enable filtering in the Traces
    Dashboard.
    """

    workflow_name: Optional[str] = None
    """The name of the workflow to attach to this trace.

    This is used to name the trace in the Traces Dashboard.
    """


Tracing: TypeAlias = Union[Literal["auto"], TracingTracingConfiguration, None]


class RealtimeSessionCreateResponse(BaseModel):
    """A new Realtime session configuration, with an ephemeral key.

    Default TTL
    for keys is one minute.
    """

    client_secret: RealtimeSessionClientSecret
    """Ephemeral key returned by the API."""

    type: Literal["realtime"]
    """The type of session to create. Always `realtime` for the Realtime API."""

    audio: Optional[Audio] = None
    """Configuration for input and output audio."""

    include: Optional[List[Literal["item.input_audio_transcription.logprobs"]]] = None
    """Additional fields to include in server outputs.

    `item.input_audio_transcription.logprobs`: Include logprobs for input audio
    transcription.
    """

    instructions: Optional[str] = None
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

    max_output_tokens: Union[int, Literal["inf"], None] = None
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
        None,
    ] = None
    """The Realtime model used for this session."""

    output_modalities: Optional[List[Literal["text", "audio"]]] = None
    """The set of modalities the model can respond with.

    It defaults to `["audio"]`, indicating that the model will respond with audio
    plus a transcript. `["text"]` can be used to make the model respond with text
    only. It is not possible to request both `text` and `audio` at the same time.
    """

    prompt: Optional[ResponsePrompt] = None
    """
    Reference to a prompt template and its variables.
    [Learn more](https://platform.openai.com/docs/guides/text?api-mode=responses#reusable-prompts).
    """

    tool_choice: Optional[ToolChoice] = None
    """How the model chooses tools.

    Provide one of the string modes or force a specific function/MCP tool.
    """

    tools: Optional[List[Tool]] = None
    """Tools available to the model."""

    tracing: Optional[Tracing] = None
    """
    Realtime API can write session traces to the
    [Traces Dashboard](/logs?api=traces). Set to null to disable tracing. Once
    tracing is enabled for a session, the configuration cannot be modified.

    `auto` will create a trace for the session with default values for the workflow
    name, group id, and metadata.
    """

    truncation: Optional[RealtimeTruncation] = None
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
