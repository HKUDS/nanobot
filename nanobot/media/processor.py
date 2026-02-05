"""Media processor: preprocesses media items before context building."""

from dataclasses import dataclass, field

from loguru import logger

from nanobot.media.transcription import GroqTranscriptionProvider


@dataclass
class ProcessedMedia:
    """Result of media preprocessing."""

    media: list[dict[str, str]] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)


class MediaProcessor:
    """
    Preprocesses media items before context building.

    Converts media into text when possible (e.g., audio transcription),
    passing remaining items through for native LLM handling.
    """

    def __init__(self, groq_api_key: str | None = None):
        self.transcriber = (
            GroqTranscriptionProvider(api_key=groq_api_key) if groq_api_key else None
        )

    async def process(self, media: list[dict[str, str]]) -> ProcessedMedia:
        """Process media items, converting to text where possible."""
        if not media:
            return ProcessedMedia()

        remaining: list[dict[str, str]] = []
        text_parts: list[str] = []

        for item in media:
            media_type = item.get("type", "")
            url = item.get("url", "")

            if media_type in ("voice", "audio") and self.transcriber:
                text = await self.transcriber.transcribe(url)
                if text:
                    logger.info(f"Transcribed {media_type}: {text[:50]}...")
                    text_parts.append(text)
                    continue
                logger.warning(f"Transcription failed for {media_type}, passing to LLM")

            remaining.append(item)

        return ProcessedMedia(media=remaining, text_parts=text_parts)
