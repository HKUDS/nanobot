# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Union
from typing_extensions import Annotated, TypeAlias

from ..._utils import PropertyInfo
from .session_update_event import SessionUpdateEvent
from .response_cancel_event import ResponseCancelEvent
from .response_create_event import ResponseCreateEvent
from .conversation_item_create_event import ConversationItemCreateEvent
from .conversation_item_delete_event import ConversationItemDeleteEvent
from .input_audio_buffer_clear_event import InputAudioBufferClearEvent
from .input_audio_buffer_append_event import InputAudioBufferAppendEvent
from .input_audio_buffer_commit_event import InputAudioBufferCommitEvent
from .output_audio_buffer_clear_event import OutputAudioBufferClearEvent
from .conversation_item_retrieve_event import ConversationItemRetrieveEvent
from .conversation_item_truncate_event import ConversationItemTruncateEvent

__all__ = ["RealtimeClientEvent"]

RealtimeClientEvent: TypeAlias = Annotated[
    Union[
        ConversationItemCreateEvent,
        ConversationItemDeleteEvent,
        ConversationItemRetrieveEvent,
        ConversationItemTruncateEvent,
        InputAudioBufferAppendEvent,
        InputAudioBufferClearEvent,
        OutputAudioBufferClearEvent,
        InputAudioBufferCommitEvent,
        ResponseCancelEvent,
        ResponseCreateEvent,
        SessionUpdateEvent,
    ],
    PropertyInfo(discriminator="type"),
]
