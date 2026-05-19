from __future__ import annotations

import base64
from pathlib import Path

import pytest

from nanobot.providers.image_generation import AIHubMixImageGenerationClient

from ._helpers import JPEG_BYTES, PNG_BYTES, PNG_DATA_URL, FakeClient, FakeResponse


@pytest.mark.asyncio
async def test_aihubmix_image_generation_payload_and_response() -> None:
    raw_b64 = PNG_DATA_URL.removeprefix("data:image/png;base64,")
    fake = FakeClient(FakeResponse({"output": {"b64_json": [{"bytesBase64": raw_b64}]}}))
    client = AIHubMixImageGenerationClient(
        api_key="sk-ahm-test",
        api_base="https://aihubmix.com/v1/",
        extra_headers={"APP-Code": "nanobot"},
        extra_body={"quality": "low"},
        client=fake,  # type: ignore[arg-type]
    )

    response = await client.generate(
        prompt="draw a logo",
        model="gpt-image-2-free",
        aspect_ratio="16:9",
        image_size="1K",
    )

    assert response.images == [PNG_DATA_URL]
    call = fake.calls[0]
    assert call["url"] == "https://aihubmix.com/v1/models/openai/gpt-image-2-free/predictions"
    assert call["headers"]["Authorization"] == "Bearer sk-ahm-test"
    assert call["headers"]["APP-Code"] == "nanobot"
    assert call["json"] == {
        "input": {
            "prompt": "draw a logo",
            "n": 1,
            "size": "1536x1024",
            "quality": "low",
        }
    }


@pytest.mark.asyncio
async def test_aihubmix_image_edit_payload_uses_reference_images(tmp_path: Path) -> None:
    raw_b64 = PNG_DATA_URL.removeprefix("data:image/png;base64,")
    fake = FakeClient(FakeResponse({"output": [{"b64_json": raw_b64}]}))
    ref = tmp_path / "ref.png"
    ref.write_bytes(PNG_BYTES)
    client = AIHubMixImageGenerationClient(
        api_key="sk-ahm-test",
        client=fake,  # type: ignore[arg-type]
    )

    response = await client.generate(
        prompt="edit this",
        model="gpt-image-2-free",
        reference_images=[str(ref)],
        aspect_ratio="1:1",
    )

    assert response.images == [PNG_DATA_URL]
    call = fake.calls[0]
    assert call["url"] == "https://aihubmix.com/v1/models/openai/gpt-image-2-free/predictions"
    assert call["json"]["input"]["prompt"] == "edit this"
    assert call["json"]["input"]["n"] == 1
    assert call["json"]["input"]["size"] == "1024x1024"
    assert call["json"]["input"]["image"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_aihubmix_image_generation_downloads_url_response() -> None:
    fake = FakeClient(FakeResponse({"data": [{"url": "https://cdn.example/image.png"}]}))
    fake.get_response = FakeResponse({}, content=PNG_BYTES)
    client = AIHubMixImageGenerationClient(
        api_key="sk-ahm-test",
        client=fake,  # type: ignore[arg-type]
    )

    response = await client.generate(prompt="draw", model="gpt-image-2-free")

    assert response.images[0].startswith("data:image/png;base64,")
    assert fake.get_calls[0]["url"] == "https://cdn.example/image.png"


@pytest.mark.asyncio
async def test_aihubmix_base64_response_uses_detected_mime() -> None:
    raw_b64 = base64.b64encode(JPEG_BYTES).decode("ascii")
    fake = FakeClient(FakeResponse({"output": {"b64_json": raw_b64}}))
    client = AIHubMixImageGenerationClient(
        api_key="sk-ahm-test",
        client=fake,  # type: ignore[arg-type]
    )

    response = await client.generate(prompt="draw", model="gpt-image-2-free")

    assert response.images == [f"data:image/jpeg;base64,{raw_b64}"]
