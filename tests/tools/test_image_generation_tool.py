from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nanobot.agent.tools.image_generation import ImageGenerationTool
from nanobot.config.loader import set_config_path
from nanobot.config.schema import ImageGenerationToolConfig, ProviderConfig
from nanobot.providers.image_generation import GeneratedImageResponse

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x04\x00\x00\x00\xb5\x1c\x0c\x02"
    b"\x00\x00\x00\x0bIDATx\xdacd\xfc\xff\x1f\x00\x03\x03"
    b"\x02\x00\xef\xbf\xa7\xdb\x00\x00\x00\x00IEND\xaeB`\x82"
)
PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


class FakeImageClient:
    instances: list["FakeImageClient"] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.calls: list[dict[str, Any]] = []
        self.instances.append(self)

    async def generate(self, **kwargs: Any) -> GeneratedImageResponse:
        self.calls.append(kwargs)
        return GeneratedImageResponse(images=[PNG_DATA_URL], content="", raw={})


@pytest.mark.asyncio
async def test_generate_image_tool_stores_artifact_and_source_images(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_config_path(tmp_path / "config.json")
    FakeImageClient.instances = []
    monkeypatch.setattr(
        "nanobot.agent.tools.image_generation.OpenRouterImageGenerationClient",
        FakeImageClient,
    )
    ref = tmp_path / "ref.png"
    ref.write_bytes(PNG_BYTES)
    tool = ImageGenerationTool(
        workspace=tmp_path,
        config=ImageGenerationToolConfig(enabled=True, max_images_per_turn=2),
        provider_config=ProviderConfig(api_key="sk-or-test"),
    )

    result = await tool.execute(
        prompt="make this blue",
        reference_images=["ref.png"],
        aspect_ratio="16:9",
        image_size="2K",
        count=2,
    )

    payload = json.loads(result)
    artifacts = payload["artifacts"]
    assert len(artifacts) == 2
    assert Path(artifacts[0]["path"]).is_file()
    assert artifacts[0]["source_images"] == [str(ref.resolve())]
    assert artifacts[0]["model"] == "openai/gpt-5.4-image-2"

    fake = FakeImageClient.instances[0]
    assert fake.kwargs["api_key"] == "sk-or-test"
    assert len(fake.calls) == 2
    assert fake.calls[0]["aspect_ratio"] == "16:9"
    assert fake.calls[0]["image_size"] == "2K"


@pytest.mark.asyncio
async def test_generate_image_tool_reports_missing_key(tmp_path: Path) -> None:
    tool = ImageGenerationTool(
        workspace=tmp_path,
        config=ImageGenerationToolConfig(enabled=True),
        provider_config=ProviderConfig(),
    )

    result = await tool.execute(prompt="draw")

    assert result.startswith("Error: OpenRouter API key is not configured")


@pytest.mark.asyncio
async def test_generate_image_tool_selects_aihubmix_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_config_path(tmp_path / "config.json")
    FakeImageClient.instances = []
    monkeypatch.setattr(
        "nanobot.agent.tools.image_generation.AIHubMixImageGenerationClient",
        FakeImageClient,
    )
    tool = ImageGenerationTool(
        workspace=tmp_path,
        config=ImageGenerationToolConfig(
            enabled=True,
            provider="aihubmix",
            model="gpt-image-2-free",
        ),
        provider_configs={
            "openrouter": ProviderConfig(api_key="sk-or-test"),
            "aihubmix": ProviderConfig(api_key="sk-ahm-test", extra_body={"quality": "low"}),
        },
    )

    result = await tool.execute(prompt="draw a poster", aspect_ratio="3:4")

    payload = json.loads(result)
    assert len(payload["artifacts"]) == 1
    fake = FakeImageClient.instances[0]
    assert fake.kwargs["api_key"] == "sk-ahm-test"
    assert fake.kwargs["extra_body"] == {"quality": "low"}
    assert fake.calls[0]["model"] == "gpt-image-2-free"
    assert fake.calls[0]["aspect_ratio"] == "3:4"


@pytest.mark.asyncio
async def test_generate_image_tool_reports_missing_aihubmix_key(tmp_path: Path) -> None:
    tool = ImageGenerationTool(
        workspace=tmp_path,
        config=ImageGenerationToolConfig(enabled=True, provider="aihubmix"),
        provider_configs={"aihubmix": ProviderConfig()},
    )

    result = await tool.execute(prompt="draw")

    assert result.startswith("Error: AIHubMix API key is not configured")


@pytest.mark.asyncio
async def test_generate_image_tool_rejects_reference_outside_workspace(tmp_path: Path) -> None:
    set_config_path(tmp_path / "config.json")
    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(PNG_BYTES)
    tool = ImageGenerationTool(
        workspace=tmp_path,
        config=ImageGenerationToolConfig(enabled=True),
        provider_config=ProviderConfig(api_key="sk-or-test"),
    )

    result = await tool.execute(prompt="edit", reference_images=[str(outside)])

    assert "reference_images must be inside the workspace" in result
