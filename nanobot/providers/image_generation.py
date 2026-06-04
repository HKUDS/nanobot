"""Image generation provider helpers."""

from __future__ import annotations

import asyncio
import base64
import binascii
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from nanobot.providers.registry import find_by_name
from nanobot.utils.helpers import detect_image_mime

_OPENROUTER_ATTRIBUTION_HEADERS = {
    "HTTP-Referer": "https://github.com/HKUDS/nanobot",
    "X-OpenRouter-Title": "nanobot",
    "X-OpenRouter-Categories": "cli-agent,personal-agent",
}
_DEFAULT_TIMEOUT_S = 120.0
_AIHUBMIX_TIMEOUT_S = 300.0
_AIHUBMIX_ASPECT_RATIO_SIZES = {
    "1:1": "1024x1024",
    "3:4": "1024x1536",
    "9:16": "1024x1536",
    "4:3": "1536x1024",
    "16:9": "1536x1024",
}
_GEMINI_DEFAULT_TIMEOUT_S = 120.0
_GEMINI_IMAGEN_ASPECT_RATIOS = {"1:1", "9:16", "16:9", "3:4", "4:3"}
_OLLAMA_DEFAULT_SIDE = 1024
_OLLAMA_SIZE_PRESETS = {
    "1K": 1024,
    "2K": 2048,
    "4K": 4096,
}
_OLLAMA_EXPLICIT_SIZE_RE = re.compile(r"^\s*(\d+)\s*[xX]\s*(\d+)\s*$")
_OLLAMA_ASPECT_RATIO_RE = re.compile(r"^\s*(\d+)\s*:\s*(\d+)\s*$")


class ImageGenerationError(RuntimeError):
    """Raised when the image generation provider cannot return images."""


@dataclass(frozen=True)
class GeneratedImageResponse:
    """Images and optional text returned by the provider."""

    images: list[str]
    content: str
    raw: dict[str, Any]


def _read_image_b64(path: str | Path) -> tuple[str, str]:
    """Return ``(mime, base64)`` for the image at ``path``."""
    p = Path(path).expanduser()
    raw = p.read_bytes()
    mime = detect_image_mime(raw)
    if mime is None:
        raise ImageGenerationError(f"unsupported reference image: {p}")
    return mime, base64.b64encode(raw).decode("ascii")


def image_path_to_data_url(path: str | Path) -> str:
    """Convert a local image path to an image data URL."""
    mime, encoded = _read_image_b64(path)
    return f"data:{mime};base64,{encoded}"


def image_path_to_inline_data(path: str | Path) -> dict[str, str]:
    """Convert a local image path to a Gemini ``inlineData`` payload dict."""
    mime, encoded = _read_image_b64(path)
    return {"mimeType": mime, "data": encoded}


def _b64_image_data_url(value: str) -> str:
    encoded = "".join(value.split())
    try:
        raw = base64.b64decode(encoded, validate=True)
    except binascii.Error as exc:
        raise ImageGenerationError("generated image payload was not valid base64") from exc
    mime = detect_image_mime(raw)
    if mime is None:
        raise ImageGenerationError("generated image payload was not a supported image")
    return f"data:{mime};base64,{encoded}"


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


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_IMAGE_GEN_PROVIDERS: dict[str, type[ImageGenerationProvider]] = {}


def register_image_gen_provider(cls: type[ImageGenerationProvider]) -> None:
    """Register an image provider at import time only.

    The registry is populated by module side effects so provider discovery
    stays lazy and consistent across the process.
    """
    name = cls.provider_name
    if not name:
        raise ValueError(f"{cls.__name__} must set provider_name")
    _IMAGE_GEN_PROVIDERS[name] = cls


def get_image_gen_provider(name: str) -> type[ImageGenerationProvider] | None:
    return _IMAGE_GEN_PROVIDERS.get(name)


def image_gen_provider_names() -> tuple[str, ...]:
    """Return registered image generation provider names in registry order."""
    return tuple(_IMAGE_GEN_PROVIDERS)


