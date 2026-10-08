"""Prepare inline image copies within a shared provider request byte budget."""

from __future__ import annotations

import asyncio
import base64
import io
from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass
from math import ceil
from typing import Any, cast

from loguru import logger
from PIL import Image, ImageOps

# A soft transport target, including base64 expansion, rather than an API size limit.
INLINE_IMAGE_BYTE_BUDGET = 1_000_000
_SMALL_IMAGE_BYTES = 64_000


@dataclass(frozen=True)
class _InlineImage:
    container: dict[str, Any]
    key: str
    detail: object

    @property
    def url(self) -> str:
        return cast(str, self.container[self.key])


def _inline_images(body: dict[str, Any]) -> Iterator[_InlineImage]:
    items = body.get("input", body.get("messages"))
    # Responses also accepts a plain-text input string.
    if not isinstance(items, list):
        return
    for item in cast(list[dict[str, Any]], items):
        content = item.get("output") if item.get("type") == "function_call_output" else item.get("content")
        if not isinstance(content, list):
            continue
        for block in cast(list[dict[str, Any]], content):
            container = block
            key = "image_url"
            if block.get("type") == "image_url" and isinstance(block.get("image_url"), dict):
                container = cast(dict[str, Any], block["image_url"])
                key = "url"
            elif block.get("type") != "input_image":
                continue
            url = container.get(key)
            if (
                isinstance(url, str)
                and url.startswith("data:image/") and ";base64," in url
            ):
                yield _InlineImage(container, key, container.get("detail"))


@dataclass
class _ImageCopy:
    target: _InlineImage
    source: Image.Image
    format: str
    original_bytes: int
    sent_bytes: int
    sent_size: tuple[int, int]

    def encode(self, quality: int, scale: float) -> None:
        if self.format == "PNG" and scale == 1 and quality != 85:
            return
        image = self.source
        if scale < 1 and self.target.detail != "original":
            image = image.resize(  # pyright: ignore[reportUnknownMemberType]
                (ceil(image.width * scale), ceil(image.height * scale)),
                Image.Resampling.LANCZOS,
            )
        output = io.BytesIO()
        image.save(output, format=self.format, quality=quality, optimize=True)
        raw = output.getvalue()
        if len(raw) < self.sent_bytes:
            self.sent_bytes = len(raw)
            self.sent_size = image.size
            mime = "image/png" if self.format == "PNG" else "image/jpeg"
            self.target.container[self.target.key] = f"data:{mime};base64,{base64.b64encode(raw).decode()}"


async def prepare_inline_images(body: dict[str, Any]) -> dict[str, Any]:
    """Keep small requests unchanged and prepare large image batches off the event loop."""
    total_bytes = sum(len(image.url) for image in _inline_images(body))
    if total_bytes <= INLINE_IMAGE_BYTE_BUDGET:
        return body
    return await asyncio.to_thread(_prepare_copies, body, total_bytes)


async def prepare_message_images(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prepare public image_url messages before provider-specific conversion."""
    prepared = await prepare_inline_images({"messages": messages})
    return cast(list[dict[str, Any]], prepared["messages"])


def _prepare_copies(body: dict[str, Any], total_bytes: int) -> dict[str, Any]:
    prepared = deepcopy(body)
    blocks = list(_inline_images(prepared))
    copies: list[_ImageCopy] = []
    try:
        for block in blocks:
            if len(block.url) <= _SMALL_IMAGE_BYTES:
                continue
            try:
                raw = base64.b64decode(block.url.split(";base64,", 1)[1], validate=True)
                with Image.open(io.BytesIO(raw)) as original:
                    if getattr(original, "is_animated", False) is True:
                        continue
                    original.load()
                    # Preserve PNG pixels and transparency instead of flattening them into JPEG.
                    format = "PNG" if (
                        original.format == "PNG" or "A" in original.getbands()
                        or "transparency" in original.info
                    ) else "JPEG"
                    source = ImageOps.exif_transpose(original)
                    if format == "JPEG" and source.mode != "RGB":
                        source = source.convert("RGB")
                    copies.append(_ImageCopy(block, source, format, len(raw), len(raw), source.size))
            except (ValueError, OSError, Image.DecompressionBombError) as exc:
                logger.info("Inline image preparation skipped: type={}", type(exc).__name__)

        # Re-encode at the original resolution first. Bound quality loss and any later scaling.
        copies.sort(key=lambda image: image.original_bytes, reverse=True)
        sent_bytes = total_bytes
        for quality, scale in ((85, 1.0), (75, 1.0), (65, 1.0), (65, 0.85), (65, 0.75)):
            for image in copies:
                before_bytes = len(image.target.url)
                image.encode(quality, scale)
                sent_bytes += len(image.target.url) - before_bytes
                if sent_bytes <= INLINE_IMAGE_BYTE_BUDGET:
                    break
            if sent_bytes <= INLINE_IMAGE_BYTE_BUDGET:
                break
        logger.info(
            "Inline images prepared: count={} encoded_bytes_before={} "
            "encoded_bytes_after={} budget={} budget_met={} images={}",
            len(blocks), total_bytes, sent_bytes, INLINE_IMAGE_BYTE_BUDGET,
            sent_bytes <= INLINE_IMAGE_BYTE_BUDGET,
            [{
                "before_size": image.source.size, "after_size": image.sent_size,
                "before_bytes": image.original_bytes, "after_bytes": image.sent_bytes,
            } for image in copies[:16]],
        )
        return prepared
    finally:
        for image in copies:
            image.source.close()
