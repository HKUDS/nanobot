"""Tests for LLMProvider._strip_image_content and _strip_image_content_inplace.

Regression test for #4345: image-strip fallback should not leak file paths
or produce text that makes the model hallucinate about unseen images.
"""

from __future__ import annotations

from nanobot.providers.base import LLMProvider

# ---------------------------------------------------------------------------
# _strip_image_content (returns new list)
# ---------------------------------------------------------------------------


class TestStripImageContent:
    """Tests for the non-mutating _strip_image_content method."""

    def test_replaces_image_url_with_nondescriptive_placeholder(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is this?"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,abc"},
                        "_meta": {"path": "/tmp/screenshot.png"},
                    },
                ],
            }
        ]
        result = LLMProvider._strip_image_content(messages)
        assert result is not None
        content = result[0]["content"]
        assert len(content) == 2
        assert content[0] == {"type": "text", "text": "What is this?"}
        assert content[1]["type"] == "text"
        placeholder = content[1]["text"]
        # Must NOT leak the file path
        assert "/tmp/screenshot.png" not in placeholder
        assert "screenshot" not in placeholder
        # Must clearly indicate the image was not delivered
        assert "not delivered" in placeholder.lower()

    def test_returns_none_when_no_images(self):
        messages = [
            {"role": "user", "content": [{"type": "text", "text": "hello"}]}
        ]
        assert LLMProvider._strip_image_content(messages) is None

    def test_handles_multiple_images(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Look at these:"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,abc"},
                        "_meta": {"path": "/a.png"},
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,def"},
                        "_meta": {"path": "/b.png"},
                    },
                ],
            }
        ]
        result = LLMProvider._strip_image_content(messages)
        assert result is not None
        content = result[0]["content"]
        # text + 2 placeholders
        assert len(content) == 3
        for block in content[1:]:
            assert block["type"] == "text"
            assert "/a.png" not in block["text"]
            assert "/b.png" not in block["text"]

    def test_handles_image_without_meta(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,abc"},
                    },
                ],
            }
        ]
        result = LLMProvider._strip_image_content(messages)
        assert result is not None
        placeholder = result[0]["content"][0]["text"]
        assert "not delivered" in placeholder.lower()

    def test_preserves_non_image_content(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Hello"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,abc"},
                        "_meta": {"path": "/x.png"},
                    },
                ],
            },
            {"role": "assistant", "content": "Hi there!"},
        ]
        result = LLMProvider._strip_image_content(messages)
        assert result is not None
        # system and assistant messages unchanged
        assert result[0]["content"] == "You are helpful."
        assert result[2]["content"] == "Hi there!"
        # user message has image replaced
        assert result[1]["content"][0]["type"] == "text"


# ---------------------------------------------------------------------------
# _strip_image_content_inplace (mutates in place)
# ---------------------------------------------------------------------------


class TestStripImageContentInplace:
    """Tests for the mutating _strip_image_content_inplace method."""

    def test_replaces_image_url_with_nondescriptive_placeholder(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is this?"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,abc"},
                        "_meta": {"path": "/tmp/photo.jpg"},
                    },
                ],
            }
        ]
        found = LLMProvider._strip_image_content_inplace(messages)
        assert found is True
        content = messages[0]["content"]
        assert len(content) == 2
        placeholder = content[1]["text"]
        assert "/tmp/photo.jpg" not in placeholder
        assert "not delivered" in placeholder.lower()

    def test_returns_false_when_no_images(self):
        messages = [
            {"role": "user", "content": [{"type": "text", "text": "hello"}]}
        ]
        assert LLMProvider._strip_image_content_inplace(messages) is False

    def test_mutates_original_messages(self):
        original_content = [
            {"type": "text", "text": "see this"},
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,abc"},
                "_meta": {"path": "/img.png"},
            },
        ]
        messages = [{"role": "user", "content": original_content}]
        LLMProvider._strip_image_content_inplace(messages)
        # The original list was mutated
        assert original_content[1]["type"] == "text"
        assert "/img.png" not in original_content[1]["text"]


# ---------------------------------------------------------------------------
# Opaque attachment handle marker (#4345): id present -> forwardable marker,
# id absent -> plain "omitted" placeholder. The path is never in either.
# ---------------------------------------------------------------------------


class TestStrippedImageHandleMarker:
    def test_marker_carries_id_when_meta_id_present(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,abc"},
                        "_meta": {"path": "/srv/uploads/a.png", "id": "attachment_1"},
                    },
                ],
            }
        ]
        result = LLMProvider._strip_image_content(messages)
        assert result is not None
        text = result[0]["content"][0]["text"]
        assert text == "[image attachment: attachment_1; cannot be viewed by this model]"
        assert "/srv/uploads/a.png" not in text  # still no raw path

    def test_marker_falls_back_to_placeholder_when_no_id(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,abc"},
                        "_meta": {"path": "/srv/uploads/a.png"},
                    },
                ],
            }
        ]
        result = LLMProvider._strip_image_content(messages)
        assert result is not None
        text = result[0]["content"][0]["text"]
        assert "not delivered" in text.lower()
        assert "attachment_" not in text

    def test_inplace_marker_carries_id_when_meta_id_present(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,abc"},
                        "_meta": {"path": "/srv/uploads/b.png", "id": "attachment_2"},
                    },
                ],
            }
        ]
        assert LLMProvider._strip_image_content_inplace(messages) is True
        text = messages[0]["content"][0]["text"]
        assert text == "[image attachment: attachment_2; cannot be viewed by this model]"
        assert "/srv/uploads/b.png" not in text
