"""Text views of session messages. None of these projections resolves attachments."""

from collections.abc import Mapping, Sequence
from typing import cast

from nanobot.utils.helpers import stringify_text_blocks

IMAGE_ATTACHMENT_TYPE = "image_attachment"


def text_history_blocks(blocks: Sequence[object]) -> list[object]:
    """Keep block order and replace each inline or stored image with a text marker."""
    return [
        {"type": "text", "text": "[image]"}
        if isinstance(block, dict) and cast(dict[str, object], block).get("type") in (
            IMAGE_ATTACHMENT_TYPE, "image_url",
        ) else block
        for block in blocks
    ]


def message_text(content: object) -> str:
    """Visible text only; an image is not part of its caption."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for value in cast(list[object], content):
        if isinstance(value, dict):
            block = cast(dict[str, object], value)
            if block.get("type") == "text" and isinstance(text := block.get("text"), str):
                parts.append(text)
    return "\n".join(parts)


def history_message_text(message: Mapping[str, object]) -> str:
    """Text for an archive line, including markers for image-only user turns."""
    content = message.get("content")
    if message.get("role") == "user" and isinstance(content, list):
        blocks = text_history_blocks(cast(list[object], content))
        text = stringify_text_blocks(blocks)
        return str(blocks) if text is None else text
    return str(content) if content else ""
