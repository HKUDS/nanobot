"""Tests for Anthropic image format conversion in LiteLLMProvider."""

from __future__ import annotations

import pytest

from nanobot.providers.litellm_provider import LiteLLMProvider


# ---------------------------------------------------------------------------
# _convert_images_for_anthropic
# ---------------------------------------------------------------------------

def _jpeg_data_uri(data: str = "abc123") -> str:
    return f"data:image/jpeg;base64,{data}"


def _png_data_uri(data: str = "xyz789") -> str:
    return f"data:image/png;base64,{data}"


def test_converts_jpeg_data_uri_to_anthropic_format():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": _jpeg_data_uri("FAKEDATA")}},
                {"type": "text", "text": "What is in this image?"},
            ],
        }
    ]
    result = LiteLLMProvider._convert_images_for_anthropic(messages)
    assert len(result) == 1
    content = result[0]["content"]
    assert content[0] == {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": "FAKEDATA",
        },
    }
    assert content[1] == {"type": "text", "text": "What is in this image?"}


def test_converts_png_data_uri_to_anthropic_format():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": _png_data_uri("PNGDATA")}},
            ],
        }
    ]
    result = LiteLLMProvider._convert_images_for_anthropic(messages)
    img = result[0]["content"][0]
    assert img["source"]["media_type"] == "image/png"
    assert img["source"]["data"] == "PNGDATA"


def test_leaves_http_image_url_unchanged():
    """HTTP URLs should pass through unchanged so litellm handles them."""
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "https://example.com/photo.jpg"}},
            ],
        }
    ]
    result = LiteLLMProvider._convert_images_for_anthropic(messages)
    assert result[0]["content"][0] == {
        "type": "image_url",
        "image_url": {"url": "https://example.com/photo.jpg"},
    }


def test_leaves_string_content_messages_unchanged():
    messages = [{"role": "user", "content": "Hello"}]
    result = LiteLLMProvider._convert_images_for_anthropic(messages)
    assert result == messages


def test_leaves_non_image_blocks_unchanged():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "No images here"},
            ],
        }
    ]
    result = LiteLLMProvider._convert_images_for_anthropic(messages)
    assert result[0]["content"] == [{"type": "text", "text": "No images here"}]


def test_handles_multiple_images_in_one_message():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": _jpeg_data_uri("DATA1")}},
                {"type": "image_url", "image_url": {"url": _png_data_uri("DATA2")}},
                {"type": "text", "text": "Compare them"},
            ],
        }
    ]
    result = LiteLLMProvider._convert_images_for_anthropic(messages)
    content = result[0]["content"]
    assert content[0]["source"]["data"] == "DATA1"
    assert content[1]["source"]["data"] == "DATA2"
    assert content[2]["type"] == "text"


def test_does_not_mutate_original_messages():
    original_block = {"type": "image_url", "image_url": {"url": _jpeg_data_uri("DATA")}}
    messages = [{"role": "user", "content": [original_block]}]
    LiteLLMProvider._convert_images_for_anthropic(messages)
    # Original block untouched
    assert messages[0]["content"][0]["type"] == "image_url"


# ---------------------------------------------------------------------------
# _is_anthropic_model
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("original,resolved,expected", [
    ("claude-sonnet-4-5", "anthropic/claude-sonnet-4-5", True),
    ("anthropic/claude-opus-4-5", "anthropic/claude-opus-4-5", True),
    ("gpt-4o", "openai/gpt-4o", False),
    ("gemini/gemini-pro", "gemini/gemini-pro", False),
])
def test_is_anthropic_model(original, resolved, expected):
    assert LiteLLMProvider._is_anthropic_model(original, resolved) == expected
