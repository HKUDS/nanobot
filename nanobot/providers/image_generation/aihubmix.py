"""AIHubMix image generation client."""

from __future__ import annotations

import base64
from typing import Any

import httpx

from nanobot.providers.image_generation.base import (
    GeneratedImageResponse,
    ImageGenerationError,
    ImageGenerationProvider,
    _b64_image_data_url,
    image_path_to_data_url,
)
from nanobot.utils.helpers import detect_image_mime

_AIHUBMIX_TIMEOUT_S = 300.0
_AIHUBMIX_ASPECT_RATIO_SIZES = {
    "1:1": "1024x1024",
    "3:4": "1024x1536",
    "9:16": "1024x1536",
    "4:3": "1536x1024",
    "16:9": "1536x1024",
}


def _aihubmix_size(aspect_ratio: str | None, image_size: str | None) -> str:
    """Return an OpenAI Images API size string for AIHubMix.

    The WebUI emits compact size hints like ``1K`` for OpenRouter. AIHubMix's
    Images API expects OpenAI-style dimensions or ``auto``, so only pass
    through explicit dimension strings and otherwise derive the closest
    supported orientation from aspect ratio.
    """
    if image_size and "x" in image_size.lower():
        return image_size
    if aspect_ratio in _AIHUBMIX_ASPECT_RATIO_SIZES:
        return _AIHUBMIX_ASPECT_RATIO_SIZES[aspect_ratio]
    return "auto"


def _aihubmix_model_path(model: str) -> str:
    if "/" in model:
        return model
    if model.startswith(("gpt-image-", "dall-e-")):
        return f"openai/{model}"
    return model


async def _download_image_data_url(
    client: httpx.AsyncClient,
    url: str,
) -> str:
    response = await client.get(url)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = response.text[:500]
        raise ImageGenerationError(f"failed to download generated image: {detail}") from exc
    raw = response.content
    mime = detect_image_mime(raw)
    if mime is None:
        raise ImageGenerationError("generated image URL did not return a supported image")
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{encoded}"


async def _aihubmix_images_from_payload(
    client: httpx.AsyncClient,
    payload: dict[str, Any],
) -> list[str]:
    images: list[str] = []
    candidates: list[Any] = []
    if "data" in payload:
        candidates.append(payload["data"])
    if "output" in payload:
        candidates.append(payload["output"])

    async def collect(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                await collect(item)
            return
        if isinstance(value, str):
            if value.startswith("data:image/"):
                images.append(value)
            elif value.startswith(("http://", "https://")):
                images.append(await _download_image_data_url(client, value))
            return
        if not isinstance(value, dict):
            return

        b64_json = value.get("b64_json")
        if isinstance(b64_json, str) and b64_json:
            images.append(_b64_image_data_url(b64_json))
        elif b64_json is not None:
            await collect(b64_json)

        bytes_base64 = value.get("bytesBase64") or value.get("bytes_base64") or value.get("base64")
        if isinstance(bytes_base64, str) and bytes_base64:
            images.append(_b64_image_data_url(bytes_base64))

        image_url = value.get("image_url") or value.get("imageUrl")
        if isinstance(image_url, dict):
            await collect(image_url.get("url"))
        elif image_url is not None:
            await collect(image_url)

        url_value = value.get("url")
        if url_value is not None:
            await collect(url_value)

        for key in ("images", "image", "output"):
            if key in value:
                await collect(value[key])

    for candidate in candidates:
        await collect(candidate)
    return images


class AIHubMixImageGenerationClient(ImageGenerationProvider):
    """Small async client for AIHubMix unified image generation."""

    provider_name = "aihubmix"
    missing_key_message = (
        "AIHubMix API key is not configured. Set providers.aihubmix.apiKey."
    )
    default_timeout = _AIHUBMIX_TIMEOUT_S

    def _default_base_url(self) -> str:
        return "https://aihubmix.com/v1"

    async def generate(
        self,
        *,
        prompt: str,
        model: str,
        reference_images: list[str] | None = None,
        aspect_ratio: str | None = None,
        image_size: str | None = None,
    ) -> GeneratedImageResponse:
        if not self.api_key:
            raise ImageGenerationError(self.missing_key_message)

        refs = list(reference_images or [])
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            **self.extra_headers,
        }
        size = _aihubmix_size(aspect_ratio, image_size)

        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        try:
            return await self._generate_with_client(
                client,
                prompt=prompt,
                model=model,
                reference_images=refs,
                size=size,
                headers=headers,
            )
        finally:
            if self._client is None:
                await client.aclose()

    async def _generate_with_client(
        self,
        client: httpx.AsyncClient,
        *,
        prompt: str,
        model: str,
        reference_images: list[str],
        size: str,
        headers: dict[str, str],
    ) -> GeneratedImageResponse:
        image_input: str | list[str] | None = None
        if reference_images:
            image_refs = [image_path_to_data_url(path) for path in reference_images]
            image_input = image_refs[0] if len(image_refs) == 1 else image_refs

        input_body: dict[str, Any] = {
            "prompt": prompt,
            "n": 1,
            "size": size,
        }
        if image_input is not None:
            input_body["image"] = image_input
        input_body.update(self.extra_body)

        body = {"input": input_body}
        model_path = _aihubmix_model_path(model)
        url = f"{self.api_base}/models/{model_path}/predictions"
        try:
            response = await client.post(
                url,
                headers={**headers, "Content-Type": "application/json"},
                json=body,
            )
        except httpx.TimeoutException as exc:
            raise ImageGenerationError("AIHubMix image generation timed out") from exc
        except httpx.RequestError as exc:
            raise ImageGenerationError(f"AIHubMix image generation request failed: {exc}") from exc

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text[:500]
            raise ImageGenerationError(f"AIHubMix image generation failed: {detail}") from exc

        payload = response.json()
        images = await _aihubmix_images_from_payload(client, payload)

        self._require_images(images, payload)

        return GeneratedImageResponse(images=images, content="", raw=payload)
