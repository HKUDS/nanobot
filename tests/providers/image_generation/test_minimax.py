from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.providers.image_generation import MiniMaxImageGenerationClient

from ._helpers import PNG_BYTES, PNG_DATA_URL, RAW_B64, FakeClient, FakeResponse


@pytest.mark.asyncio
async def test_minimax_payload_and_response_with_reference_image(tmp_path: Path) -> None:
    ref = tmp_path / "ref.png"
    ref.write_bytes(PNG_BYTES)
    fake = FakeClient(FakeResponse({"data": {"image_base64": [RAW_B64]}}))
    client = MiniMaxImageGenerationClient(
        api_key="sk-mm-test",
        api_base="https://api.minimaxi.com/v1/",
        extra_headers={"X-Test": "1"},
        client=fake,  # type: ignore[arg-type]
    )

    response = await client.generate(
        prompt="draw a character",
        model="image-01",
        reference_images=[str(ref)],
        aspect_ratio="21:9",
    )

    assert response.images == [PNG_DATA_URL]
    call = fake.calls[0]
    assert call["url"] == "https://api.minimaxi.com/v1/image_generation"
    assert call["headers"]["Authorization"] == "Bearer sk-mm-test"
    assert call["headers"]["X-Test"] == "1"
    body = call["json"]
    assert body["model"] == "image-01"
    assert body["prompt"] == "draw a character"
    assert body["response_format"] == "base64"
    assert body["aspect_ratio"] == "21:9"
    assert body["subject_reference"][0]["type"] == "character"
    assert body["subject_reference"][0]["image_file"].startswith("data:image/png;base64,")