def image_gen_provider_configs(config: Any) -> dict[str, Any]:
    providers_cfg = config.providers
    return {
        name: pc
        for name in _IMAGE_GEN_PROVIDERS
        if (pc := getattr(providers_cfg, name, None)) is not None
    }


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class ImageGenerationProvider(ABC):
    """Base class for image generation provider clients."""

    provider_name: str = ""
    missing_key_message: str = ""
    default_timeout: float = _DEFAULT_TIMEOUT_S

    def __init__(
        self,
        *,
        api_key: str | None,
        api_base: str | None = None,
        extra_headers: dict[str, str] | None = None,
        extra_body: dict[str, Any] | None = None,
        timeout: float | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.api_base = self._resolve_base_url(api_base)
        self.extra_headers = extra_headers or {}
        self.extra_body = extra_body or {}
        self.timeout = timeout if timeout is not None else self.default_timeout
        self._client = client

    def _resolve_base_url(self, api_base: str | None) -> str:
        if api_base:
            return api_base.rstrip("/")
        spec = find_by_name(self.provider_name)
        if spec and spec.default_api_base:
            return spec.default_api_base.rstrip("/")
        return self._default_base_url()

    def _default_base_url(self) -> str:
        return ""

    @abstractmethod
    async def generate(
        self,
        *,
        prompt: str,
        model: str,
        reference_images: list[str] | None = None,
        aspect_ratio: str | None = None,
        image_size: str | None = None,
    ) -> GeneratedImageResponse: ...

    def _require_images(self, images: list[str], data: dict[str, Any]) -> None:
        if images:
            return
        provider_error = data.get("error") if isinstance(data, dict) else None
        label = self.provider_name
        if provider_error:
            raise ImageGenerationError(f"{label} returned no images: {provider_error}")
        raise ImageGenerationError(f"{label} returned no images for this request")

    async def _http_post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: dict[str, Any],
        client: httpx.AsyncClient | None = None,
    ) -> httpx.Response:
        if client is not None:
            return await client.post(url, headers=headers, json=body)
        if self._client is not None:
            return await self._client.post(url, headers=headers, json=body)
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            return await c.post(url, headers=headers, json=body)


class OpenRouterImageGenerationClient(ImageGenerationProvider):
    """Small async client for OpenRouter Chat Completions image generation."""

    provider_name = "openrouter"
    missing_key_message = (
        "OpenRouter API key is not configured. Set providers.openrouter.apiKey."
    )

    def _default_base_url(self) -> str:
        return "https://openrouter.ai/api/v1"

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

        content: str | list[dict[str, Any]]
        references = list(reference_images or [])
        if references:
            blocks: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
            blocks.extend(
                {"type": "image_url", "image_url": {"url": image_path_to_data_url(path)}}
                for path in references
            )
            content = blocks
        else:
            content = prompt

        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "modalities": ["image", "text"],
            "stream": False,
        }
        image_config: dict[str, str] = {}
        if aspect_ratio:
            image_config["aspect_ratio"] = aspect_ratio
        if image_size:
            image_config["image_size"] = image_size
        if image_config:
            body["image_config"] = image_config
        body.update(self.extra_body)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **_OPENROUTER_ATTRIBUTION_HEADERS,
            **self.extra_headers,
        }
        url = f"{self.api_base}/chat/completions"
        response = await self._http_post(url, headers=headers, body=body)

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text[:500]
            raise ImageGenerationError(f"OpenRouter image generation failed: {detail}") from exc

        data = response.json()
        images: list[str] = []
        text_parts: list[str] = []
        for choice in data.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message") or {}
            if isinstance(message.get("content"), str):
                text_parts.append(message["content"])
            for image in message.get("images") or []:
                if not isinstance(image, dict):
                    continue
                image_url = image.get("image_url") or image.get("imageUrl") or {}
                url_value = image_url.get("url") if isinstance(image_url, dict) else None
                if isinstance(url_value, str) and url_value.startswith("data:image/"):
                    images.append(url_value)

        self._require_images(images, data)

        return GeneratedImageResponse(
            images=images,
            content="\n".join(part for part in text_parts if part).strip(),
            raw=data,
        )


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
            response = await self._http_post(
                url,
                headers={**headers, "Content-Type": "application/json"},
                body=body,
                client=client,
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


def _http_error_detail(response: httpx.Response) -> str:
    """Extract a readable error message from an HTTP error response."""
    try:
        data = response.json()
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict):
                return err.get("message") or str(err)
            if err:
                return str(err)
    except Exception:
        pass
    return response.text[:500] or "<empty response body>"


def _round_to_multiple(value: float, multiple: int = 8) -> int:
    rounded = int(round(value / multiple) * multiple)
    return max(multiple, rounded)


def _ollama_dimensions(aspect_ratio: str | None, image_size: str | None) -> tuple[int, int]:
    if image_size:
        size = image_size.strip()
        explicit = _OLLAMA_EXPLICIT_SIZE_RE.fullmatch(size)
        if explicit:
            return int(explicit.group(1)), int(explicit.group(2))
        long_side = _OLLAMA_SIZE_PRESETS.get(size.upper(), _OLLAMA_DEFAULT_SIDE)
    else:
        long_side = _OLLAMA_DEFAULT_SIDE

    if not aspect_ratio:
        return long_side, long_side

    ratio = _OLLAMA_ASPECT_RATIO_RE.fullmatch(aspect_ratio.strip())
    if ratio is None:
        return long_side, long_side

    width_ratio = int(ratio.group(1))
    height_ratio = int(ratio.group(2))
    if width_ratio <= 0 or height_ratio <= 0:
        return long_side, long_side

    if width_ratio >= height_ratio:
        width = long_side
        height = _round_to_multiple(long_side * height_ratio / width_ratio)
    else:
        height = long_side
        width = _round_to_multiple(long_side * width_ratio / height_ratio)
    return max(8, width), max(8, height)


