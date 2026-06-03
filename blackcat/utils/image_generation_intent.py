"""Helpers for WebUI image-generation intent metadata."""

from __future__ import annotations

from typing import Any

IMAGE_GENERATION_METADATA_KEY = "image_generation"


def image_generation_prompt(content: str, metadata: dict[str, Any] | None) -> str:
    """Decorate a user prompt when WebUI image mode is enabled."""
    raw = (metadata or {}).get(IMAGE_GENERATION_METADATA_KEY)
    if not isinstance(raw, dict) or raw.get("enabled") is not True:
        return content

    aspect_ratio = raw.get("aspect_ratio")
    if isinstance(aspect_ratio, str) and aspect_ratio.strip():
        instruction = (
            "The user selected WebUI image generation mode. Use the generate_image tool. "
            f"When calling generate_image, pass aspect_ratio={aspect_ratio!r}."
        )
    else:
        instruction = (
            "The user selected WebUI image generation mode. Use the generate_image tool. "
            "Choose the most suitable aspect_ratio yourself from the prompt and intended use."
        )
    return f"{content}\n\n[WebUI image generation instruction: {instruction}]"
