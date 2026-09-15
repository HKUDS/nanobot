from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nanobot.agent.tools.music_generation import (
    MusicGenerationTool,
    MusicGenerationToolConfig,
)
from nanobot.config.loader import set_config_path
from nanobot.config.schema import ProviderConfig, ToolsConfig
from nanobot.providers.music_generation import GeneratedMusicResponse


class FakeMusicClient:
    instances: list["FakeMusicClient"] = []
    response = GeneratedMusicResponse(
        audio=b"ID3music".hex(),
        status=2,
        output_format="hex",
        raw={},
    )

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.calls: list[dict[str, Any]] = []
        self.instances.append(self)

    async def generate(self, **kwargs: Any) -> GeneratedMusicResponse:
        self.calls.append(kwargs)
        return self.response


@pytest.mark.asyncio
async def test_generate_music_tool_stores_hex_audio_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_config_path(tmp_path / "config.json")
    FakeMusicClient.instances = []
    FakeMusicClient.response = GeneratedMusicResponse(
        audio=b"ID3music".hex(),
        status=2,
        output_format="hex",
        raw={},
    )
    monkeypatch.setattr(
        "nanobot.agent.tools.music_generation.MiniMaxMusicGenerationClient",
        FakeMusicClient,
    )
    tool = MusicGenerationTool(
        config=MusicGenerationToolConfig(enabled=True),
        provider_configs={"minimax": ProviderConfig(api_key="test-key")},
    )

    result = await tool.execute(
        prompt="Bright electronic instrumental",
        is_instrumental=True,
    )

    payload = json.loads(result)
    artifact = payload["artifacts"][0]
    audio_path = Path(artifact["path"])
    assert audio_path.read_bytes() == b"ID3music"
    assert artifact["id"].startswith("audio_")
    assert artifact["mime"] == "audio/mpeg"
    assert artifact["model"] == "music-3.0"

    fake = FakeMusicClient.instances[0]
    assert fake.kwargs["api_key"] == "test-key"
    assert fake.calls[0]["audio_setting"] == {
        "sample_rate": 44100,
        "bitrate": 256000,
        "format": "mp3",
    }


@pytest.mark.asyncio
async def test_generate_music_tool_returns_expiring_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeMusicClient.instances = []
    FakeMusicClient.response = GeneratedMusicResponse(
        audio="https://cdn.example.com/generated.mp3",
        status=2,
        output_format="url",
        raw={},
    )
    monkeypatch.setattr(
        "nanobot.agent.tools.music_generation.MiniMaxMusicGenerationClient",
        FakeMusicClient,
    )
    tool = MusicGenerationTool(
        config=MusicGenerationToolConfig(enabled=True),
        provider_configs={"minimax": ProviderConfig(api_key="test-key")},
    )

    result = await tool.execute(
        prompt="Warm cinematic instrumental",
        output_format="url",
        is_instrumental=True,
    )

    artifact = json.loads(result)["artifacts"][0]
    assert artifact == {
        "url": "https://cdn.example.com/generated.mp3",
        "model": "music-3.0",
        "provider": "minimax",
        "output_format": "url",
        "expires_in_hours": 24,
    }


@pytest.mark.asyncio
async def test_generate_music_tool_reports_missing_key() -> None:
    tool = MusicGenerationTool(
        config=MusicGenerationToolConfig(enabled=True),
        provider_configs={"minimax": ProviderConfig()},
    )

    result = await tool.execute(
        prompt="Warm cinematic instrumental",
        is_instrumental=True,
    )

    assert result.startswith("Error: MiniMax API key is not configured")


def test_music_generation_config_accepts_camel_case() -> None:
    config = ToolsConfig.model_validate(
        {
            "musicGeneration": {
                "enabled": True,
                "model": "music-2.6",
                "defaultOutputFormat": "url",
                "defaultAudioFormat": "wav",
                "defaultSampleRate": 32000,
                "defaultBitrate": 128000,
            }
        }
    )

    assert config.music_generation.enabled is True
    assert config.music_generation.model == "music-2.6"
    assert config.music_generation.default_output_format == "url"
    assert config.music_generation.default_audio_format == "wav"
    assert config.music_generation.default_sample_rate == 32000
    assert config.music_generation.default_bitrate == 128000
