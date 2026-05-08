from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from nanobot.providers.image_generation import (
    AIHubMixImageGenerationClient,
    GeneratedImageResponse,
    ImageGenerationError,
    OpenRouterImageGenerationClient,
)

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


class FakeResponse:
    def __init__(
        self,
        payload: dict[str, Any],
        status_code: int = 200,
        content: bytes = b"",
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)
        self.content = content
        self.request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            response = httpx.Response(self.status_code, request=self.request, text=self.text)
            raise httpx.HTTPStatusError("failed", request=self.request, response=response)


class FakeClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.get_response = response
        self.calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []

    async def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self.response

    async def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.get_calls.append({"url": url, **kwargs})
        return self.get_response


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