def _ollama_image_data_url(value: str) -> str:
    if value.startswith("data:image/"):
        return value
    return _b64_image_data_url(value)


def _ollama_images_from_payload(payload: dict[str, Any]) -> list[str]:
    images: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, str) and value:
            images.append(_ollama_image_data_url(value))
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(payload.get("image"))
    collect(payload.get("images"))
    return images


class OllamaImageGenerationClient(ImageGenerationProvider):
    """Async client for Ollama native image generation models."""

    provider_name = "ollama"
    default_timeout = 300.0

    def _default_base_url(self) -> str:
        return "http://localhost:11434/api"

    def _resolve_base_url(self, api_base: str | None) -> str:
        if api_base:
            base = api_base.rstrip("/")
            if base.endswith("/v1"):
                return f"{base[:-3]}/api"
            return base
        return self._default_base_url()

    async def generate(
        self,
        *,
        prompt: str,
        model: str,
        reference_images: list[str] | None = None,
        aspect_ratio: str | None = None,
        image_size: str | None = None,
    ) -> GeneratedImageResponse:
        if reference_images:
            raise ImageGenerationError(
                "Ollama image generation does not support reference images"
            )

        width, height = _ollama_dimensions(aspect_ratio, image_size)
        body: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "width": width,
            "height": height,
            "steps": 0,
        }
        body.update(self.extra_body)
        body["stream"] = False

        headers = {
            "Content-Type": "application/json",
            **self.extra_headers,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        url = f"{self.api_base}/generate"
        response = await self._http_post(url, headers=headers, body=body)

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = _http_error_detail(response)
            logger.error(
                "Ollama image generation failed (HTTP {}): {}",
                response.status_code,
                detail,
            )
            raise ImageGenerationError(
                f"Ollama image generation failed (HTTP {response.status_code}): {detail}"
            ) from exc

        data = response.json()
        images = _ollama_images_from_payload(data)

        self._require_images(images, data)

        response_text = data.get("response")
        content = response_text if isinstance(response_text, str) else ""

        return GeneratedImageResponse(images=images, content=content, raw=data)


class GeminiImageGenerationClient(ImageGenerationProvider):
    """Async client for Gemini/Imagen image generation via the Generative Language API."""

    provider_name = "gemini"
    missing_key_message = (
        "Gemini API key is not configured. Set providers.gemini.apiKey."
    )
    default_timeout = _GEMINI_DEFAULT_TIMEOUT_S

    def _default_base_url(self) -> str:
        return "https://generativelanguage.googleapis.com/v1beta"

    def _resolve_base_url(self, api_base: str | None) -> str:
        # Gemini chat completions use the registry's OpenAI-compatible shim.
        # Image generation must hit the native Generative Language API, so we
        # intentionally bypass the shared registry lookup here.
        if api_base:
            return api_base.rstrip("/")
        return self._default_base_url()

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
        if "imagen" in model.lower():
            if reference_images:
                logger.warning(
                    "Imagen models do not support reference images; "
                    "ignoring {} reference image(s) for {}",
                    len(reference_images),
                    model,
                )
            return await self._generate_imagen(
                prompt=prompt, model=model, aspect_ratio=aspect_ratio
            )
        return await self._generate_gemini_flash(
            prompt=prompt, model=model, reference_images=reference_images or []
        )

    async def _generate_imagen(
        self,
        *,
        prompt: str,
        model: str,
        aspect_ratio: str | None,
    ) -> GeneratedImageResponse:
        parameters: dict[str, Any] = {"sampleCount": 1}
        if aspect_ratio in _GEMINI_IMAGEN_ASPECT_RATIOS:
            parameters["aspectRatio"] = aspect_ratio
        body: dict[str, Any] = {
            "instances": [{"prompt": prompt}],
            "parameters": parameters,
        }
        body.update(self.extra_body)

        url = f"{self.api_base}/models/{model}:predict"
        headers = {
            "x-goog-api-key": self.api_key or "",
            "Content-Type": "application/json",
            **self.extra_headers,
        }
        response = await self._http_post(url, headers=headers, body=body)

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = _http_error_detail(response)
            logger.error("Gemini Imagen generation failed (HTTP {}): {}", response.status_code, detail)
            raise ImageGenerationError(
                f"Gemini Imagen generation failed (HTTP {response.status_code}): {detail}"
            ) from exc

        data = response.json()
        images: list[str] = []
        for prediction in data.get("predictions") or []:
            if not isinstance(prediction, dict):
                continue
            b64 = prediction.get("bytesBase64Encoded")
            mime = prediction.get("mimeType", "image/png")
            if isinstance(b64, str) and b64:
                images.append(f"data:{mime};base64,{b64}")

        self._require_images(images, data)

        return GeneratedImageResponse(images=images, content="", raw=data)

    async def _generate_gemini_flash(
        self,
        *,
        prompt: str,
        model: str,
        reference_images: list[str],
    ) -> GeneratedImageResponse:
        parts: list[dict[str, Any]] = [
            {"inlineData": image_path_to_inline_data(path)} for path in reference_images
        ]
        parts.append({"text": prompt})

        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
        }
        body.update(self.extra_body)

        url = f"{self.api_base}/models/{model}:generateContent"
        headers = {
            "x-goog-api-key": self.api_key or "",
            "Content-Type": "application/json",
            **self.extra_headers,
        }
        response = await self._http_post(url, headers=headers, body=body)

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = _http_error_detail(response)
            logger.error("Gemini image generation failed (HTTP {}): {}", response.status_code, detail)
            raise ImageGenerationError(
                f"Gemini image generation failed (HTTP {response.status_code}): {detail}"
            ) from exc

        data = response.json()
        images: list[str] = []
        text_parts: list[str] = []
        for candidate in data.get("candidates") or []:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content") or {}
            for part in content.get("parts") or []:
                if not isinstance(part, dict):
                    continue
                if "text" in part:
                    text_parts.append(part["text"])
                inline = part.get("inlineData")
                if isinstance(inline, dict):
                    mime = inline.get("mimeType", "image/png")
                    b64 = inline.get("data", "")
                    if b64:
                        images.append(f"data:{mime};base64,{b64}")

        self._require_images(images, data)

        return GeneratedImageResponse(
            images=images,
            content="\n".join(t for t in text_parts if t).strip(),
            raw=data,
        )


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

        return await self._generate_with_client(body, headers)

    async def _generate_with_client(
        self,
        body: dict[str, Any],
        headers: dict[str, str],
    ) -> GeneratedImageResponse:
        url = f"{self.api_base}/image_generation"
        try:
            response = await self._http_post(url, headers=headers, body=body)
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


