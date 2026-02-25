# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Union
from typing_extensions import Literal, Annotated, TypeAlias

from ..._utils import PropertyInfo
from ..._models import BaseModel
from .conversation_item import ConversationItem
from .response_done_event import ResponseDoneEvent
from .realtime_error_event import RealtimeErrorEvent
from .mcp_list_tools_failed import McpListToolsFailed
from .session_created_event import SessionCreatedEvent
from .session_updated_event import SessionUpdatedEvent
from .conversation_item_done import ConversationItemDone
from .response_created_event import ResponseCreatedEvent
from .conversation_item_added import ConversationItemAdded
from .mcp_list_tools_completed import McpListToolsCompleted
from .response_mcp_call_failed import ResponseMcpCallFailed
from .response_text_done_event import ResponseTextDoneEvent
from .rate_limits_updated_event import RateLimitsUpdatedEvent
from .response_audio_done_event import ResponseAudioDoneEvent
from .response_text_delta_event import ResponseTextDeltaEvent
from .conversation_created_event import ConversationCreatedEvent
from .mcp_list_tools_in_progress import McpListToolsInProgress
from .response_audio_delta_event import ResponseAudioDeltaEvent
from .response_mcp_call_completed import ResponseMcpCallCompleted
from .response_mcp_call_in_progress import ResponseMcpCallInProgress
from .conversation_item_created_event import ConversationItemCreatedEvent
from .conversation_item_deleted_event import ConversationItemDeletedEvent
from .response_output_item_done_event import ResponseOutputItemDoneEvent
from .input_audio_buffer_cleared_event import InputAudioBufferClearedEvent
from .response_content_part_done_event import ResponseContentPartDoneEvent
from .response_mcp_call_arguments_done import ResponseMcpCallArgumentsDone
from .response_output_item_added_event import ResponseOutputItemAddedEvent
from .conversation_item_truncated_event import ConversationItemTruncatedEvent
from .response_content_part_added_event import ResponseContentPartAddedEvent
from .response_mcp_call_arguments_delta import ResponseMcpCallArgumentsDelta
from .input_audio_buffer_committed_event import InputAudioBufferCommittedEvent
from .input_audio_buffer_timeout_triggered import InputAudioBufferTimeoutTriggered
from .response_audio_transcript_done_event import ResponseAudioTranscriptDoneEvent
from .response_audio_transcript_delta_event import ResponseAudioTranscriptDeltaEvent
from .input_audio_buffer_speech_started_event import InputAudioBufferSpeechStartedEvent
from .input_audio_buffer_speech_stopped_event import InputAudioBufferSpeechStoppedEvent
from .response_function_call_arguments_done_event import ResponseFunctionCallArgumentsDoneEvent
from .input_audio_buffer_dtmf_event_received_event import InputAudioBufferDtmfEventReceivedEvent
from .response_function_call_arguments_delta_event import ResponseFunctionCallArgumentsDeltaEvent
from .conversation_item_input_audio_transcription_segment import ConversationItemInputAudioTranscriptionSegment
from .conversation_item_input_audio_transcription_delta_event import ConversationItemInputAudioTranscriptionDeltaEvent
from .conversation_item_input_audio_transcription_failed_event import ConversationItemInputAudioTranscriptionFailedEvent
from .conversation_item_input_audio_transcription_completed_event import (
    ConversationItemInputAudioTranscriptionCompletedEvent,
)

__all__ = [
    "RealtimeServerEvent",
    "ConversationItemRetrieved",
    "OutputAudioBufferStarted",
    "OutputAudioBufferStopped",
    "OutputAudioBufferCleared",
]


class ConversationItemRetrieved(BaseModel):
    """Returned when a conversation item is retrieved with `conversation.item.retrieve`.

    This is provided as a way to fetch the server's representation of an item, for example to get access to the post-processed audio data after noise cancellation and VAD. It includes the full content of the Item, including audio data.
    """

    event_id: str
    """The unique ID of the server event."""

    item: ConversationItem
    """A single item within a Realtime conversation."""

    type: Literal["conversation.item.retrieved"]
    """The event type, must be `conversation.item.retrieved`."""


