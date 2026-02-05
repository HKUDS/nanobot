# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Optional

from ..._models import BaseModel

__all__ = ["RealtimeTranscriptionSessionTurnDetection"]


class RealtimeTranscriptionSessionTurnDetection(BaseModel):
    """Configuration for turn detection.

    Can be set to `null` to turn off. Server
    VAD means that the model will detect the start and end of speech based on
    audio volume and respond at the end of user speech.
    """

    prefix_padding_ms: Optional[int] = None
    """Amount of audio to include before the VAD detected speech (in milliseconds).

    Defaults to 300ms.
    """

    silence_duration_ms: Optional[int] = None
    """Duration of silence to detect speech stop (in milliseconds).

    Defaults to 500ms. With shorter values the model will respond more quickly, but
    may jump in on short pauses from the user.
    """

    threshold: Optional[float] = None
    """Activation threshold for VAD (0.0 to 1.0), this defaults to 0.5.

    A higher threshold will require louder audio to activate the model, and thus
    might perform better in noisy environments.
    """

    type: Optional[str] = None
    """Type of turn detection, only `server_vad` is currently supported."""
