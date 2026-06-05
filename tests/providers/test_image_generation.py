from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import httpx
import pytest

from blackcat.providers.image_generation import (
    AIHubMixImageGenerationClient,
    CodexImageGenerationClient,
    CustomImageGenerationClient,
    GeminiImageGenerationClient,
    GeneratedImageResponse,
    ImageGenerationError,
    MiniMaxImageGenerationClient,
    OllamaImageGenerationClient,
    OpenAIImageGenerationClient,
    OpenRouterImageGenerationClient,
    StepFunImageGenerationClient,
    ZhipuImageGenerationClient,
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
        sse_lines: list[str] | None = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)
        self.content = content
        self.request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        self._sse_lines = sse_lines

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            response = httpx.Response(self.status_code, request=self.request, text=self.text)
            raise httpx.HTTPStatusError("failed", request=self.request, response=response)

    async def aiter_lines(self):
        if self._sse_lines is not None:
            for line in self._sse_lines:
                yield line
            return
        # Fallback: treat response text as SSE lines
        for line in self.text.split("\n"):
            yield line


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
async def test_ollama_image_generation_payload_and_response() -> None:
    raw_b64 = PNG_DATA_URL.removeprefix("data:image/png;base64,")
    fake = FakeClient(FakeResponse({"image": raw_b64}))
    client = OllamaImageGenerationClient(
        api_key="ollama-test",
        api_base="http://localhost:11434/v1/",
        extra_headers={"X-Test": "1"},
        extra_body={"seed": 123},
        client=fake,  # type: ignore[arg-type]
    )

    response = await client.generate(
        prompt="a sunset",
        model="x/z-image-turbo",
        aspect_ratio="16:9",
        image_size="1K",
    )

    assert response.images == [PNG_DATA_URL]
    assert response.content == ""

    call = fake.calls[0]
    assert call["url"] == "http://localhost:11434/api/generate"
    assert call["headers"]["Authorization"] == "Bearer ollama-test"
    assert call["headers"]["X-Test"] == "1"
    body = call["json"]
    assert body["model"] == "x/z-image-turbo"
    assert body["prompt"] == "a sunset"
    assert body["width"] == 1024
    assert body["height"] == 576
    assert body["steps"] == 0
    assert body["stream"] is False
    assert body["seed"] == 123


@pytest.mark.asyncio
async def test_ollama_image_generation_rejects_reference_images() -> None:
    client = OllamaImageGenerationClient(api_key=None)

    with pytest.raises(ImageGenerationError, match="reference images"):
        await client.generate(
            prompt="edit this",
            model="x/z-image-turbo",
            reference_images=["ref.png"],
        )