class OutputAudioBufferStarted(BaseModel):
    """
    **WebRTC/SIP Only:** Emitted when the server begins streaming audio to the client. This event is
    emitted after an audio content part has been added (`response.content_part.added`)
    to the response.
    [Learn more](https://platform.openai.com/docs/guides/realtime-conversations#client-and-server-events-for-audio-in-webrtc).
    """

    event_id: str
    """The unique ID of the server event."""

    response_id: str
    """The unique ID of the response that produced the audio."""

    type: Literal["output_audio_buffer.started"]
    """The event type, must be `output_audio_buffer.started`."""


class OutputAudioBufferStopped(BaseModel):
    """
    **WebRTC/SIP Only:** Emitted when the output audio buffer has been completely drained on the server,
    and no more audio is forthcoming. This event is emitted after the full response
    data has been sent to the client (`response.done`).
    [Learn more](https://platform.openai.com/docs/guides/realtime-conversations#client-and-server-events-for-audio-in-webrtc).
    """

    event_id: str
    """The unique ID of the server event."""

    response_id: str
    """The unique ID of the response that produced the audio."""

    type: Literal["output_audio_buffer.stopped"]
    """The event type, must be `output_audio_buffer.stopped`."""


class OutputAudioBufferCleared(BaseModel):
    """**WebRTC/SIP Only:** Emitted when the output audio buffer is cleared.

    This happens either in VAD
    mode when the user has interrupted (`input_audio_buffer.speech_started`),
    or when the client has emitted the `output_audio_buffer.clear` event to manually
    cut off the current audio response.
    [Learn more](https://platform.openai.com/docs/guides/realtime-conversations#client-and-server-events-for-audio-in-webrtc).
    """

    event_id: str
    """The unique ID of the server event."""

    response_id: str
    """The unique ID of the response that produced the audio."""

    type: Literal["output_audio_buffer.cleared"]
    """The event type, must be `output_audio_buffer.cleared`."""


RealtimeServerEvent: TypeAlias = Annotated[
    Union[
        ConversationCreatedEvent,
        ConversationItemCreatedEvent,
        ConversationItemDeletedEvent,
        ConversationItemInputAudioTranscriptionCompletedEvent,
        ConversationItemInputAudioTranscriptionDeltaEvent,
        ConversationItemInputAudioTranscriptionFailedEvent,
        ConversationItemRetrieved,
        ConversationItemTruncatedEvent,
        RealtimeErrorEvent,
        InputAudioBufferClearedEvent,
        InputAudioBufferCommittedEvent,
        InputAudioBufferDtmfEventReceivedEvent,
        InputAudioBufferSpeechStartedEvent,
        InputAudioBufferSpeechStoppedEvent,
        RateLimitsUpdatedEvent,
        ResponseAudioDeltaEvent,
        ResponseAudioDoneEvent,
        ResponseAudioTranscriptDeltaEvent,
        ResponseAudioTranscriptDoneEvent,
        ResponseContentPartAddedEvent,
        ResponseContentPartDoneEvent,
        ResponseCreatedEvent,
        ResponseDoneEvent,
        ResponseFunctionCallArgumentsDeltaEvent,
        ResponseFunctionCallArgumentsDoneEvent,
        ResponseOutputItemAddedEvent,
        ResponseOutputItemDoneEvent,
        ResponseTextDeltaEvent,
        ResponseTextDoneEvent,
        SessionCreatedEvent,
        SessionUpdatedEvent,
        OutputAudioBufferStarted,
        OutputAudioBufferStopped,
        OutputAudioBufferCleared,
        ConversationItemAdded,
        ConversationItemDone,
        InputAudioBufferTimeoutTriggered,
        ConversationItemInputAudioTranscriptionSegment,
        McpListToolsInProgress,
        McpListToolsCompleted,
        McpListToolsFailed,
        ResponseMcpCallArgumentsDelta,
        ResponseMcpCallArgumentsDone,
        ResponseMcpCallInProgress,
        ResponseMcpCallCompleted,
        ResponseMcpCallFailed,
    ],
    PropertyInfo(discriminator="type"),
]
