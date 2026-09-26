"""MiniMax music generation tool."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.schema import (
    BooleanSchema,
    IntegerSchema,
    ObjectSchema,
    StringSchema,
    tool_parameters_schema,
)
from nanobot.config_base import Base
from nanobot.providers.music_generation import (
    MUSIC_AUDIO_FORMATS,
    MUSIC_BITRATES,
    MUSIC_MODELS,
    MUSIC_SAMPLE_RATES,
    MiniMaxMusicGenerationClient,
    MusicGenerationError,
    MusicOutputFormat,
)
from nanobot.utils.artifacts import (
    ArtifactError,
    generated_audio_tool_result,
    store_generated_audio_artifact,
)

if TYPE_CHECKING:
    from nanobot.agent.tools.context import ToolContext
    from nanobot.config.schema import ProviderConfig


class MusicGenerationToolConfig(Base):
    """Music generation tool configuration."""

    enabled: bool = False
    provider: str = "minimax"
    model: str = "music-3.0"
    default_output_format: Literal["url", "hex"] = "hex"
    default_audio_format: Literal["mp3", "wav", "pcm"] = "mp3"
    default_sample_rate: Literal[16000, 24000, 32000, 44100] = 44100
    default_bitrate: Literal[32000, 64000, 128000, 256000] = 256000
    save_dir: str = "generated"


@tool_parameters(
    tool_parameters_schema(
        model=StringSchema(
            "Optional MiniMax music model override.",
            enum=MUSIC_MODELS,
        ),
        prompt=StringSchema(
            "Music style, mood, and scenario. Required for instrumental generation and covers.",
            max_length=2000,
        ),
        lyrics=StringSchema(
            "Lyrics with optional structure tags such as [Verse] and [Chorus].",
            max_length=3500,
        ),
        stream=BooleanSchema(
            description="Stream hexadecimal audio chunks before returning the completed artifact.",
        ),
        output_format=StringSchema(
            "Provider output format. Streaming requires hex.",
            enum=("url", "hex"),
        ),
        audio_setting=ObjectSchema(
            sample_rate=IntegerSchema(
                description="Audio sample rate.",
                enum=MUSIC_SAMPLE_RATES,
            ),
            bitrate=IntegerSchema(
                description="Audio bitrate.",
                enum=MUSIC_BITRATES,
            ),
            format=StringSchema(
                "Audio file format.",
                enum=MUSIC_AUDIO_FORMATS,
            ),
            description="Optional output audio settings.",
            additional_properties=False,
        ),
        lyrics_optimizer=BooleanSchema(
            description="Generate lyrics from the prompt when lyrics are omitted.",
        ),
        is_instrumental=BooleanSchema(
            description="Generate instrumental music without vocals.",
        ),
        audio_url=StringSchema(
            "Reference audio URL for a music cover model. Mutually exclusive with other cover inputs.",
        ),
        audio_base64=StringSchema(
            "Base64 reference audio for a music cover model. Maximum decoded size is 50 MB.",
        ),
        cover_feature_id=StringSchema(
            "Preprocessed cover feature ID. Mutually exclusive with direct audio inputs.",
        ),
        aigc_watermark=BooleanSchema(
            description="Add the mainland China endpoint audio watermark for non-streaming output.",
        ),
    )
)
class MusicGenerationTool(Tool):
    """Generate music through the configured MiniMax provider."""

    config_key = "music_generation"

    @classmethod
    def config_cls(cls):
        return MusicGenerationToolConfig

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return ctx.config.music_generation.enabled

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        return cls(
            config=ctx.config.music_generation,
            provider_configs=ctx.media_generation_provider_configs,
        )

    def __init__(
        self,
        *,
        config: MusicGenerationToolConfig,
        provider_config: ProviderConfig | None = None,
        provider_configs: dict[str, ProviderConfig] | None = None,
    ) -> None:
        self.config = config
        self.provider_configs = dict(provider_configs or {})
        if provider_config is not None and "minimax" not in self.provider_configs:
            self.provider_configs["minimax"] = provider_config

    @property
    def name(self) -> str:
        return "generate_music"

    @property
    def description(self) -> str:
        return (
            "Generate music or a music cover with MiniMax. Returns a persistent local audio "
            "artifact for hex output or a 24-hour provider URL for URL output. Use the message "
            "tool with the returned path or URL in media to deliver the audio."
        )

    def _provider_client(self) -> MiniMaxMusicGenerationClient | None:
        if self.config.provider != "minimax":
            return None
        provider = self.provider_configs.get("minimax")
        return MiniMaxMusicGenerationClient(
            api_key=provider.api_key if provider and isinstance(provider.api_key, str) else None,
            api_base=provider.api_base if provider and isinstance(provider.api_base, str) else None,
            extra_headers=(
                provider.extra_headers
                if provider and isinstance(provider.extra_headers, dict)
                else None
            ),
            extra_body=(
                provider.extra_body if provider and isinstance(provider.extra_body, dict) else None
            ),
            proxy=provider.proxy if provider and isinstance(provider.proxy, str) else None,
        )

    async def execute(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        model: str | None = None,
        prompt: str | None = None,
        lyrics: str | None = None,
        stream: bool = False,
        output_format: MusicOutputFormat | None = None,
        audio_setting: dict[str, Any] | None = None,
        lyrics_optimizer: bool = False,
        is_instrumental: bool = False,
        audio_url: str | None = None,
        audio_base64: str | None = None,
        cover_feature_id: str | None = None,
        aigc_watermark: bool | None = None,
        **kwargs: Any,
    ) -> str:
        client = self._provider_client()
        if client is None:
            return ToolResult.error(
                f"Error: unsupported music generation provider '{self.config.provider}'"
            )

        selected_model = model or self.config.model
        selected_output_format = output_format or self.config.default_output_format
        settings: dict[str, Any] = {
            "sample_rate": self.config.default_sample_rate,
            "bitrate": self.config.default_bitrate,
            "format": self.config.default_audio_format,
        }
        settings.update(audio_setting or {})

        try:
            response = await client.generate(
                model=selected_model,
                prompt=prompt,
                lyrics=lyrics,
                stream=stream,
                output_format=selected_output_format,
                audio_setting=settings,
                lyrics_optimizer=lyrics_optimizer,
                is_instrumental=is_instrumental,
                audio_url=audio_url,
                audio_base64=audio_base64,
                cover_feature_id=cover_feature_id,
                aigc_watermark=aigc_watermark,
            )
            if response.output_format == "url":
                artifact = {
                    "url": response.audio,
                    "model": selected_model,
                    "provider": self.config.provider,
                    "output_format": "url",
                    "expires_in_hours": 24,
                }
            else:
                audio_format = settings.get("format")
                if not isinstance(audio_format, str):
                    raise ArtifactError("audio format must be a string")
                artifact = store_generated_audio_artifact(
                    response.audio,
                    prompt=prompt,
                    lyrics=lyrics,
                    model=selected_model,
                    audio_format=audio_format,
                    save_dir=self.config.save_dir,
                    provider=self.config.provider,
                )
            return generated_audio_tool_result([artifact])
        except (ArtifactError, MusicGenerationError, OSError) as exc:
            return ToolResult.error(f"Error: {exc}")
