"""Historical image annotations and the input a text-only candidate can accept."""

from typing import Any, cast

REPLAYED_IMAGE_META = "replayed_user_image"


def replace_replayed_images(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Omit only historical user images for a text-only provider candidate."""
    projected: list[dict[str, Any]] = []
    for message in messages:
        content = message.get("content")
        if message.get("role") == "user" and isinstance(content, list):
            blocks = cast(list[object], content)
            # Fresh and replayed images can share one merged user row.
            updated = [_replace_replayed_image(block) for block in blocks]
            if any(before is not after for before, after in zip(blocks, updated, strict=True)):
                message = {**message, "content": updated}
        projected.append(message)
    return projected


def _replace_replayed_image(value: object) -> object:
    if not isinstance(value, dict):
        return value
    block = cast(dict[str, object], value)
    meta = block.get("_meta")
    if (
        block.get("type") == "image_url"
        and isinstance(meta, dict)
        and cast(dict[str, object], meta).get(REPLAYED_IMAGE_META) is True
    ):
        return {"type": "text", "text": "[Previous image omitted: model does not support images]"}
    return block