# ---------------------------------------------------------------------------
# OpenAI image generation
# ---------------------------------------------------------------------------

_OPENAI_DALLE2_SUPPORTED_SIZES = {"256x256", "512x512", "1024x1024"}
_OPENAI_DALLE3_SUPPORTED_SIZES = {"1024x1024", "1792x1024", "1024x1792"}
_OPENAI_GPT_IMAGE_SUPPORTED_SIZES = {
    "1024x1024",
    "1536x1024",
    "1024x1536",
    "auto",
}
_OPENAI_DALLE2_ASPECT_RATIO_SIZES = {
    "1:1": "1024x1024",
    "16:9": "1024x1024",
    "9:16": "1024x1024",
    "3:4": "1024x1024",
    "4:3": "1024x1024",
}
_OPENAI_DALLE3_ASPECT_RATIO_SIZES = {
    "1:1": "1024x1024",
    "16:9": "1792x1024",
    "9:16": "1024x1792",
    "3:4": "1024x1792",
    "4:3": "1792x1024",
}
_OPENAI_GPT_IMAGE_ASPECT_RATIO_SIZES = {
    "1:1": "1024x1024",
    "16:9": "1536x1024",
    "9:16": "1024x1536",
    "3:4": "1024x1536",
    "4:3": "1536x1024",
}


class OpenAIImageGenerationClient(ImageGenerationProvider):
    """OpenAI Images API using an API key (``providers.openai.apiKey``)."""

    provider_name = "openai"
    missing_key_message = (
        "OpenAI API key is not configured. Set providers.openai.apiKey."
    )

    def _default_base_url(self) -> str:
        return "https://api.openai.com/v1"

    @staticmethod
    def _strip_model_prefix(model: str) -> str:
        """Remove ``openai/`` prefix if present (OpenRouter convention)."""
        if model.startswith("openai/") or model.startswith("openai_codex/"):
            return model.split("/", 1)[1]
        return model

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

        if reference_images:
            logger.warning(
                "DALL-E models do not support reference images; "
                "ignoring {} reference image(s) for {}",
                len(reference_images),
                model,
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }

        clean_model = self._strip_model_prefix(model)
        body: dict[str, Any] = {
            "model": clean_model,
            "prompt": prompt,
        }

        if not _openai_is_gpt_image_model(clean_model):
            body["response_format"] = "b64_json"
            body["n"] = 1

        size = _openai_size(clean_model, aspect_ratio, image_size)
        if size:
            body["size"] = size

        body.update(self.extra_body)

        logger.info("OpenAI Images API request: POST {}/images/generations body={}", self.api_base, body)

        response = await self._http_post(
            f"{self.api_base}/images/generations",
            headers=headers,
            body=body,
        )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text[:1000]
            logger.error("OpenAI Images API error ({}): {}", response.status_code, detail)
            raise ImageGenerationError(
                f"OpenAI image generation failed (HTTP {response.status_code}): {detail}"
            ) from exc

        payload = response.json()
        logger.info("OpenAI Images API response ({}): {}", response.status_code,
                       {k: v for k, v in payload.items() if k != "data"})

        client = self._client
        owns_client = client is None
        if owns_client:
            client = httpx.AsyncClient(timeout=self.timeout)
        try:
            images = await _openai_images_from_payload(client, payload)
        finally:
            if owns_client:
                await client.aclose()

        self._require_images(images, payload)

        return GeneratedImageResponse(images=images, content="", raw=payload)


