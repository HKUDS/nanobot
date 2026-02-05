# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Union, Optional
from typing_extensions import Literal, Annotated, TypeAlias

from ..._utils import PropertyInfo
from ..._models import BaseModel

__all__ = ["RealtimeAudioInputTurnDetection", "ServerVad", "SemanticVad"]


class ServerVad(BaseModel):
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


class SemanticVad(BaseModel):
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


RealtimeAudioInputTurnDetection: TypeAlias = Annotated[
    Union[ServerVad, SemanticVad, None], PropertyInfo(discriminator="type")
]
