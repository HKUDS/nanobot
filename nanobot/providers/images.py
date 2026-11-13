from __future__ import annotations

import asyncio
import base64
import io
from collections import Counter
from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from math import ceil
from typing import TYPE_CHECKING, Any, cast

from loguru import logger
from PIL import Image, ImageOps

if TYPE_CHECKING:
    from nanobot.providers.base import LLMResponse, ProviderConversationState

# A soft transport target, including base64 expansion, rather than an API size limit.
INLINE_IMAGE_BYTE_BUDGET = 1_000_000
_SMALL_IMAGE_BYTES = 64_000


def image_input_ids(value: object) -> tuple[str, ...]:
    """Identify actual image inputs, retaining their identity after transport preparation."""
    return tuple(image.input_id for image in _image_urls(value))


def state_image_input_ids(state: ProviderConversationState | None) -> tuple[str, ...]:
    if state is None:
        return ()
    return image_input_ids([state.payload, state.pending_messages])


def image_inputs_available(
    required: tuple[str, ...],
    messages: list[dict[str, Any]],
    state: ProviderConversationState | None = None,
) -> bool:
    """Require the complete image multiset in the input that will actually be sent."""
    available = state_image_input_ids(state) if state is not None else image_input_ids(messages)
    return not (Counter(required) - Counter(available))


@dataclass(frozen=True)
class _InlineImage:
    block: dict[str, Any]
    container: dict[str, Any]
    key: str
    detail: object

    @property
    def url(self) -> str:
        return cast(str, self.container[self.key])

    @property
    def input_id(self) -> str:
        meta = self.block.get("_meta")
        if isinstance(meta, dict):
            identifier = cast(dict[str, Any], meta).get("image_input_id")
            if isinstance(identifier, str) and identifier:
                return identifier
        return sha256(self.url.encode()).hexdigest()


def _image_urls(value: object) -> Iterator[_InlineImage]:
    if isinstance(value, dict):
        block = cast(dict[str, Any], value)
        container = block
        key = "image_url"
        if block.get("type") == "image_url" and isinstance(block.get("image_url"), dict):
            container = cast(dict[str, Any], block["image_url"])
            key = "url"
        if block.get("type") in ("image_url", "input_image") and isinstance(container.get(key), str):
            yield _InlineImage(block, container, key, container.get("detail"))
            return
        for child in block.values():
            yield from _image_urls(child)
    elif isinstance(value, (list, tuple)):
        for child in cast(list[object], value):
            yield from _image_urls(child)


def _inline_images(body: dict[str, Any]) -> Iterator[_InlineImage]:
    for image in _image_urls(body):
        if image.url.startswith("data:image/") and ";base64," in image.url:
            yield image


def preserve_image_input_ids(
    result: LLMResponse, source_body: dict[str, Any], sent_body: dict[str, Any],
) -> LLMResponse:
    """Keep only the sent pixels and a logical ID in newly returned private state."""
    states = [result.provider_state, result.provider_compaction_state]
    if not any(state is not None for state in states):
        return result
    sent_ids: dict[str, list[str]] = {}
    for source, sent in zip(_image_urls(source_body), _image_urls(sent_body), strict=True):
        sent_ids.setdefault(sent.url, []).append(source.input_id)
    if not sent_ids:
        return result
    for state in states:
        if state is None:
            continue
        remaining = {url: ids.copy() for url, ids in sent_ids.items()}
        # Compaction can prune a prefix; match repeated sent URLs from the end
        # so identical encodings retain the IDs of the surviving occurrences.
        for image in reversed(list(_image_urls([state.payload, state.pending_messages]))):
            identifiers = remaining.get(image.url)
            if identifiers:
                meta = image.block.get("_meta")
                metadata = dict(cast(dict[str, Any], meta)) if isinstance(meta, dict) else {}
                metadata["image_input_id"] = identifiers.pop()
                image.block["_meta"] = metadata
    return result


def _transport_copy(body: dict[str, Any]) -> dict[str, Any]:
    prepared = deepcopy(body)
    for image in _image_urls(prepared):
        image.block.pop("_meta", None)
    return prepared


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
    """Strip private image metadata and prepare large batches off the event loop."""
    total_bytes = sum(len(image.url) for image in _inline_images(body))
    if total_bytes > INLINE_IMAGE_BYTE_BUDGET:
        return await asyncio.to_thread(_prepare_copies, body, total_bytes)
    if any("_meta" in image.block for image in _image_urls(body)):
        return _transport_copy(body)
    return body


async def prepare_message_images(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prepare public image_url messages before provider-specific conversion."""
    prepared = await prepare_inline_images({"messages": messages})
    return cast(list[dict[str, Any]], prepared["messages"])


def _prepare_copies(body: dict[str, Any], total_bytes: int) -> dict[str, Any]:
    prepared = _transport_copy(body)
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