class CustomImageGenerationClient(ImageGenerationProvider):
    """OpenAI-compatible Images API for user-configured custom providers."""

    provider_name = "custom"
    missing_base_message = (
        "Custom image generation API base is not configured. Set providers.custom.apiBase."
    )

    def _default_base_url(self) -> str:
        return ""

    @staticmethod
    def _custom_size(aspect_ratio: str | None, image_size: str | None) -> str:
        return _openai_size("gpt-image-2", aspect_ratio, image_size)

    async def generate(
        self,
        *,
        prompt: str,
        model: str,
        reference_images: list[str] | None = None,
        aspect_ratio: str | None = None,
        image_size: str | None = None,
    ) -> GeneratedImageResponse:
        if not self.api_base:
            raise ImageGenerationError(self.missing_base_message)

        if reference_images:
            logger.warning(
                "Custom image generation does not support reference images; "
                "ignoring {} reference image(s) for {}",
                len(reference_images),
                model,
            )

        headers: dict[str, str] = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        headers.update(self.extra_headers)

        body: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "response_format": "b64_json",
            "n": 1,
            "size": self._custom_size(aspect_ratio, image_size),
        }
        body.update(self.extra_body)

        logger.info("Custom Images API request: POST {}/images/generations body={}", self.api_base, body)

        response = await self._http_post(
            f"{self.api_base}/images/generations",
            headers=headers,
            body=body,
        )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text[:1000]
            logger.error("Custom Images API error ({}): {}", response.status_code, detail)
            raise ImageGenerationError(
                f"Custom image generation failed (HTTP {response.status_code}): {detail}"
            ) from exc

        payload = response.json()
        logger.info("Custom Images API response ({}): {}", response.status_code,
                       {k: v for k, v in payload.items() if k != "data"})

        client = self._client
        owns_client = client is None
        if owns_client:
            client = httpx.AsyncClient(timeout=self.timeout)
        try:
            images = await _openai_images_from_payload(client, payload)
        finally:
            if owns_client:
                await client.aclose()

        self._require_images(images, payload)

        return GeneratedImageResponse(images=images, content="", raw=payload)


# ---------------------------------------------------------------------------
# OpenAI Codex image generation
# ---------------------------------------------------------------------------


class CodexImageGenerationClient(ImageGenerationProvider):
    """OpenAI image generation via Codex subscription OAuth.

    Uses the Codex Responses API with the ``image_generation`` tool
    (the same mechanism ChatGPT uses internally).  No API key required —
    the Codex OAuth token from ``oauth_cli_kit`` is used instead.
    """

    provider_name = "openai_codex"
    missing_key_message = (
        "Codex OAuth token is unavailable. "
        "Log in with Codex subscription first."
    )

    def _default_base_url(self) -> str:
        return "https://chatgpt.com/backend-api"

    def _codex_model(self, model: str) -> str:
        """Strip the ``openai-codex/`` prefix if present."""
        if model.startswith(("openai-codex/", "openai_codex/")):
            return model.split("/", 1)[1]
        return model

    async def generate(
        self,
        *,
        prompt: str,
        model: str,
        reference_images: list[str] | None = None,
        aspect_ratio: str | None = None,
        image_size: str | None = None,
    ) -> GeneratedImageResponse:
        try:
            from oauth_cli_kit import get_token as get_codex_token
        except ImportError:
            raise ImageGenerationError(self.missing_key_message)

        try:
            token = await asyncio.to_thread(get_codex_token)
        except Exception as exc:
            raise ImageGenerationError(self.missing_key_message) from exc
        if not token or not token.access:
            raise ImageGenerationError(self.missing_key_message)

        logger.info(
            "Using Codex OAuth token for image generation (account: {})",
            token.account_id,
        )

        if reference_images:
            logger.warning(
                "Codex image generation does not support reference images; "
                "ignoring {} reference image(s)",
                len(reference_images),
            )

        headers = {
            "Authorization": f"Bearer {token.access}",
            "chatgpt-account-id": token.account_id,
            "OpenAI-Beta": "responses=experimental",
            "originator": "nanobot",
            "User-Agent": "nanobot (python)",
            "Content-Type": "application/json",
            **self.extra_headers,
        }

        body: dict[str, Any] = {
            "model": self._codex_model(model),
            "instructions": "Generate an image based on the user's request.",
            "input": [{"role": "user", "content": prompt}],
            "tools": [{"type": "image_generation"}],
            "tool_choice": "auto",
            "stream": True,
            "store": False,
        }
        body.update(self.extra_body)

        logger.info("Codex Responses API request: POST {}/codex/responses body={}",
                       self.api_base, {k: v for k, v in body.items() if k != "input"})

        response = await self._http_post(
            f"{self.api_base}/codex/responses",
            headers=headers,
            body=body,
        )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text[:1000]
            logger.error("Codex Responses API error ({}): {}", response.status_code, detail)
            raise ImageGenerationError(
                f"Codex image generation failed (HTTP {response.status_code}): {detail}"
            ) from exc

        images, content_text = await _parse_codex_sse_images(response)

        raw = {"status": "completed"}
        self._require_images(images, raw)

        return GeneratedImageResponse(images=images, content=content_text, raw=raw)