@pytest.mark.asyncio
async def test_aihubmix_image_generation_payload_and_response() -> None:
    raw_b64 = PNG_DATA_URL.removeprefix("data:image/png;base64,")
    fake = FakeClient(FakeResponse({"output": {"b64_json": [{"bytesBase64": raw_b64}]}}))
    client = AIHubMixImageGenerationClient(
        api_key="sk-ahm-test",
        api_base="https://aihubmix.com/v1/",
        extra_headers={"APP-Code": "blackcat"},
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
    assert call["headers"]["APP-Code"] == "blackcat"
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


def test_gemini_image_client_uses_native_api_base_by_default() -> None:
    client = GeminiImageGenerationClient(api_key="AIza-test")
    assert client.api_base == "https://generativelanguage.googleapis.com/v1beta"


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


@pytest.mark.asyncio
async def test_minimax_base64_response_uses_detected_mime() -> None:
    raw_b64 = base64.b64encode(JPEG_BYTES).decode("ascii")
    fake = FakeClient(FakeResponse({"data": {"image_base64": [raw_b64]}}))
    client = MiniMaxImageGenerationClient(api_key="sk-mm-test", client=fake)  # type: ignore[arg-type]

    response = await client.generate(prompt="draw", model="image-01")

    assert response.images == [f"data:image/jpeg;base64,{raw_b64}"]


# ---------------------------------------------------------------------------
# StepFun (阶跃星辰)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stepfun_payload_and_response_with_aspect_ratio() -> None:
    fake = FakeClient(FakeResponse({"data": [{"b64_json": RAW_B64}]}))
    client = StepFunImageGenerationClient(
        api_key="sk-sf-test",
        api_base="https://api.stepfun.com/v1",
        extra_headers={"X-Test": "1"},
        client=fake,  # type: ignore[arg-type]
    )

    response = await client.generate(
        prompt="a cat on the moon",
        model="step-image-edit-2",
        aspect_ratio="16:9",
    )

    assert response.images == [PNG_DATA_URL]
    call = fake.calls[0]
    assert call["url"] == "https://api.stepfun.com/v1/images/generations"
    assert call["headers"]["Authorization"] == "Bearer sk-sf-test"
    assert call["headers"]["X-Test"] == "1"
    body = call["json"]
    assert body["model"] == "step-image-edit-2"
    assert body["prompt"] == "a cat on the moon"
    assert body["response_format"] == "b64_json"
    assert body["n"] == 1
    assert body["size"] == "1280x800"


@pytest.mark.asyncio
async def test_stepfun_default_size_when_no_aspect_ratio() -> None:
    fake = FakeClient(FakeResponse({"data": [{"b64_json": RAW_B64}]}))
    client = StepFunImageGenerationClient(
        api_key="sk-sf-test",
        api_base="https://api.stepfun.com/v1",
        client=fake,  # type: ignore[arg-type]
    )

    await client.generate(prompt="a dog", model="step-image-edit-2")

    body = fake.calls[0]["json"]
    assert body["size"] == "1024x1024"


@pytest.mark.asyncio
async def test_stepfun_uses_explicit_image_size() -> None:
    fake = FakeClient(FakeResponse({"data": [{"b64_json": RAW_B64}]}))
    client = StepFunImageGenerationClient(
        api_key="sk-sf-test",
        api_base="https://api.stepfun.com/v1",
        client=fake,  # type: ignore[arg-type]
    )

    await client.generate(
        prompt="a bird",
        model="step-image-edit-2",
        image_size="1024x1024",
    )

    body = fake.calls[0]["json"]
    assert body["size"] == "1024x1024"


@pytest.mark.asyncio
async def test_stepfun_style_reference_on_1x_model(tmp_path: Path) -> None:
    """step-1x-medium supports style_reference for reference-image generation."""
    ref = tmp_path / "ref.png"
    ref.write_bytes(PNG_BYTES)
    fake = FakeClient(FakeResponse({"data": [{"b64_json": RAW_B64}]}))
    client = StepFunImageGenerationClient(
        api_key="sk-sf-test",
        api_base="https://api.stepfun.com/v1",
        client=fake,  # type: ignore[arg-type]
    )

    await client.generate(
        prompt="in this style",
        model="step-1x-medium",
        reference_images=[str(ref)],
    )

    body = fake.calls[0]["json"]
    assert "style_reference" in body
    assert body["style_reference"]["source_url"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_stepfun_no_style_reference_on_non_1x_model() -> None:
    """step-image-edit-2 does not use style_reference; reference images are ignored."""
    fake = FakeClient(FakeResponse({"data": [{"b64_json": RAW_B64}]}))
    client = StepFunImageGenerationClient(
        api_key="sk-sf-test",
        api_base="https://api.stepfun.com/v1",
        client=fake,  # type: ignore[arg-type]
    )

    await client.generate(
        prompt="a flower",
        model="step-image-edit-2",
        reference_images=["/tmp/ref.png"],
    )

    body = fake.calls[0]["json"]
    assert "style_reference" not in body


@pytest.mark.asyncio
async def test_stepfun_requires_api_key() -> None:
    client = StepFunImageGenerationClient(api_key=None)

    with pytest.raises(ImageGenerationError, match="API key"):
        await client.generate(prompt="draw", model="step-image-edit-2")


@pytest.mark.asyncio
async def test_stepfun_no_images_raises() -> None:
    fake = FakeClient(FakeResponse({"data": [{"text": "sorry"}]}))
    client = StepFunImageGenerationClient(api_key="sk-sf-test", client=fake)  # type: ignore[arg-type]

    with pytest.raises(ImageGenerationError, match="returned no images"):
        await client.generate(prompt="draw", model="step-image-edit-2")


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_payload_and_response() -> None:
    fake = FakeClient(FakeResponse({"data": [{"b64_json": RAW_B64}]}))
    client = OpenAIImageGenerationClient(
        api_key="sk-openai-test",
        api_base="https://api.openai.com/v1",
        extra_headers={"X-Test": "1"},
        client=fake,  # type: ignore[arg-type]
    )

    response = await client.generate(
        prompt="a cat on the moon",
        model="dall-e-3",
        aspect_ratio="16:9",
    )

    assert response.images == [PNG_DATA_URL]
    call = fake.calls[0]
    assert call["url"] == "https://api.openai.com/v1/images/generations"
    assert call["headers"]["Authorization"] == "Bearer sk-openai-test"
    assert call["headers"]["X-Test"] == "1"
    body = call["json"]
    assert body["model"] == "dall-e-3"
    assert body["prompt"] == "a cat on the moon"
    assert body["response_format"] == "b64_json"
    assert body["n"] == 1
    assert body["size"] == "1792x1024"


@pytest.mark.asyncio
async def test_openai_b64_json_response_uses_detected_mime() -> None:
    raw_b64 = base64.b64encode(JPEG_BYTES).decode("ascii")
    fake = FakeClient(FakeResponse({"data": [{"b64_json": raw_b64}]}))
    client = OpenAIImageGenerationClient(
        api_key="sk-openai-test",
        client=fake,  # type: ignore[arg-type]
    )

    response = await client.generate(prompt="draw", model="dall-e-3")

    assert response.images == [f"data:image/jpeg;base64,{raw_b64}"]


@pytest.mark.asyncio
async def test_openai_url_download_fallback() -> None:
    fake = FakeClient(FakeResponse({"data": [{"url": "https://cdn.example/image.png"}]}))
    fake.get_response = FakeResponse({}, content=PNG_BYTES)
    client = OpenAIImageGenerationClient(
        api_key="sk-openai-test",
        client=fake,  # type: ignore[arg-type]
    )

    response = await client.generate(prompt="draw", model="dall-e-3")

    assert response.images[0].startswith("data:image/png;base64,")
    assert fake.get_calls[0]["url"] == "https://cdn.example/image.png"


@pytest.mark.asyncio
async def test_openai_multiple_images() -> None:
    fake = FakeClient(FakeResponse({
        "data": [
            {"b64_json": RAW_B64},
            {"b64_json": RAW_B64},
        ]
    }))
    client = OpenAIImageGenerationClient(
        api_key="sk-openai-test",
        client=fake,  # type: ignore[arg-type]
    )

    response = await client.generate(prompt="draw", model="dall-e-3")

    assert len(response.images) == 2
    assert response.images == [PNG_DATA_URL, PNG_DATA_URL]


@pytest.mark.asyncio
async def test_openai_aspect_ratio_to_size() -> None:
    fake = FakeClient(FakeResponse({"data": [{"b64_json": RAW_B64}]}))
    client = OpenAIImageGenerationClient(
        api_key="sk-openai-test",
        client=fake,  # type: ignore[arg-type]
    )

    await client.generate(prompt="draw", model="dall-e-3", aspect_ratio="1:1")
    assert fake.calls[0]["json"]["size"] == "1024x1024"


@pytest.mark.asyncio
async def test_openai_dalle3_uses_supported_orientation_sizes() -> None:
    fake = FakeClient(FakeResponse({"data": [{"b64_json": RAW_B64}]}))
    client = OpenAIImageGenerationClient(
        api_key="sk-openai-test",
        client=fake,  # type: ignore[arg-type]
    )

    await client.generate(prompt="draw", model="dall-e-3", aspect_ratio="3:4")
    await client.generate(prompt="draw", model="dall-e-3", aspect_ratio="4:3")

    assert fake.calls[0]["json"]["size"] == "1024x1792"
    assert fake.calls[1]["json"]["size"] == "1792x1024"


@pytest.mark.asyncio
async def test_openai_dalle2_uses_square_size_for_non_square_ratios() -> None:
    fake = FakeClient(FakeResponse({"data": [{"b64_json": RAW_B64}]}))
    client = OpenAIImageGenerationClient(
        api_key="sk-openai-test",
        client=fake,  # type: ignore[arg-type]
    )

    await client.generate(prompt="draw", model="dall-e-2", aspect_ratio="16:9")

    assert fake.calls[0]["json"]["size"] == "1024x1024"


@pytest.mark.asyncio
async def test_openai_gpt_image_uses_supported_landscape_size() -> None:
    fake = FakeClient(FakeResponse({"data": [{"b64_json": RAW_B64}]}))
    client = OpenAIImageGenerationClient(
        api_key="sk-openai-test",
        client=fake,  # type: ignore[arg-type]
    )

    await client.generate(prompt="draw", model="gpt-image-1", aspect_ratio="16:9")

    assert fake.calls[0]["json"]["size"] == "1536x1024"


@pytest.mark.asyncio
async def test_openai_gpt_image_uses_supported_orientation_sizes() -> None:
    fake = FakeClient(FakeResponse({"data": [{"b64_json": RAW_B64}]}))
    client = OpenAIImageGenerationClient(
        api_key="sk-openai-test",
        client=fake,  # type: ignore[arg-type]
    )

    await client.generate(prompt="draw", model="gpt-image-1", aspect_ratio="3:4")
    await client.generate(prompt="draw", model="gpt-image-1", aspect_ratio="4:3")

    assert fake.calls[0]["json"]["size"] == "1024x1536"
    assert fake.calls[1]["json"]["size"] == "1536x1024"


@pytest.mark.asyncio
async def test_openai_default_size_when_no_aspect_ratio() -> None:
    fake = FakeClient(FakeResponse({"data": [{"b64_json": RAW_B64}]}))
    client = OpenAIImageGenerationClient(
        api_key="sk-openai-test",
        client=fake,  # type: ignore[arg-type]
    )

    await client.generate(prompt="draw", model="dall-e-3")

    body = fake.calls[0]["json"]
    assert body["size"] == "1024x1024"


@pytest.mark.asyncio
async def test_openai_ignores_explicit_size_unsupported_by_model_family() -> None:
    fake = FakeClient(FakeResponse({"data": [{"b64_json": RAW_B64}]}))
    client = OpenAIImageGenerationClient(
        api_key="sk-openai-test",
        client=fake,  # type: ignore[arg-type]
    )

    await client.generate(
        prompt="draw",
        model="dall-e-3",
        aspect_ratio="16:9",
        image_size="1536x1024",
    )

    body = fake.calls[0]["json"]
    assert body["size"] == "1792x1024"


@pytest.mark.asyncio
async def test_openai_uses_explicit_image_size() -> None:
    fake = FakeClient(FakeResponse({"data": [{"b64_json": RAW_B64}]}))
    client = OpenAIImageGenerationClient(
        api_key="sk-openai-test",
        client=fake,  # type: ignore[arg-type]
    )

    await client.generate(
        prompt="draw",
        model="dall-e-3",
        aspect_ratio="16:9",
        image_size="1024x1024",
    )

    body = fake.calls[0]["json"]
    assert body["size"] == "1024x1024"


@pytest.mark.asyncio
async def test_openai_requires_api_key() -> None:
    client = OpenAIImageGenerationClient(api_key=None)

    with pytest.raises(ImageGenerationError, match="API key"):
        await client.generate(prompt="draw", model="dall-e-3")


# ---------------------------------------------------------------------------
# Custom OpenAI-compatible Images API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_custom_generate_success() -> None:
    fake = FakeClient(FakeResponse({"data": [{"b64_json": RAW_B64}]}))
    client = CustomImageGenerationClient(
        api_key="sk-custom-test",
        api_base="https://custom.example/v1/",
        extra_headers={"X-Test": "1"},
        client=fake,  # type: ignore[arg-type]
    )

    response = await client.generate(
        prompt="a cat on the moon",
        model="custom-image-model",
        aspect_ratio="16:9",
    )

    assert isinstance(response, GeneratedImageResponse)
    assert response.images == [PNG_DATA_URL]
    assert response.content == ""
    call = fake.calls[0]
    assert call["url"] == "https://custom.example/v1/images/generations"
    assert call["headers"]["Authorization"] == "Bearer sk-custom-test"
    assert call["headers"]["X-Test"] == "1"
    body = call["json"]
    assert body["model"] == "custom-image-model"
    assert body["prompt"] == "a cat on the moon"
    assert body["response_format"] == "b64_json"
    assert body["n"] == 1
    assert body["size"] == "1536x1024"


@pytest.mark.asyncio
async def test_custom_generate_preserves_provider_size_hint() -> None:
    fake = FakeClient(FakeResponse({"data": [{"b64_json": RAW_B64}]}))
    client = CustomImageGenerationClient(
        api_key="sk-custom-test",
        api_base="https://custom.example/v1",
        client=fake,  # type: ignore[arg-type]
    )

    await client.generate(
        prompt="a cat on the moon",
        model="custom-image-model",
        image_size="2K",
    )

    assert fake.calls[0]["json"]["size"] == "2K"


@pytest.mark.asyncio
async def test_custom_generate_maps_one_k_to_openai_dimension() -> None:
    fake = FakeClient(FakeResponse({"data": [{"b64_json": RAW_B64}]}))
    client = CustomImageGenerationClient(
        api_key="sk-custom-test",
        api_base="https://custom.example/v1",
        client=fake,  # type: ignore[arg-type]
    )

    await client.generate(
        prompt="a cat on the moon",
        model="custom-image-model",
        image_size="1K",
    )

    assert fake.calls[0]["json"]["size"] == "1024x1024"


@pytest.mark.asyncio
async def test_custom_generate_extra_body_can_override_defaults() -> None:
    fake = FakeClient(FakeResponse({"data": [{"url": "https://images.example/cat.png"}]}))
    fake.get_response = FakeResponse({}, content=PNG_BYTES)
    client = CustomImageGenerationClient(
        api_key="sk-custom-test",
        api_base="https://custom.example/v1",
        extra_body={"response_format": "url", "size": "2K"},
        client=fake,  # type: ignore[arg-type]
    )

    response = await client.generate(
        prompt="a cat on the moon",
        model="custom-image-model",
        image_size="1K",
    )

    expected_data_url = f"data:image/png;base64,{base64.b64encode(PNG_BYTES).decode('ascii')}"
    assert response.images == [expected_data_url]
    assert fake.get_calls[0]["url"] == "https://images.example/cat.png"
    body = fake.calls[0]["json"]
    assert body["response_format"] == "url"
    assert body["size"] == "2K"


@pytest.mark.asyncio
async def test_custom_generate_without_api_key_omits_authorization() -> None:
    fake = FakeClient(FakeResponse({"data": [{"b64_json": RAW_B64}]}))
    client = CustomImageGenerationClient(
        api_key=None,
        api_base="http://localhost:7860/v1",
        client=fake,  # type: ignore[arg-type]
    )

    response = await client.generate(prompt="draw", model="custom-image-model")

    assert response.images == [PNG_DATA_URL]
    assert "Authorization" not in fake.calls[0]["headers"]


@pytest.mark.asyncio
async def test_custom_generate_requires_api_base() -> None:
    client = CustomImageGenerationClient(api_key="sk-custom-test")

    with pytest.raises(ImageGenerationError, match="providers.custom.apiBase"):
        await client.generate(prompt="draw", model="custom-image-model")


@pytest.mark.asyncio
async def test_custom_generate_http_error() -> None:
    fake = FakeClient(FakeResponse({"error": "bad request"}, status_code=400))
    client = CustomImageGenerationClient(
        api_key="sk-custom-test",
        api_base="https://custom.example/v1",
        client=fake,  # type: ignore[arg-type]
    )

    with pytest.raises(ImageGenerationError, match="HTTP 400"):
        await client.generate(prompt="draw", model="custom-image-model")


# ---------------------------------------------------------------------------
# OpenAI Codex (Responses API)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_codex_payload_and_response(monkeypatch) -> None:
    import sys
    from dataclasses import dataclass
    from types import SimpleNamespace

    @dataclass
    class FakeToken:
        account_id: str = "acct-123"
        access: str = "oauth-token"

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)
    fake_oauth = SimpleNamespace(get_token=lambda: FakeToken())
    monkeypatch.setitem(sys.modules, "oauth_cli_kit", fake_oauth)

    sse_lines = [
        'data: {"type":"response.output_item.added","item":{"id":"ig_1","type":"image_generation_call","status":"in_progress"}}',
        "",
        f'data: {{"type":"response.output_item.done","item":{{"id":"ig_1","type":"image_generation_call","result":"{PNG_DATA_URL}","status":"completed"}}}}',
        "",
        'data: [DONE]',
        "",
    ]
    fake = FakeClient(FakeResponse({}, sse_lines=sse_lines))
    client = CodexImageGenerationClient(
        api_key=None,
        api_base="https://chatgpt.com/backend-api",
        extra_headers={"X-Test": "1"},
        client=fake,  # type: ignore[arg-type]
    )

    response = await client.generate(
        prompt="draw a cat",
        model="gpt-5.4",
    )

    assert response.images == [PNG_DATA_URL]
    assert response.content == ""
    call = fake.calls[0]
    assert call["url"] == "https://chatgpt.com/backend-api/codex/responses"
    assert call["headers"]["Authorization"] == "Bearer oauth-token"
    assert call["headers"]["chatgpt-account-id"] == "acct-123"
    assert call["headers"]["OpenAI-Beta"] == "responses=experimental"
    assert call["headers"]["X-Test"] == "1"
    body = call["json"]
    assert body["model"] == "gpt-5.4"
    assert body["instructions"] == "Generate an image based on the user's request."
    assert body["input"] == [{"role": "user", "content": "draw a cat"}]
    assert body["tools"] == [{"type": "image_generation"}]
    assert body["tool_choice"] == "auto"
    assert body["store"] is False
    assert body["stream"] is True


@pytest.mark.asyncio
async def test_codex_strips_model_prefix(monkeypatch) -> None:
    import sys
    from dataclasses import dataclass
    from types import SimpleNamespace

    @dataclass
    class FakeToken:
        account_id: str = "acct-123"
        access: str = "oauth-token"

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)
    fake_oauth = SimpleNamespace(get_token=lambda: FakeToken())
    monkeypatch.setitem(sys.modules, "oauth_cli_kit", fake_oauth)

    fake = FakeClient(FakeResponse({}, sse_lines=[
        f'data: {{"type":"response.output_item.done","item":{{"type":"image_generation_call","result":"{PNG_DATA_URL}"}}}}',
        "",
        'data: [DONE]',
        "",
    ]))
    client = CodexImageGenerationClient(
        api_key=None, client=fake  # type: ignore[arg-type]
    )

    await client.generate(prompt="draw", model="openai-codex/gpt-5.4")

    assert fake.calls[0]["json"]["model"] == "gpt-5.4"


