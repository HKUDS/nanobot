"""Voice transcription via multimodal LLM completion."""

import base64
import os
from typing import Protocol, runtime_checkable

from loguru import logger

# Maximum audio duration to attempt transcription (5 minutes in seconds)
MAX_AUDIO_DURATION_SECONDS = 5 * 60

DEFAULT_TRANSCRIPTION_MODEL = "gemini/gemini-2.5-flash"

TRANSCRIPTION_PROMPT = (
    "Transcribe the following audio message exactly as spoken. "
    "Return only the transcript text with no additional commentary."
)


@runtime_checkable
class TranscriptionProvider(Protocol):
    """Standard interface for voice transcription providers.

    Channels depend only on this interface — they never import or instantiate
    a concrete provider directly.  The provider is constructed by the channel
    manager and injected at startup.
    """

    async def transcribe(
        self,
        audio_bytes: bytes,
        mime_type: str = "audio/ogg",
        duration_seconds: float | None = None,
    ) -> str:
        """Transcribe raw audio bytes.

        Args:
            audio_bytes: Raw audio data.
            mime_type: MIME type of the audio (e.g. "audio/ogg", "audio/mpeg").
            duration_seconds: Optional known duration for length-gating.

        Returns:
            Transcribed text, or a sentinel string on error/overflow.
        """
        ...


class VoiceTranscriptionProvider:
    """Transcribes voice messages using any multimodal model via LiteLLM.

    Audio bytes are passed as a data-URI in the message content — no
    provider-specific SDK required.  Any model LiteLLM supports that
    accepts multimodal input works here (Gemini, GPT-4o, Claude, etc.).

    Configuration is intentionally minimal: just a model name and an
    optional API key.  If no key is supplied, LiteLLM resolves it from
    the environment (e.g. GEMINI_API_KEY, OPENAI_API_KEY) as usual.
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
    ):
        self.model = model
        self.api_key = api_key or None  # None → LiteLLM reads from env

    async def transcribe(
        self,
        audio_bytes: bytes,
        mime_type: str = "audio/ogg",
        duration_seconds: float | None = None,
    ) -> str:
        if duration_seconds is not None and duration_seconds > MAX_AUDIO_DURATION_SECONDS:
            logger.info(
                "Voice message duration {}s exceeds {}s limit — skipping transcription",
                duration_seconds,
                MAX_AUDIO_DURATION_SECONDS,
            )
            return "[Voice message too long - please type it out]"

        try:
            import litellm

            audio_b64 = base64.b64encode(audio_bytes).decode()
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": TRANSCRIPTION_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{audio_b64}"},
                        },
                    ],
                }
            ]

            kwargs: dict = {"model": self.model, "messages": messages}
            if self.api_key:
                kwargs["api_key"] = self.api_key

            response = await litellm.acompletion(**kwargs)
            transcript = response.choices[0].message.content or ""
            return transcript.strip()

        except Exception as e:
            logger.error("Voice transcription error (model={}): {}", self.model, e)
            return "[Voice message - transcription failed]"


def create_transcription_provider(
    model: str | None = None,
    api_key: str | None = None,
) -> VoiceTranscriptionProvider | None:
    """Build a VoiceTranscriptionProvider from config/env.

    Transcription is opt-in: if no model is configured (config or env), it is
    disabled and voice messages are left as a placeholder.

    Args:
        model: Model name in LiteLLM format (e.g. "gemini/gemini-2.5-flash").
               Falls back to VOICE_TRANSCRIPTION_MODEL env var.
               Pass "disabled" to explicitly disable transcription.
        api_key: API key for the transcription model.  If omitted, LiteLLM
                 resolves it from the environment automatically.

    Returns:
        A VoiceTranscriptionProvider, or None if transcription is not configured.
    """
    resolved_model = model or os.environ.get("VOICE_TRANSCRIPTION_MODEL")

    if not resolved_model or resolved_model.lower() == "disabled":
        logger.info("Voice transcription disabled")
        return None

    logger.info("Voice transcription: model={}", resolved_model)
    return VoiceTranscriptionProvider(model=resolved_model, api_key=api_key or None)
