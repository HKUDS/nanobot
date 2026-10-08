"""Prepare inline image copies within a shared Responses request byte budget."""

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


def _inline_images(body: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for item in cast(list[dict[str, Any]], body["input"]):
        content = item.get("output") if item.get("type") == "function_call_output" else item.get("content")
        if not isinstance(content, list):
            continue
        for block in cast(list[dict[str, Any]], content):
            url = block.get("image_url")
            if (
                block.get("type") == "input_image" and isinstance(url, str)
                and url.startswith("data:image/") and ";base64," in url
            ):
                yield block


@dataclass
class _ImageCopy:
    block: dict[str, Any]
    source: Image.Image
    format: str
    original_bytes: int
    sent_bytes: int
    sent_size: tuple[int, int]

    def encode(self, quality: int, scale: float) -> None:
        if self.format == "PNG" and scale == 1 and quality != 85:
            return
        image = self.source
        if scale < 1 and self.block.get("detail") != "original":
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
            self.block["image_url"] = f"data:{mime};base64,{base64.b64encode(raw).decode()}"


async def prepare_inline_images(body: dict[str, Any]) -> dict[str, Any]:
    """Keep small requests unchanged and prepare large image batches off the event loop."""
    total_bytes = sum(len(block["image_url"]) for block in _inline_images(body))
    if total_bytes <= INLINE_IMAGE_BYTE_BUDGET:
        return body
    return await asyncio.to_thread(_prepare_copies, body, total_bytes)


def _prepare_copies(body: dict[str, Any], total_bytes: int) -> dict[str, Any]:
    prepared = deepcopy(body)
    blocks = list(_inline_images(prepared))
    copies: list[_ImageCopy] = []
    try:
        for block in blocks:
            if len(block["image_url"]) <= _SMALL_IMAGE_BYTES:
                continue
            try:
                raw = base64.b64decode(block["image_url"].split(";base64,", 1)[1], validate=True)
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
                before_bytes = len(image.block["image_url"])
                image.encode(quality, scale)
                sent_bytes += len(image.block["image_url"]) - before_bytes
                if sent_bytes <= INLINE_IMAGE_BYTE_BUDGET:
                    break
            if sent_bytes <= INLINE_IMAGE_BYTE_BUDGET:
                break
        logger.info(
            "Codex inline images prepared: count={} encoded_bytes_before={} "
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
