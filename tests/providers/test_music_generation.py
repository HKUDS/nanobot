from __future__ import annotations

import base64
from typing import Any

import httpx
import pytest

from nanobot.providers.music_generation import (
    GeneratedMusicResponse,
    MiniMaxMusicGenerationClient,
    MusicGenerationError,
)


class FakeResponse:
    def __init__(
        self,
        payload: dict[str, Any],
        *,
        status_code: int = 200,
        stream_lines: list[str] | None = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)
        self.request = httpx.Request("POST", "https://api.minimax.io/v1/music_generation")
        self._stream_lines = stream_lines or []

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            response = httpx.Response(self.status_code, request=self.request, text=self.text)
            raise httpx.HTTPStatusError("failed", request=self.request, response=response)

    async def aiter_lines(self):
        for line in self._stream_lines:
            yield line


class FakeClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self.response


@pytest.mark.asyncio
async def test_minimax_music_generation_payload_and_hex_response() -> None:
    audio_hex = b"ID3music".hex()
    fake = FakeClient(
        FakeResponse(
            {
                "data": {"status": 2, "audio": audio_hex},
                "base_resp": {"status_code": 0, "status_msg": "success"},
            }
        )
    )
    client = MiniMaxMusicGenerationClient(
        api_key="test-key",
        extra_headers={"X-Test": "1"},
        extra_body={"custom_field": "value"},
        client=fake,  # type: ignore[arg-type]
    )

    response = await client.generate(
        model="music-3.0",
        prompt="Melancholic indie folk for a rainy night",
        lyrics="[Verse]\nStreetlights shimmer in the rain",
        audio_setting={"sample_rate": 44100, "bitrate": 256000, "format": "mp3"},
    )

    assert response == GeneratedMusicResponse(
        audio=audio_hex,
        status=2,
        output_format="hex",
        raw={
            "data": {"status": 2, "audio": audio_hex},
            "base_resp": {"status_code": 0, "status_msg": "success"},
        },
    )
    call = fake.calls[0]
    assert call["url"] == "https://api.minimax.io/v1/music_generation"
    assert call["headers"]["Authorization"] == "Bearer test-key"
    assert call["headers"]["X-Test"] == "1"
    assert call["json"] == {
        "model": "music-3.0",
        "stream": False,
        "output_format": "hex",
        "lyrics_optimizer": False,
        "is_instrumental": False,
        "prompt": "Melancholic indie folk for a rainy night",
        "lyrics": "[Verse]\nStreetlights shimmer in the rain",
        "audio_setting": {"sample_rate": 44100, "bitrate": 256000, "format": "mp3"},
        "custom_field": "value",
    }


@pytest.mark.asyncio
async def test_minimax_music_generation_uses_cn_endpoint_and_url_output() -> None:
    audio_url = "https://cdn.example.com/generated.mp3"
    fake = FakeClient(
        FakeResponse(
            {
                "data": {"status": 2, "audio": audio_url},
                "base_resp": {"status_code": 0},
            }
        )
    )
    client = MiniMaxMusicGenerationClient(
        api_key="test-key",
        api_base="https://api.minimaxi.com/v1/",
        client=fake,  # type: ignore[arg-type]
    )

    response = await client.generate(
        model="music-2.6-free",
        prompt="Warm cinematic strings with a gentle piano melody",
        is_instrumental=True,
        output_format="url",
        aigc_watermark=True,
    )

    assert response.audio == audio_url
    assert response.output_format == "url"
    assert fake.calls[0]["url"] == "https://api.minimaxi.com/v1/music_generation"
    assert fake.calls[0]["json"]["aigc_watermark"] is True


@pytest.mark.asyncio
async def test_minimax_music_generation_supports_cover_inputs() -> None:
    audio_hex = b"RIFFcover".hex()
    reference_audio = base64.b64encode(b"reference audio").decode("ascii")
    fake = FakeClient(
        FakeResponse(
            {
                "data": {"status": 2, "audio": audio_hex},
                "base_resp": {"status_code": 0},
            }
        )
    )
    client = MiniMaxMusicGenerationClient(
        api_key="test-key",
        client=fake,  # type: ignore[arg-type]
    )

    await client.generate(
        model="music-cover-free",
        prompt="Transform this track into a soft acoustic ballad",
        audio_base64=reference_audio,
        output_format="hex",
    )

    body = fake.calls[0]["json"]
    assert body["model"] == "music-cover-free"
    assert body["audio_base64"] == reference_audio
    assert "audio_url" not in body
    assert "cover_feature_id" not in body


@pytest.mark.asyncio
async def test_minimax_music_generation_collects_streamed_hex_audio() -> None:
    first = b"ID3".hex()
    second = b"music".hex()
    fake = FakeClient(
        FakeResponse(
            {},
            stream_lines=[
                f'data: {{"data":{{"status":1,"audio":"{first}"}},"base_resp":{{"status_code":0}}}}',
                f'data: {{"data":{{"status":2,"audio":"{second}"}},"base_resp":{{"status_code":0}}}}',
                "data: [DONE]",
            ],
        )
    )
    client = MiniMaxMusicGenerationClient(
        api_key="test-key",
        client=fake,  # type: ignore[arg-type]
    )

    response = await client.generate(
        model="music-3.0",
        prompt="Bright electronic instrumental",
        stream=True,
        output_format="hex",
        is_instrumental=True,
    )

    assert bytes.fromhex(response.audio) == b"ID3music"
    assert response.status == 2


@pytest.mark.asyncio
async def test_minimax_music_generation_reports_api_errors() -> None:
    fake = FakeClient(
        FakeResponse(
            {
                "data": {"status": 2, "audio": b"audio".hex()},
                "base_resp": {"status_code": 1004, "status_msg": "authentication failed"},
            }
        )
    )
    client = MiniMaxMusicGenerationClient(
        api_key="test-key",
        client=fake,  # type: ignore[arg-type]
    )

    with pytest.raises(MusicGenerationError, match="authentication failed"):
        await client.generate(
            model="music-3.0",
            prompt="Ambient instrumental",
            is_instrumental=True,
        )


@pytest.mark.asyncio
async def test_minimax_music_generation_validates_regional_and_stream_fields() -> None:
    client = MiniMaxMusicGenerationClient(api_key="test-key")

    with pytest.raises(MusicGenerationError, match="requires output_format='hex'"):
        await client.generate(
            model="music-3.0",
            prompt="Ambient instrumental",
            stream=True,
            output_format="url",
            is_instrumental=True,
        )

    with pytest.raises(MusicGenerationError, match="mainland China endpoint"):
        await client.generate(
            model="music-3.0",
            prompt="Ambient instrumental",
            is_instrumental=True,
            aigc_watermark=True,
        )