@pytest.mark.asyncio
async def test_codex_requires_oauth(monkeypatch) -> None:
    async def fake_to_thread(fn, *args, **kwargs):
        raise RuntimeError("no token")

    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)

    client = CodexImageGenerationClient(api_key=None)

    with pytest.raises(ImageGenerationError, match="OAuth token"):
        await client.generate(prompt="draw", model="gpt-5.4")


@pytest.mark.asyncio
async def test_codex_no_images_raises(monkeypatch) -> None:
    import sys
    from dataclasses import dataclass
    from types import SimpleNamespace

    @dataclass
    class FakeToken:
        account_id: str = "acct-123"
        access: str = "oauth-token"

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)
    fake_oauth = SimpleNamespace(get_token=lambda: FakeToken())
    monkeypatch.setitem(sys.modules, "oauth_cli_kit", fake_oauth)

    fake = FakeClient(FakeResponse({}, sse_lines=[
        'data: {"type":"response.completed","response":{"status":"completed"}}',
        "",
        'data: [DONE]',
        "",
    ]))
    client = CodexImageGenerationClient(
        api_key=None, client=fake  # type: ignore[arg-type]
    )

    with pytest.raises(ImageGenerationError, match="returned no images"):
        await client.generate(prompt="draw", model="gpt-5.4")


