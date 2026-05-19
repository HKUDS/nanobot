from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import httpx
import pytest

from nanobot.providers.image_generation import (
    AIHubMixImageGenerationClient,
    GeminiImageGenerationClient,
    GeneratedImageResponse,
    ImageGenerationError,
    MiniMaxImageGenerationClient,
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
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"0" * 12


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


RAW_B64 = PNG_DATA_URL.removeprefix("data:image/png;base64,")


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
