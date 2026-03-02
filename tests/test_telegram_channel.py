"""Tests for Telegram channel static methods."""

import pytest

from nanobot.channels.telegram import (
    TelegramChannel,
    _markdown_to_telegram_html,
    _split_message,
)


# Helper to create channel instance for instance methods
def _make_channel():
    from nanobot.config.schema import TelegramConfig
    from nanobot.bus.queue import MessageBus
    cfg = TelegramConfig(enabled=True)
    return TelegramChannel(cfg, MessageBus())


class TestGetMediaType:
    """Test TelegramChannel._get_media_type() static method."""

    def test_image_extensions(self):
        assert TelegramChannel._get_media_type("photo.jpg") == "photo"
        assert TelegramChannel._get_media_type("photo.jpeg") == "photo"
        assert TelegramChannel._get_media_type("photo.png") == "photo"
        assert TelegramChannel._get_media_type("photo.gif") == "photo"
        assert TelegramChannel._get_media_type("photo.webp") == "photo"

    def test_voice_extension(self):
        assert TelegramChannel._get_media_type("voice.ogg") == "voice"

    def test_audio_extensions(self):
        assert TelegramChannel._get_media_type("audio.mp3") == "audio"
        assert TelegramChannel._get_media_type("audio.m4a") == "audio"
        assert TelegramChannel._get_media_type("audio.wav") == "audio"
        assert TelegramChannel._get_media_type("audio.aac") == "audio"

    def test_document_extension(self):
        assert TelegramChannel._get_media_type("doc.pdf") == "document"
        assert TelegramChannel._get_media_type("file.txt") == "document"

    def test_no_extension(self):
        assert TelegramChannel._get_media_type("filename") == "document"


class TestGetExtension:
    """Test TelegramChannel._get_extension() instance method."""

    def test_image_mime_types(self):
        channel = _make_channel()
        assert channel._get_extension("image", "image/jpeg") == ".jpg"
        assert channel._get_extension("image", "image/png") == ".png"
        assert channel._get_extension("image", "image/gif") == ".gif"

    def test_audio_mime_types(self):
        channel = _make_channel()
        assert channel._get_extension("voice", "audio/ogg") == ".ogg"
        assert channel._get_extension("audio", "audio/mpeg") == ".mp3"
        assert channel._get_extension("audio", "audio/mp4") == ".m4a"

    def test_unknown_mime_type_falls_back_to_type(self):
        channel = _make_channel()
        # Unknown mime type falls back to media type default
        assert channel._get_extension("image", "image/webp") == ".jpg"
        assert channel._get_extension("file", None) == ""

    def test_media_type_fallback(self):
        channel = _make_channel()
        assert channel._get_extension("image", None) == ".jpg"
        assert channel._get_extension("voice", None) == ".ogg"
        assert channel._get_extension("audio", None) == ".mp3"


class TestSplitMessage:
    """Test _split_message() function."""

    def test_short_message_no_split(self):
        result = _split_message("hello world", max_len=100)
        assert result == ["hello world"]

    def test_split_at_newline(self):
        result = _split_message("line1\nline2\nline3", max_len=6)
        assert result == ["line1", "line2", "line3"]

    def test_split_at_space(self):
        result = _split_message("hello world foo", max_len=8)
        # Splits at space, keeps remainder
        assert "hello" in result
        assert "world" in result

    def test_split_preserves_long_word(self):
        # When no space/newline, split at max_len
        result = _split_message("verylongword123", max_len=10)
        assert result == ["verylongwo", "rd123"]

    def test_multiple_chunks(self):
        content = "a" * 2000 + "\n" + "b" * 2000
        result = _split_message(content, max_len=1000)
        # Should have multiple chunks
        assert len(result) > 1


class TestMarkdownToTelegramHtml:
    """Test _markdown_to_telegram_html() function."""

    def test_empty_string(self):
        assert _markdown_to_telegram_html("") == ""

    def test_none_input(self):
        assert _markdown_to_telegram_html(None) == ""

    def test_bold(self):
        assert _markdown_to_telegram_html("**bold**") == "<b>bold</b>"
        assert _markdown_to_telegram_html("__bold__") == "<b>bold</b>"

    def test_italic(self):
        assert _markdown_to_telegram_html("_italic_") == "<i>italic</i>"

    def test_italic_underscore_in_word(self):
        # _ in variable names should not be italic
        result = _markdown_to_telegram_html("var_name")
        assert "<i>" not in result

    def test_strikethrough(self):
        assert _markdown_to_telegram_html("~~deleted~~") == "<s>deleted</s>"

    def test_link(self):
        assert _markdown_to_telegram_html("[text](http://example.com)") == '<a href="http://example.com">text</a>'

    def test_bullet_list(self):
        assert _markdown_to_telegram_html("- item1\n- item2") == "• item1\n• item2"

    def test_code_block(self):
        result = _markdown_to_telegram_html("```python\nprint('hello')\n```")
        assert "<pre><code>" in result
        assert "print('hello')" in result

    def test_inline_code(self):
        result = _markdown_to_telegram_html("Use `const x = 1`")
        assert "<code>const x = 1</code>" in result

    def test_header(self):
        assert _markdown_to_telegram_html("# Title") == "Title"
        assert _markdown_to_telegram_html("## Subtitle") == "Subtitle"

    def test_blockquote(self):
        assert _markdown_to_telegram_html("> quoted text") == "quoted text"

    def test_html_escaping(self):
        result = _markdown_to_telegram_html("<script>alert('xss')</script>")
        assert "&lt;script&gt;" in result

    def test_complex_markdown(self):
        markdown = "**Bold** and _italic_ with [link](http://example.com)"
        result = _markdown_to_telegram_html(markdown)
        assert "<b>Bold</b>" in result
        assert "<i>italic</i>" in result
        assert '<a href="http://example.com">link</a>' in result
