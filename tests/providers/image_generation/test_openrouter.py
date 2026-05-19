from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.providers.image_generation import (
    GeneratedImageResponse,
    ImageGenerationError,
    OpenRouterImageGenerationClient,
)

from ._helpers import PNG_BYTES, PNG_DATA_URL, FakeClient, FakeResponse


@pytest.mark.asyncio
async def test_openrouter_image_generation_payload_and_response(tmp_path: Path) -> None:
    ref = tmp_path / "ref.png"
    ref.write_bytes(PNG_BYTES)
    fake = FakeClient(
        FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": "done",
                            "images": [{"image_url": {"url": PNG_DATA_URL}}],
                        }
                    }
                ]
            }
        )
    )
    client = OpenRouterImageGenerationClient(
        api_key="sk-or-test",
        api_base="https://openrouter.ai/api/v1/",
        extra_headers={"X-Test": "1"},
        client=fake,  # type: ignore[arg-type]
    )

    response = await client.generate(
        prompt="make this blue",
        model="openai/gpt-5.4-image-2",
        reference_images=[str(ref)],
        aspect_ratio="16:9",
        image_size="2K",
    )

    assert isinstance(response, GeneratedImageResponse)
    assert response.images == [PNG_DATA_URL]
    assert response.content == "done"

    call = fake.calls[0]
    assert call["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer sk-or-test"
    assert call["headers"]["X-Test"] == "1"
    body = call["json"]
    assert body["modalities"] == ["image", "text"]
    assert body["image_config"] == {"aspect_ratio": "16:9", "image_size": "2K"}
    assert body["messages"][0]["content"][0] == {"type": "text", "text": "make this blue"}
    assert body["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_openrouter_image_generation_requires_images() -> None:
    fake = FakeClient(FakeResponse({"choices": [{"message": {"content": "text only"}}]}))
    client = OpenRouterImageGenerationClient(api_key="sk-or-test", client=fake)  # type: ignore[arg-type]

    with pytest.raises(ImageGenerationError, match="returned no images"):
        await client.generate(prompt="draw", model="model")


@pytest.mark.asyncio
async def test_openrouter_image_generation_requires_api_key() -> None:
    client = OpenRouterImageGenerationClient(api_key=None)

    with pytest.raises(ImageGenerationError, match="API key"):
        await client.generate(prompt="draw", model="model")