@pytest.mark.asyncio
async def test_codex_extracts_text_content(monkeypatch) -> None:
    import sys
    from dataclasses import dataclass
    from types import SimpleNamespace

    @dataclass
    class FakeToken:
        account_id: str = "acct-123"
        access: str = "oauth-token"

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)
    fake_oauth = SimpleNamespace(get_token=lambda: FakeToken())
    monkeypatch.setitem(sys.modules, "oauth_cli_kit", fake_oauth)

    fake = FakeClient(FakeResponse({}, sse_lines=[
        'data: {"type":"response.output_text.delta","delta":"Here "}',
        "",
        'data: {"type":"response.output_text.delta","delta":"is your cat image."}',
        "",
        f'data: {{"type":"response.output_item.done","item":{{"type":"image_generation_call","result":"{PNG_DATA_URL}"}}}}',
        "",
        'data: [DONE]',
        "",
    ]))
    client = CodexImageGenerationClient(
        api_key=None, client=fake  # type: ignore[arg-type]
    )

    response = await client.generate(prompt="draw a cat", model="gpt-5.4")

    assert response.images == [PNG_DATA_URL]
    assert response.content == "Here is your cat image."


@pytest.mark.asyncio
async def test_codex_json_result_format(monkeypatch) -> None:
    """image_generation_call result can be a dict with image_url key."""
    import sys
    from dataclasses import dataclass
    from types import SimpleNamespace

    @dataclass
    class FakeToken:
        account_id: str = "acct-123"
        access: str = "oauth-token"

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)
    fake_oauth = SimpleNamespace(get_token=lambda: FakeToken())
    monkeypatch.setitem(sys.modules, "oauth_cli_kit", fake_oauth)

    fake = FakeClient(FakeResponse({}, sse_lines=[
        f'data: {{"type":"response.output_item.done","item":{{"type":"image_generation_call","result":{{"image_url":"{PNG_DATA_URL}"}}}}}}',
        "",
        'data: [DONE]',
        "",
    ]))
    client = CodexImageGenerationClient(
        api_key=None, client=fake  # type: ignore[arg-type]
    )

    response = await client.generate(prompt="draw", model="gpt-5.4")

    assert response.images == [PNG_DATA_URL]


