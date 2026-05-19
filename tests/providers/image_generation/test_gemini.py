from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.providers.image_generation import (
    GeminiImageGenerationClient,
    ImageGenerationError,
)

from ._helpers import PNG_BYTES, PNG_DATA_URL, RAW_B64, FakeClient, FakeResponse


@pytest.mark.asyncio
async def test_gemini_imagen_payload_and_response() -> None:
    fake = FakeClient(
        FakeResponse({"predictions": [{"bytesBase64Encoded": RAW_B64, "mimeType": "image/png"}]})
    )
    client = GeminiImageGenerationClient(
        api_key="AIza-test",
        api_base="https://generativelanguage.googleapis.com/v1beta",
        client=fake,  # type: ignore[arg-type]
    )

    response = await client.generate(
        prompt="a sunset",
        model="imagen-4.0-generate-001",
        aspect_ratio="16:9",
    )

    assert response.images == [PNG_DATA_URL]
    assert response.content == ""
    call = fake.calls[0]
    assert call["url"].endswith(":predict")
    assert call["headers"]["x-goog-api-key"] == "AIza-test"
    assert "params" not in call
    body = call["json"]
    assert body["instances"] == [{"prompt": "a sunset"}]
    assert body["parameters"]["sampleCount"] == 1
    assert body["parameters"]["aspectRatio"] == "16:9"


@pytest.mark.asyncio
async def test_gemini_imagen_ignores_unsupported_aspect_ratio() -> None:
    fake = FakeClient(
        FakeResponse({"predictions": [{"bytesBase64Encoded": RAW_B64, "mimeType": "image/png"}]})
    )
    client = GeminiImageGenerationClient(api_key="AIza-test", client=fake)  # type: ignore[arg-type]

    await client.generate(prompt="a sunset", model="imagen-4.0-generate-001", aspect_ratio="2:3")

    body = fake.calls[0]["json"]
    assert "aspectRatio" not in body["parameters"]


@pytest.mark.asyncio
async def test_gemini_flash_payload_and_response() -> None:
    fake = FakeClient(
        FakeResponse(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "here is your image"},
                                {"inlineData": {"mimeType": "image/png", "data": RAW_B64}},
                            ]
                        }
                    }
                ]
            }
        )
    )
    client = GeminiImageGenerationClient(
        api_key="AIza-test",
        api_base="https://generativelanguage.googleapis.com/v1beta",
        client=fake,  # type: ignore[arg-type]
    )

    response = await client.generate(
        prompt="draw a cat",
        model="gemini-2.0-flash-preview-image-generation",
    )

    assert response.images == [PNG_DATA_URL]
    assert response.content == "here is your image"
    call = fake.calls[0]
    assert call["url"].endswith(":generateContent")
    assert call["headers"]["x-goog-api-key"] == "AIza-test"
    assert "params" not in call
    body = call["json"]
    assert body["generationConfig"]["responseModalities"] == ["TEXT", "IMAGE"]
    assert body["contents"][0]["parts"][-1] == {"text": "draw a cat"}


@pytest.mark.asyncio
async def test_gemini_flash_reference_images(tmp_path: Path) -> None:
    ref = tmp_path / "ref.png"
    ref.write_bytes(PNG_BYTES)
    fake = FakeClient(
        FakeResponse(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"inlineData": {"mimeType": "image/png", "data": RAW_B64}}]
                        }
                    }
                ]
            }
        )
    )
    client = GeminiImageGenerationClient(api_key="AIza-test", client=fake)  # type: ignore[arg-type]

    response = await client.generate(
        prompt="edit this",
        model="gemini-2.0-flash-preview-image-generation",
        reference_images=[str(ref)],
    )

    assert response.images == [PNG_DATA_URL]
    parts = fake.calls[0]["json"]["contents"][0]["parts"]
    assert parts[0]["inlineData"]["mimeType"] == "image/png"
    assert parts[0]["inlineData"]["data"].startswith("iVBOR")
    assert parts[1] == {"text": "edit this"}


@pytest.mark.asyncio
async def test_gemini_requires_api_key() -> None:
    client = GeminiImageGenerationClient(api_key=None)

    with pytest.raises(ImageGenerationError, match="API key"):
        await client.generate(prompt="draw", model="imagen-4.0-generate-001")


@pytest.mark.asyncio
async def test_gemini_no_images_raises() -> None:
    fake = FakeClient(FakeResponse({"candidates": [{"content": {"parts": [{"text": "sorry"}]}}]}))
    client = GeminiImageGenerationClient(api_key="AIza-test", client=fake)  # type: ignore[arg-type]

    with pytest.raises(ImageGenerationError, match="returned no images"):
        await client.generate(prompt="draw", model="gemini-2.0-flash-preview-image-generation")
