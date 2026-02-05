# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Union
from typing_extensions import TypeAlias

from .session_update_event_param import SessionUpdateEventParam
from .response_cancel_event_param import ResponseCancelEventParam
from .response_create_event_param import ResponseCreateEventParam
from .conversation_item_create_event_param import ConversationItemCreateEventParam
from .conversation_item_delete_event_param import ConversationItemDeleteEventParam
from .input_audio_buffer_clear_event_param import InputAudioBufferClearEventParam
from .input_audio_buffer_append_event_param import InputAudioBufferAppendEventParam
from .input_audio_buffer_commit_event_param import InputAudioBufferCommitEventParam
from .output_audio_buffer_clear_event_param import OutputAudioBufferClearEventParam
from .conversation_item_retrieve_event_param import ConversationItemRetrieveEventParam
from .conversation_item_truncate_event_param import ConversationItemTruncateEventParam

__all__ = ["RealtimeClientEventParam"]

RealtimeClientEventParam: TypeAlias = Union[
    ConversationItemCreateEventParam,
    ConversationItemDeleteEventParam,
    ConversationItemRetrieveEventParam,
    ConversationItemTruncateEventParam,
    InputAudioBufferAppendEventParam,
    InputAudioBufferClearEventParam,
    OutputAudioBufferClearEventParam,
    InputAudioBufferCommitEventParam,
    ResponseCancelEventParam,
    ResponseCreateEventParam,
    SessionUpdateEventParam,
]
