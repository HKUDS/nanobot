"""MiniMax image generation client."""

from __future__ import annotations

from typing import Any

import httpx

from nanobot.providers.image_generation.base import (
    GeneratedImageResponse,
    ImageGenerationError,
    ImageGenerationProvider,
    _b64_image_data_url,
    image_path_to_data_url,
)

_MINIMAX_TIMEOUT_S = 300.0

_MINIMAX_ASPECT_RATIO_SIZES = {
    "1:1": "1:1",
    "16:9": "16:9",
    "4:3": "4:3",
    "3:2": "3:2",
    "2:3": "2:3",
    "3:4": "3:4",
    "9:16": "9:16",
    "21:9": "21:9",
}


def _minimax_images_from_payload(payload: dict[str, Any]) -> list[str]:
    """Extract base64 images from MiniMax API response.

    MiniMax returns images in ``data.image_base64`` (list of base64 strings).
    """
    images: list[str] = []
    data = payload.get("data")
    if not isinstance(data, dict):
        return images
    for b64 in data.get("image_base64") or []:
        if isinstance(b64, str) and b64:
            images.append(_b64_image_data_url(b64))
    return images


class MiniMaxImageGenerationClient(ImageGenerationProvider):
    """Async client for MiniMax image generation API."""

    provider_name = "minimax"
    missing_key_message = (
        "MiniMax API key is not configured. Set providers.minimax.apiKey."
    )
    default_timeout = _MINIMAX_TIMEOUT_S

    def _default_base_url(self) -> str:
        return "https://api.minimaxi.com/v1"

    def _resolve_aspect_ratio(self, aspect_ratio: str | None) -> str:
        if aspect_ratio and aspect_ratio in _MINIMAX_ASPECT_RATIO_SIZES:
            return _MINIMAX_ASPECT_RATIO_SIZES[aspect_ratio]
        return "1:1"

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

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }

        body: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "response_format": "base64",
        }

        resolved_ratio = self._resolve_aspect_ratio(aspect_ratio)
        body["aspect_ratio"] = resolved_ratio

        refs = list(reference_images or [])
        if refs:
            image_refs = [image_path_to_data_url(path) for path in refs]
            body["subject_reference"] = [
                {"type": "character", "image_file": ref} for ref in image_refs
            ]

        body.update(self.extra_body)

        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        try:
            return await self._generate_with_client(client, body, headers)
        finally:
            if self._client is None:
                await client.aclose()

    async def _generate_with_client(
        self,
        client: httpx.AsyncClient,
        body: dict[str, Any],
        headers: dict[str, str],
    ) -> GeneratedImageResponse:
        url = f"{self.api_base}/image_generation"
        try:
            response = await client.post(url, headers=headers, json=body)
        except httpx.TimeoutException as exc:
            raise ImageGenerationError("MiniMax image generation timed out") from exc
        except httpx.RequestError as exc:
            raise ImageGenerationError(f"MiniMax image generation request failed: {exc}") from exc

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text[:500]
            raise ImageGenerationError(f"MiniMax image generation failed: {detail}") from exc

        payload = response.json()
        images = _minimax_images_from_payload(payload)

        self._require_images(images, payload)

        return GeneratedImageResponse(images=images, content="", raw=payload)
