"""MiniMax music generation provider."""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any, Literal, cast
from urllib.parse import urlparse

import httpx

MusicOutputFormat = Literal["url", "hex"]

MUSIC_GENERATION_MODELS = (
    "music-3.0",
    "music-2.6",
    "music-3.0-free",
    "music-2.6-free",
)
MUSIC_COVER_MODELS = ("music-cover", "music-cover-free")
MUSIC_MODELS = (*MUSIC_GENERATION_MODELS, *MUSIC_COVER_MODELS)
MUSIC_AUDIO_FORMATS = ("mp3", "wav", "pcm")
MUSIC_SAMPLE_RATES = (16000, 24000, 32000, 44100)
MUSIC_BITRATES = (32000, 64000, 128000, 256000)

_DEFAULT_API_BASE = "https://api.minimax.io/v1"
_DEFAULT_TIMEOUT_S = 300.0
_MAX_COVER_AUDIO_BYTES = 50 * 1024 * 1024


class MusicGenerationError(RuntimeError):
    """Raised when a music generation request cannot return audio."""


@dataclass(frozen=True)
class GeneratedMusicResponse:
    """Generated audio and provider response metadata."""

    audio: str
    status: int
    output_format: MusicOutputFormat
    raw: dict[str, Any]


def _as_json_object(value: object) -> dict[str, Any] | None:
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def _status_value(data: dict[str, Any]) -> int | None:
    value = data.get("status")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class MiniMaxMusicGenerationClient:
    """Async client for MiniMax music generation."""

    def __init__(
        self,
        *,
        api_key: str | None,
        api_base: str | None = None,
        extra_headers: dict[str, str] | None = None,
        extra_body: dict[str, Any] | None = None,
        proxy: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT_S,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.api_base = (api_base or _DEFAULT_API_BASE).rstrip("/")
        self.extra_headers = extra_headers or {}
        self.extra_body = extra_body or {}
        self.proxy = proxy or None
        self.timeout = timeout
        self._client = client

    async def generate(
        self,
        *,
        model: str,
        prompt: str | None = None,
        lyrics: str | None = None,
        stream: bool = False,
        output_format: MusicOutputFormat = "hex",
        audio_setting: dict[str, Any] | None = None,
        lyrics_optimizer: bool = False,
        is_instrumental: bool = False,
        audio_url: str | None = None,
        audio_base64: str | None = None,
        cover_feature_id: str | None = None,
        aigc_watermark: bool | None = None,
    ) -> GeneratedMusicResponse:
        if not self.api_key:
            raise MusicGenerationError(
                "MiniMax API key is not configured. Set providers.minimax.apiKey."
            )

        self._validate_request(
            model=model,
            prompt=prompt,
            lyrics=lyrics,
            stream=stream,
            output_format=output_format,
            audio_setting=audio_setting,
            lyrics_optimizer=lyrics_optimizer,
            is_instrumental=is_instrumental,
            audio_url=audio_url,
            audio_base64=audio_base64,
            cover_feature_id=cover_feature_id,
            aigc_watermark=aigc_watermark,
        )

        body: dict[str, Any] = {
            "model": model,
            "stream": stream,
            "output_format": output_format,
            "lyrics_optimizer": lyrics_optimizer,
            "is_instrumental": is_instrumental,
        }
        optional_fields = {
            "prompt": prompt,
            "lyrics": lyrics,
            "audio_setting": audio_setting,
            "audio_url": audio_url,
            "audio_base64": audio_base64,
            "cover_feature_id": cover_feature_id,
        }
        body.update({key: value for key, value in optional_fields.items() if value is not None})
        if aigc_watermark is not None:
            body["aigc_watermark"] = aigc_watermark
        body.update(self.extra_body)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }
        url = f"{self.api_base}/music_generation"

        try:
            response = await self._post(url, headers=headers, body=body)
        except httpx.TimeoutException as exc:
            raise MusicGenerationError("MiniMax music generation timed out") from exc
        except httpx.RequestError as exc:
            raise MusicGenerationError(f"MiniMax music generation request failed: {exc}") from exc

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text[:500]
            raise MusicGenerationError(f"MiniMax music generation failed: {detail}") from exc

        if stream:
            return await self._parse_stream_response(response, output_format=output_format)
        return self._parse_response(response, output_format=output_format)

    async def _post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: dict[str, Any],
    ) -> httpx.Response:
        if self._client is not None:
            return await self._client.post(url, headers=headers, json=body)
        kwargs: dict[str, Any] = {"timeout": self.timeout}
        if self.proxy:
            kwargs.update({"proxy": self.proxy, "trust_env": False})
        async with httpx.AsyncClient(**kwargs) as client:
            return await client.post(url, headers=headers, json=body)

    def _parse_response(
        self,
        response: httpx.Response,
        *,
        output_format: MusicOutputFormat,
    ) -> GeneratedMusicResponse:
        try:
            payload = _as_json_object(response.json())
        except (json.JSONDecodeError, ValueError) as exc:
            raise MusicGenerationError("MiniMax returned an invalid music response") from exc
        if payload is None:
            raise MusicGenerationError("MiniMax returned an invalid music response")
        self._raise_api_error(payload)
        return self._response_from_payload(payload, output_format=output_format)

    async def _parse_stream_response(
        self,
        response: httpx.Response,
        *,
        output_format: MusicOutputFormat,
    ) -> GeneratedMusicResponse:
        audio_parts: list[str] = []
        final_status: int | None = None
        final_payload: dict[str, Any] = {}

        async for raw_line in response.aiter_lines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("data:"):
                line = line[5:].strip()
            if line == "[DONE]":
                continue
            try:
                payload = _as_json_object(json.loads(line))
            except (json.JSONDecodeError, ValueError) as exc:
                raise MusicGenerationError("MiniMax returned an invalid music stream") from exc
            if payload is None:
                raise MusicGenerationError("MiniMax returned an invalid music stream")
            self._raise_api_error(payload)
            final_payload = payload
            data = _as_json_object(payload.get("data")) or {}
            audio = data.get("audio")
            if isinstance(audio, str) and audio:
                audio_parts.append(audio)
            status = _status_value(data)
            if status is not None:
                final_status = status

        if final_status != 2:
            raise MusicGenerationError(
                f"MiniMax music generation did not complete (status {final_status})"
            )
        audio = "".join(audio_parts)
        self._validate_audio(audio, output_format=output_format)
        return GeneratedMusicResponse(
            audio=audio,
            status=final_status,
            output_format=output_format,
            raw=final_payload,
        )

    def _response_from_payload(
        self,
        payload: dict[str, Any],
        *,
        output_format: MusicOutputFormat,
    ) -> GeneratedMusicResponse:
        data = _as_json_object(payload.get("data")) or {}
        status = _status_value(data)
        if status != 2:
            raise MusicGenerationError(f"MiniMax music generation did not complete (status {status})")
        audio = data.get("audio")
        if not isinstance(audio, str):
            raise MusicGenerationError("MiniMax returned no audio for this request")
        self._validate_audio(audio, output_format=output_format)
        return GeneratedMusicResponse(
            audio=audio,
            status=status,
            output_format=output_format,
            raw=payload,
        )

    @staticmethod
    def _raise_api_error(payload: dict[str, Any]) -> None:
        base_resp = _as_json_object(payload.get("base_resp")) or {}
        status_code = base_resp.get("status_code")
        if status_code in (None, 0, "0"):
            return
        message = base_resp.get("status_msg")
        detail = message if isinstance(message, str) and message else f"status code {status_code}"
        raise MusicGenerationError(f"MiniMax music generation failed: {detail}")

    @staticmethod
    def _validate_audio(audio: str, *, output_format: MusicOutputFormat) -> None:
        if not audio:
            raise MusicGenerationError("MiniMax returned no audio for this request")
        if output_format == "url":
            parsed = urlparse(audio)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise MusicGenerationError("MiniMax returned an invalid audio URL")
            return
        try:
            raw = bytes.fromhex(audio)
        except ValueError as exc:
            raise MusicGenerationError("MiniMax returned invalid hexadecimal audio") from exc
        if not raw:
            raise MusicGenerationError("MiniMax returned empty audio")

    def _validate_request(
        self,
        *,
        model: str,
        prompt: str | None,
        lyrics: str | None,
        stream: bool,
        output_format: MusicOutputFormat,
        audio_setting: dict[str, Any] | None,
        lyrics_optimizer: bool,
        is_instrumental: bool,
        audio_url: str | None,
        audio_base64: str | None,
        cover_feature_id: str | None,
        aigc_watermark: bool | None,
    ) -> None:
        if model not in MUSIC_MODELS:
            raise MusicGenerationError(f"unsupported MiniMax music model: {model}")
        if output_format not in ("url", "hex"):
            raise MusicGenerationError("output_format must be 'url' or 'hex'")
        if stream and output_format != "hex":
            raise MusicGenerationError("streaming music generation requires output_format='hex'")
        self._validate_audio_setting(audio_setting)
        self._validate_watermark(stream=stream, aigc_watermark=aigc_watermark)

        if model in MUSIC_COVER_MODELS:
            self._validate_cover_request(
                prompt=prompt,
                lyrics=lyrics,
                audio_url=audio_url,
                audio_base64=audio_base64,
                cover_feature_id=cover_feature_id,
            )
            return

        if any((audio_url, audio_base64, cover_feature_id)):
            raise MusicGenerationError("cover audio fields require a MiniMax music cover model")
        if prompt is not None and len(prompt) > 2000:
            raise MusicGenerationError("prompt must be at most 2000 characters")
        if lyrics is not None and len(lyrics) > 3500:
            raise MusicGenerationError("lyrics must be at most 3500 characters")
        if is_instrumental and not prompt:
            raise MusicGenerationError("prompt is required for instrumental music generation")
        if not is_instrumental and not lyrics:
            if not lyrics_optimizer:
                raise MusicGenerationError(
                    "lyrics are required unless lyrics_optimizer or is_instrumental is enabled"
                )
            if not prompt:
                raise MusicGenerationError("prompt is required when lyrics_optimizer is enabled")

    @staticmethod
    def _validate_audio_setting(audio_setting: dict[str, Any] | None) -> None:
        if audio_setting is None:
            return
        unknown = set(audio_setting) - {"sample_rate", "bitrate", "format"}
        if unknown:
            raise MusicGenerationError(
                f"unsupported audio_setting fields: {', '.join(sorted(unknown))}"
            )
        sample_rate = audio_setting.get("sample_rate")
        if sample_rate is not None and sample_rate not in MUSIC_SAMPLE_RATES:
            raise MusicGenerationError("unsupported audio sample_rate")
        bitrate = audio_setting.get("bitrate")
        if bitrate is not None and bitrate not in MUSIC_BITRATES:
            raise MusicGenerationError("unsupported audio bitrate")
        audio_format = audio_setting.get("format")
        if audio_format is not None and audio_format not in MUSIC_AUDIO_FORMATS:
            raise MusicGenerationError("unsupported audio format")

    def _validate_watermark(self, *, stream: bool, aigc_watermark: bool | None) -> None:
        if aigc_watermark is None:
            return
        hostname = (urlparse(self.api_base).hostname or "").lower()
        if not hostname.endswith("minimaxi.com"):
            raise MusicGenerationError(
                "aigc_watermark is only supported by the MiniMax mainland China endpoint"
            )
        if stream and aigc_watermark:
            raise MusicGenerationError("aigc_watermark is not supported for streaming requests")

    @staticmethod
    def _validate_cover_request(
        *,
        prompt: str | None,
        lyrics: str | None,
        audio_url: str | None,
        audio_base64: str | None,
        cover_feature_id: str | None,
    ) -> None:
        if prompt is None or not 10 <= len(prompt) <= 300:
            raise MusicGenerationError("cover prompt must be between 10 and 300 characters")
        sources = [bool(audio_url), bool(audio_base64), bool(cover_feature_id)]
        if sum(sources) != 1:
            raise MusicGenerationError(
                "provide exactly one of audio_url, audio_base64, or cover_feature_id"
            )
        if lyrics is not None and not 10 <= len(lyrics) <= 1000:
            raise MusicGenerationError("cover lyrics must be between 10 and 1000 characters")
        if cover_feature_id and not lyrics:
            raise MusicGenerationError("lyrics are required with cover_feature_id")
        if audio_url:
            parsed = urlparse(audio_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise MusicGenerationError("audio_url must be an HTTP or HTTPS URL")
        if audio_base64:
            encoded = "".join(audio_base64.split())
            try:
                raw = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise MusicGenerationError("audio_base64 is not valid base64") from exc
            if len(raw) > _MAX_COVER_AUDIO_BYTES:
                raise MusicGenerationError("cover audio must not exceed 50 MB")