@pytest.mark.asyncio
async def test_openai_no_images_raises() -> None:
    fake = FakeClient(FakeResponse({"data": []}))
    client = OpenAIImageGenerationClient(
        api_key="sk-openai-test",
        client=fake,  # type: ignore[arg-type]
    )

    with pytest.raises(ImageGenerationError, match="returned no images"):
        await client.generate(prompt="draw", model="dall-e-3")


# ---------------------------------------------------------------------------
# Zhipu
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zhipu_image_generation_payload_and_response() -> None:
    fake = FakeClient(FakeResponse({"data": [{"url": "https://cdn.example/image.png"}]}))
    fake.get_response = FakeResponse({}, content=PNG_BYTES)
    client = ZhipuImageGenerationClient(
        api_key="sk-zhipu-test",
        api_base="https://open.bigmodel.cn/api/paas/v4",
        extra_headers={"X-Test": "1"},
        extra_body={"watermark_enabled": False},
        client=fake,  # type: ignore[arg-type]
    )

    response = await client.generate(
        prompt="a sunset over the ocean",
        model="glm-image",
        aspect_ratio="16:9",
        image_size="2K",
    )

    assert response.images[0].startswith("data:image/png;base64,")
    call = fake.calls[0]
    assert call["url"] == "https://open.bigmodel.cn/api/paas/v4/images/generations"
    assert call["headers"]["Authorization"] == "Bearer sk-zhipu-test"
    assert call["headers"]["X-Test"] == "1"
    body = call["json"]
    assert body["model"] == "glm-image"
    assert body["prompt"] == "a sunset over the ocean"
    assert body["size"] == "1728x960"
    assert body["watermark_enabled"] is False