def _openai_size(
    model: str,
    aspect_ratio: str | None,
    image_size: str | None,
) -> str:
    """Resolve aspect ratio or image_size to an OpenAI Images API size string."""
    sizes, supported_sizes = _openai_size_options(model)
    explicit_size = _normalize_openai_image_size(image_size)
    if explicit_size and _openai_explicit_size_supported(
        explicit_size,
        supported_sizes=supported_sizes,
    ):
        return explicit_size
    if explicit_size:
        logger.warning(
            "OpenAI image size '{}' is not supported by {}; using aspect ratio/default size",
            explicit_size,
            model,
        )
    if aspect_ratio and aspect_ratio in sizes:
        return sizes[aspect_ratio]
    return "1024x1024"


def _openai_is_gpt_image_model(model: str) -> bool:
    normalized = model.lower()
    return normalized.startswith(("gpt-image", "chatgpt-image"))


def _openai_size_options(model: str) -> tuple[dict[str, str], set[str] | None]:
    normalized = model.lower()
    if normalized.startswith("dall-e-2"):
        return _OPENAI_DALLE2_ASPECT_RATIO_SIZES, _OPENAI_DALLE2_SUPPORTED_SIZES
    if normalized.startswith("dall-e-3"):
        return _OPENAI_DALLE3_ASPECT_RATIO_SIZES, _OPENAI_DALLE3_SUPPORTED_SIZES
    if normalized.startswith("gpt-image-2"):
        return _OPENAI_GPT_IMAGE_ASPECT_RATIO_SIZES, None
    return _OPENAI_GPT_IMAGE_ASPECT_RATIO_SIZES, _OPENAI_GPT_IMAGE_SUPPORTED_SIZES


def _normalize_openai_image_size(image_size: str | None) -> str | None:
    if not image_size:
        return None
    normalized = image_size.strip().lower()
    return normalized or None


def _openai_explicit_size_supported(
    size: str,
    *,
    supported_sizes: set[str] | None,
) -> bool:
    if supported_sizes is not None:
        return size in supported_sizes
    width, sep, height = size.partition("x")
    return bool(sep and width.isdecimal() and height.isdecimal())


async def _openai_images_from_payload(
    client: httpx.AsyncClient,
    payload: dict[str, Any],
) -> list[str]:
    """Extract images from OpenAI Images API response.

    Handles both ``b64_json`` (preferred) and ``url`` (downloaded) formats.
    """
    images: list[str] = []
    for item in payload.get("data") or []:
        if not isinstance(item, dict):
            continue
        b64 = item.get("b64_json")
        if isinstance(b64, str) and b64:
            images.append(_b64_image_data_url(b64))
            continue
        url = item.get("url")
        if isinstance(url, str) and url:
            images.append(await _download_image_data_url(client, url))
    return images


def _codex_responses_images_from_payload(payload: dict[str, Any]) -> list[str]:
    """Extract images from Codex Responses API ``image_generation_call`` output."""
    images: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "image_generation_call":
            continue
        result = item.get("result")
        if isinstance(result, str):
            images.append(result if result.startswith("data:image/") else _b64_image_data_url(result))
            continue
        if isinstance(result, dict):
            image_url = result.get("image_url") or result.get("image") or ""
            if isinstance(image_url, str):
                images.append(image_url if image_url.startswith("data:image/") else _b64_image_data_url(image_url))
    return images


