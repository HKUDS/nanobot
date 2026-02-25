# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Union
from typing_extensions import Annotated, TypeAlias

from ..._utils import PropertyInfo
from .transcription_text_done_event import TranscriptionTextDoneEvent
from .transcription_text_delta_event import TranscriptionTextDeltaEvent
from .transcription_text_segment_event import TranscriptionTextSegmentEvent

__all__ = ["TranscriptionStreamEvent"]

TranscriptionStreamEvent: TypeAlias = Annotated[
    Union[TranscriptionTextSegmentEvent, TranscriptionTextDeltaEvent, TranscriptionTextDoneEvent],
    PropertyInfo(discriminator="type"),
]