@pytest.mark.asyncio
async def test_zhipu_image_generation_with_explicit_size() -> None:
    fake = FakeClient(FakeResponse({"data": [{"url": "https://cdn.example/image.png"}]}))
    fake.get_response = FakeResponse({}, content=PNG_BYTES)
    client = ZhipuImageGenerationClient(
        api_key="sk-zhipu-test",
        client=fake,  # type: ignore[arg-type]
    )

    await client.generate(
        prompt="a cat",
        model="cogview-4",
        image_size="1024x1024",
    )

    body = fake.calls[0]["json"]
    assert body["size"] == "1024x1024"


@pytest.mark.asyncio
async def test_zhipu_image_generation_downloads_url_response() -> None:
    fake = FakeClient(FakeResponse({"data": [{"url": "https://cdn.example/image.png"}]}))
    fake.get_response = FakeResponse({}, content=PNG_BYTES)
    client = ZhipuImageGenerationClient(
        api_key="sk-zhipu-test",
        client=fake,  # type: ignore[arg-type]
    )

    response = await client.generate(prompt="draw", model="glm-image")

    assert response.images[0].startswith("data:image/png;base64,")
    assert fake.get_calls[0]["url"] == "https://cdn.example/image.png"


@pytest.mark.asyncio
async def test_zhipu_image_generation_requires_api_key() -> None:
    client = ZhipuImageGenerationClient(api_key=None)

    with pytest.raises(ImageGenerationError, match="API key"):
        await client.generate(prompt="draw", model="glm-image")


@pytest.mark.asyncio
async def test_zhipu_image_generation_no_images_raises() -> None:
    fake = FakeClient(FakeResponse({"data": [{"text": "sorry"}]}))
    client = ZhipuImageGenerationClient(api_key="sk-zhipu-test", client=fake)  # type: ignore[arg-type]

    with pytest.raises(ImageGenerationError, match="returned no images"):
        await client.generate(prompt="draw", model="glm-image")


@pytest.mark.asyncio
async def test_zhipu_image_generation_rejects_reference_images() -> None:
    client = ZhipuImageGenerationClient(api_key="sk-zhipu-test")

    with pytest.raises(ImageGenerationError, match="reference images"):
        await client.generate(
            prompt="edit this",
            model="glm-image",
            reference_images=["ref.png"],
        )
