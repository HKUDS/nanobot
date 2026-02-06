"""Tests for vision/multi-modal support in LiteLLMProvider."""

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.providers.litellm_provider import LiteLLMProvider


class TestVisionFormatSupport:
    """Test vision format conversion for different providers."""

    def setup_method(self):
        """Set up test fixtures."""
        self.provider = LiteLLMProvider(
            api_key="test-key",
            default_model="anthropic/claude-opus-4-5"
        )
        self.test_image_base64 = base64.b64encode(b"test_image_data").decode()
        self.test_image_data_url = f"data:image/jpeg;base64,{self.test_image_base64}"

    def test_has_image_content_with_text_only(self):
        """Test detection of text-only content."""
        assert not self.provider._has_image_content("Just text")

    def test_has_image_content_with_images(self):
        """Test detection of content with images."""
        content = [
            {"type": "text", "text": "What is this?"},
            {"type": "image_url", "image_url": {"url": self.test_image_data_url}}
        ]
        assert self.provider._has_image_content(content)

    def test_has_image_content_with_empty_list(self):
        """Test detection with empty list."""
        assert not self.provider._has_image_content([])

    def test_format_content_for_provider_text_only(self):
        """Test that text-only content is returned as-is."""
        content = "Just text message"
        result = self.provider._format_content_for_provider(content, "gpt-4")
        assert result == "Just text message"

    def test_format_for_claude_with_image(self):
        """Test Claude vision format conversion."""
        content = [
            {"type": "text", "text": "Describe this image"},
            {"type": "image_url", "image_url": {"url": self.test_image_data_url}}
        ]

        result = self.provider._format_for_claude(content)

        assert len(result) == 2
        # Order is preserved
        assert result[0]["type"] == "text"
        assert result[0]["text"] == "Describe this image"
        assert result[1]["type"] == "image"
        assert result[1]["source"]["type"] == "base64"
        assert result[1]["source"]["media_type"] == "image/jpeg"
        assert result[1]["source"]["data"] == self.test_image_base64

    def test_format_for_claude_with_invalid_data_url(self):
        """Test Claude format with invalid data URL."""
        content = [
            {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}}
        ]

        result = self.provider._format_for_claude(content)

        # Should return empty list for invalid URLs
        assert result == []

    def test_format_for_gemini_with_image(self):
        """Test Gemini vision format conversion."""
        content = [
            {"type": "text", "text": "What do you see?"},
            {"type": "image_url", "image_url": {"url": self.test_image_data_url}}
        ]

        result = self.provider._format_for_gemini(content)

        assert len(result) == 2
        # Order is preserved
        assert result[0]["text"] == "What do you see?"
        assert result[1]["inline_data"]["mime_type"] == "image/jpeg"
        assert result[1]["inline_data"]["data"] == self.test_image_base64

    def test_format_for_gemini_with_invalid_url(self):
        """Test Gemini format with invalid URL."""
        content = [
            {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}}
        ]

        result = self.provider._format_for_gemini(content)

        # Should return empty list for invalid URLs
        assert result == []

    def test_format_content_for_provider_openai(self):
        """Test that OpenAI format is preserved."""
        content = [
            {"type": "text", "text": "Analyze this"},
            {"type": "image_url", "image_url": {"url": self.test_image_data_url}}
        ]

        result = self.provider._format_content_for_provider(content, "gpt-4-vision")

        # OpenAI format should be returned as-is
        assert result == content

    def test_format_content_for_provider_claude(self):
        """Test routing to Claude formatter."""
        content = [
            {"type": "text", "text": "See this"},
            {"type": "image_url", "image_url": {"url": self.test_image_data_url}}
        ]

        result = self.provider._format_content_for_provider(content, "claude-opus-4-5")

        # Should be formatted for Claude
        assert len(result) == 2
        # Order preserved - text first
        assert result[0]["type"] == "text"
        assert result[1]["type"] == "image"

    def test_format_content_for_provider_gemini(self):
        """Test routing to Gemini formatter."""
        content = [
            {"type": "text", "text": "Look at this"},
            {"type": "image_url", "image_url": {"url": self.test_image_data_url}}
        ]

        result = self.provider._format_content_for_provider(content, "gemini-pro-vision")

        # Should be formatted for Gemini
        assert len(result) == 2
        # Order preserved
        assert result[0]["text"] == "Look at this"
        assert "inline_data" in result[1]

    def test_format_messages_for_provider(self):
        """Test formatting complete message list."""
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is this?"},
                    {"type": "image_url", "image_url": {"url": self.test_image_data_url}}
                ]
            }
        ]

        result = self.provider._format_messages_for_provider(messages, "claude-opus-4-5")

        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "You are a helpful assistant."
        assert result[1]["role"] == "user"
        # User content should be formatted for Claude
        assert len(result[1]["content"]) == 2

    def test_format_messages_preserves_tool_calls(self):
        """Test that tool calls are preserved during formatting."""
        messages = [
            {
                "role": "assistant",
                "content": "Let me check that for you.",
                "tool_calls": [
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {"name": "search", "arguments": "{}"}
                    }
                ]
            }
        ]

        result = self.provider._format_messages_for_provider(messages, "gpt-4")

        assert result[0]["role"] == "assistant"
        assert result[0]["content"] == "Let me check that for you."
        assert "tool_calls" in result[0]
        assert result[0]["tool_calls"][0]["id"] == "call_123"

    def test_format_messages_preserves_tool_role(self):
        """Test that tool role messages are preserved."""
        messages = [
            {
                "role": "tool",
                "tool_call_id": "call_123",
                "name": "search",
                "content": "Search results: ..."
            }
        ]

        result = self.provider._format_messages_for_provider(messages, "gpt-4")

        assert result[0]["role"] == "tool"
        assert result[0]["tool_call_id"] == "call_123"
        assert result[0]["name"] == "search"

    def test_multiple_images_format(self):
        """Test formatting multiple images for Claude."""
        img1 = f"data:image/jpeg;base64,{base64.b64encode(b'img1').decode()}"
        img2 = f"data:image/png;base64,{base64.b64encode(b'img2').decode()}"

        content = [
            {"type": "text", "text": "Compare these"},
            {"type": "image_url", "image_url": {"url": img1}},
            {"type": "image_url", "image_url": {"url": img2}}
        ]

        result = self.provider._format_for_claude(content)

        # Order is preserved
        assert len(result) == 3
        assert result[0]["type"] == "text"
        assert result[1]["type"] == "image"
        assert result[2]["type"] == "image"
        assert result[1]["source"]["media_type"] == "image/jpeg"
        assert result[2]["source"]["media_type"] == "image/png"

    def test_malformed_base64_url(self):
        """Test handling of malformed base64 URLs."""
        content = [
            {"type": "image_url", "image_url": {"url": "data:image,no-base64,here"}}
        ]

        result = self.provider._format_for_claude(content)

        # Should skip malformed entries
        assert result == []
