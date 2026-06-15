"""Provider wrapper that replaces image_url blocks with text descriptions.

Applied automatically around text-only providers (e.g. DeepSeek) so that
the rest of the stack — context building, tool results, session history —
continues to produce multimodal content blocks without any changes, and the
wrapped provider receives clean text-only messages.

Covers all image entry points:
  - User messages with attached media (context._build_user_content)
  - read_file tool results for image files (filesystem.read_file)
  - Any future tool that returns image_url blocks
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from nanobot.providers.base import LLMProvider, LLMResponse


def _extract_image_sources(content: Any) -> list[str]:
    """Return data-URLs from image_url blocks in a message content value."""
    if not isinstance(content, list):
        return []
    sources = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "image_url":
            url = (block.get("image_url") or {}).get("url", "")
            if url:
                sources.append(url)
    return sources


def _replace_images_in_content(content: Any, description: str) -> Any:
    """Strip image_url blocks from *content*, inject description as text."""
    if not isinstance(content, list):
        return content
    cleaned = [
        block for block in content
        if not (isinstance(block, dict) and block.get("type") == "image_url")
    ]
    if description:
        cleaned.append({"type": "text", "text": f"[Immagine: {description}]"})
    # If the result is a single plain-text block, unwrap to a string.
    if len(cleaned) == 1 and isinstance(cleaned[0], dict) and cleaned[0].get("type") == "text":
        return cleaned[0]["text"]
    return cleaned or ""


async def _replace_all_images(
    messages: list[dict[str, Any]],
    describe: Any,  # Callable[[list[str]], Awaitable[str]]
) -> list[dict[str, Any]]:
    """Walk all messages and tool results, replace image blocks with descriptions."""
    result = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content")

        # Standard user/assistant message content
        sources = _extract_image_sources(content)
        if sources:
            description = await describe(sources)
            msg = {**msg, "content": _replace_images_in_content(content, description)}

        # Tool result messages: content is a list of tool results, each with their own content
        if role == "tool" and isinstance(content, list):
            new_content = []
            for item in content:
                if not isinstance(item, dict):
                    new_content.append(item)
                    continue
                item_content = item.get("content")
                item_sources = _extract_image_sources(item_content)
                if item_sources:
                    description = await describe(item_sources)
                    item = {**item, "content": _replace_images_in_content(item_content, description)}
                new_content.append(item)
            msg = {**msg, "content": new_content}

        result.append(msg)
    return result


class VisionAugmentedProvider(LLMProvider):
    """Wrap a text-only LLM provider, converting images to text descriptions before each call."""

    def __init__(self, primary: LLMProvider) -> None:
        self._primary = primary

    # ------------------------------------------------------------------ #
    # Proxy all provider properties/methods to primary                    #
    # ------------------------------------------------------------------ #

    @property
    def generation(self):
        return self._primary.generation

    @generation.setter
    def generation(self, value):
        self._primary.generation = value

    def get_default_model(self) -> str:
        return self._primary.get_default_model()

    @property
    def supports_progress_deltas(self) -> bool:
        return bool(getattr(self._primary, "supports_progress_deltas", False))

    # ------------------------------------------------------------------ #
    # Vision replacement                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    async def _describe(sources: list[str]) -> str:
        from nanobot.providers.vision_chain import describe_images
        return await describe_images(sources)

    async def _augment_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        messages = kwargs.get("messages")
        if not messages:
            return kwargs
        # Quick check: any image blocks at all?
        has_images = any(
            _extract_image_sources(m.get("content"))
            or (
                m.get("role") == "tool"
                and isinstance(m.get("content"), list)
                and any(_extract_image_sources(i.get("content")) for i in m["content"] if isinstance(i, dict))
            )
            for m in messages
        )
        if not has_images:
            return kwargs
        new_messages = await _replace_all_images(messages, self._describe)
        return {**kwargs, "messages": new_messages}

    # ------------------------------------------------------------------ #
    # chat / chat_stream                                                   #
    # ------------------------------------------------------------------ #

    async def chat(self, **kwargs: Any) -> LLMResponse:
        kwargs = await self._augment_kwargs(kwargs)
        return await self._primary.chat(**kwargs)

    async def chat_stream(self, **kwargs: Any) -> LLMResponse:
        kwargs = await self._augment_kwargs(kwargs)
        return await self._primary.chat_stream(**kwargs)