async def _parse_codex_sse_images(
    response: httpx.Response,
) -> tuple[list[str], str]:
    """Parse a Codex Responses API SSE stream for image generation output.

    Returns ``(images, content_text)``.
    """
    import json as _json

    images: list[str] = []
    text_parts: list[str] = []

    buffer: list[str] = []
    async for line_bytes in response.aiter_lines():
        line = line_bytes.strip()
        if line == "":
            if buffer:
                data_lines = []
                for bl in buffer:
                    if bl.startswith("data:"):
                        data_lines.append(bl[5:].strip())
                buffer.clear()
                if data_lines:
                    raw = "".join(data_lines)
                    if raw == "[DONE]":
                        break
                    try:
                        event = _json.loads(raw)
                    except Exception:
                        continue
                    ev_type = event.get("type", "")
                    if ev_type in ("error", "response.failed"):
                        logger.error("Codex SSE failure: {}", raw[:2000])
                    _collect_images_from_sse_event(event, images)
                    _collect_text_from_sse_event(event, text_parts)
            continue
        buffer.append(line)

    # flush remaining
    if buffer:
        data_lines = [bl[5:].strip() for bl in buffer if bl.startswith("data:")]
        raw = "".join(data_lines)
        if raw and raw != "[DONE]":
            try:
                event = _json.loads(raw)
            except Exception:
                pass
            else:
                _collect_images_from_sse_event(event, images)
                _collect_text_from_sse_event(event, text_parts)

    return images, "".join(text_parts).strip()


def _collect_images_from_sse_event(event: dict[str, Any], images: list[str]) -> None:
    if event.get("type") != "response.output_item.done":
        return
    item = event.get("item") or {}
    if item.get("type") != "image_generation_call":
        return
    result = item.get("result")
    if isinstance(result, str):
        if result.startswith("data:image/"):
            images.append(result)
        else:
            images.append(_b64_image_data_url(result))
    elif isinstance(result, dict):
        image_url = result.get("image_url") or result.get("image") or ""
        if isinstance(image_url, str):
            if image_url.startswith("data:image/"):
                images.append(image_url)
            else:
                images.append(_b64_image_data_url(image_url))


def _collect_text_from_sse_event(event: dict[str, Any], text_parts: list[str]) -> None:
    if event.get("type") == "response.output_text.delta":
        delta = event.get("delta")
        if isinstance(delta, str) and delta:
            text_parts.append(delta)


# ---------------------------------------------------------------------------
# StepFun (阶跃星辰) image generation
# ---------------------------------------------------------------------------

_STEPFUN_ASPECT_RATIO_SIZES = {
    "1:1": "1024x1024",
    "16:9": "1280x800",
    "9:16": "800x1280",
    "3:4": "768x1360",
    "4:3": "1360x768",
}


class StepFunImageGenerationClient(ImageGenerationProvider):
    """Async client for StepFun (阶跃星辰) image generation.

    Supports:
    - Text-to-image via step-image-edit-2 (default model)
    - Reference-image-guided generation via style_reference (step-1x-medium)
    """

    provider_name = "stepfun"
    missing_key_message = (
        "StepFun API key is not configured. Set providers.stepfun.apiKey."
    )
    default_timeout = 120.0

    def _default_base_url(self) -> str:
        return "https://api.stepfun.com/v1"

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
            "response_format": "b64_json",
            "n": 1,
        }

        # Map aspect ratio / image_size to StepFun size string
        size = _stepfun_size(aspect_ratio, image_size)
        if size:
            body["size"] = size

        # step-1x-medium supports style_reference for reference-image-guided generation
        refs = list(reference_images or [])
        if refs and "1x" in model:
            body["style_reference"] = {
                "source_url": image_path_to_data_url(refs[0]),
            }

        body.update(self.extra_body)

        response = await self._http_post(
            f"{self.api_base}/images/generations",
            headers=headers,
            body=body,
        )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text[:500]
            raise ImageGenerationError(
                f"StepFun image generation failed: {detail}"
            ) from exc

        payload = response.json()
        images = _stepfun_images_from_payload(payload)

        self._require_images(images, payload)

        return GeneratedImageResponse(images=images, content="", raw=payload)


def _stepfun_size(
    aspect_ratio: str | None,
    image_size: str | None,
) -> str:
    """Resolve aspect ratio / image_size to StepFun size string.

    StepFun expects ``WIDTHxHEIGHT`` (note: width x height, not the more
    common ``HxW`` order used by other providers).  The accepted sizes are
    ``1024x1024``, ``768x1360``, ``896x1184``, ``1360x768``, ``1184x896``.
    """
    if image_size and "x" in image_size.lower():
        return image_size
    if aspect_ratio and aspect_ratio in _STEPFUN_ASPECT_RATIO_SIZES:
        return _STEPFUN_ASPECT_RATIO_SIZES[aspect_ratio]
    return "1024x1024"


