"""Tests for image token estimation in helpers."""

import base64
import json

from nanobot.utils.helpers import (
    _estimate_image_tokens,
    estimate_message_tokens,
    estimate_prompt_tokens,
)


class TestEstimateImageTokens:
    def test_data_url_proportional_to_size(self):
        """base64 data URL → tokens proportional to raw byte count."""
        raw = b"\x00" * 6000  # 6000 raw bytes
        b64 = base64.b64encode(raw).decode()
        part = {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
        tokens = _estimate_image_tokens(part)
        # raw_bytes=6000, 6000//6=1000, max(765,1000)=1000
        assert tokens == 1000

    def test_data_url_small_image_uses_floor(self):
        """Small images get at least 765 tokens."""
        raw = b"\x00" * 100
        b64 = base64.b64encode(raw).decode()
        part = {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
        tokens = _estimate_image_tokens(part)
        assert tokens == 765

    def test_external_url_returns_fallback(self):
        """External (non-data:) URL → 765 fallback."""
        part = {"type": "image_url", "image_url": {"url": "https://example.com/photo.jpg"}}
        tokens = _estimate_image_tokens(part)
        assert tokens == 765

    def test_missing_url_returns_fallback(self):
        """Malformed part with no url → 765 fallback."""
        part = {"type": "image_url", "image_url": {}}
        tokens = _estimate_image_tokens(part)
        assert tokens == 765


class TestEstimatePromptTokensWithImages:
    def test_image_messages_count_more_than_text_only(self):
        """Messages with image_url parts must estimate higher than text-only."""
        raw = b"\x00" * 6000
        b64 = base64.b64encode(raw).decode()

        text_msg = [{"role": "user", "content": [{"type": "text", "text": "describe"}]}]
        image_msg = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "describe"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }
        ]
        text_tokens = estimate_prompt_tokens(text_msg)
        image_tokens = estimate_prompt_tokens(image_msg)
        assert image_tokens > text_tokens


class TestEstimateMessageTokensWithImage:
    def test_single_message_with_image(self):
        """estimate_message_tokens must account for image_url parts."""
        raw = b"\x00" * 6000
        b64 = base64.b64encode(raw).decode()
        msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": "hello"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        }
        tokens = estimate_message_tokens(msg)
        # Must be at least 1000 (the image alone)
        assert tokens >= 1000