def _stepfun_images_from_payload(payload: dict[str, Any]) -> list[str]:
    """Extract base64 images from StepFun API response.

    StepFun returns images in ``data[].b64_json`` (base64 strings).
    """
    images: list[str] = []
    for item in payload.get("data") or []:
        if not isinstance(item, dict):
            continue
        b64 = item.get("b64_json")
        if isinstance(b64, str) and b64:
            images.append(_b64_image_data_url(b64))
    return images


# ---------------------------------------------------------------------------
# Zhipu (智谱) image generation
# ---------------------------------------------------------------------------

_ZHIPU_TIMEOUT_S = 300.0

_ZHIPU_ASPECT_RATIO_SIZES = {
    "1:1": "1280x1280",
    "16:9": "1728x960",
    "9:16": "960x1728",
    "3:4": "1088x1472",
    "4:3": "1472x1088",
}


class ZhipuImageGenerationClient(ImageGenerationProvider):
    """Async client for Zhipu (智谱) image generation API.

    Supports:
    - Text-to-image via glm-image, cogview-4, cogview-3-flash, etc.
    - Aspect ratio selection
    - Watermark control
    """

    provider_name = "zhipu"
    missing_key_message = "Zhipu API key is not configured. Set providers.zhipu.apiKey."
    default_timeout = _ZHIPU_TIMEOUT_S

    def _default_base_url(self) -> str:
        return "https://open.bigmodel.cn/api/paas/v4"

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

        if reference_images:
            raise ImageGenerationError(
                "Zhipu image generation does not support reference images"
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }

        body: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
        }

        size = _zhipu_size(aspect_ratio, image_size)
        if size:
            body["size"] = size

        body.update(self.extra_body)

        url = f"{self.api_base}/images/generations"

        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        try:
            return await self._generate_with_client(
                client,
                headers=headers,
                body=body,
                url=url,
            )
        finally:
            if self._client is None:
                await client.aclose()

    async def _generate_with_client(
        self,
        client: httpx.AsyncClient,
        *,
        headers: dict[str, str],
        body: dict[str, Any],
        url: str,
    ) -> GeneratedImageResponse:
        try:
            response = await self._http_post(url, headers=headers, body=body, client=client)
        except httpx.TimeoutException as exc:
            raise ImageGenerationError("Zhipu image generation timed out") from exc
        except httpx.RequestError as exc:
            raise ImageGenerationError(f"Zhipu image generation request failed: {exc}") from exc

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text[:500]
            raise ImageGenerationError(f"Zhipu image generation failed: {detail}") from exc

        payload = response.json()
        images = await _zhipu_images_from_payload(client, payload)

        self._require_images(images, payload)

        return GeneratedImageResponse(images=images, content="", raw=payload)


def _zhipu_size(
    aspect_ratio: str | None,
    image_size: str | None,
) -> str:
    """Resolve aspect ratio / image_size to Zhipu size string.

    Zhipu glm-image model supports: 1280x1280 (default), 1568x1056,
    1056x1568, 1472x1088, 1088x1472, 1728x960, 960x1728.
    """
    if image_size and "x" in image_size.lower():
        return image_size
    if aspect_ratio and aspect_ratio in _ZHIPU_ASPECT_RATIO_SIZES:
        return _ZHIPU_ASPECT_RATIO_SIZES[aspect_ratio]
    return "1280x1280"


async def _zhipu_images_from_payload(
    client: httpx.AsyncClient,
    payload: dict[str, Any],
) -> list[str]:
    """Extract image data URLs from Zhipu API response.

    Zhipu returns images as temporary URLs that expire after 30 days.
    We download and re-encode as base64 data URLs.
    """
    images: list[str] = []
    for item in payload.get("data") or []:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if isinstance(url, str) and url:
            images.append(await _download_image_data_url(client, url))
    return images


# ---------------------------------------------------------------------------
# Provider registration
# ---------------------------------------------------------------------------

register_image_gen_provider(AIHubMixImageGenerationClient)
register_image_gen_provider(CodexImageGenerationClient)
register_image_gen_provider(CustomImageGenerationClient)
register_image_gen_provider(GeminiImageGenerationClient)
register_image_gen_provider(OllamaImageGenerationClient)
register_image_gen_provider(MiniMaxImageGenerationClient)
register_image_gen_provider(OpenAIImageGenerationClient)
register_image_gen_provider(OpenRouterImageGenerationClient)
register_image_gen_provider(StepFunImageGenerationClient)
register_image_gen_provider(ZhipuImageGenerationClient)
