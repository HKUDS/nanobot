"""Tests for channel utilities (split_message, markdown conversion, etc.)."""

from blackcat.channels.utils import (
    format_reply_context,
    get_file_extension,
    markdown_to_telegram_html,
    split_message,
)

# ── split_message ──────────────────────────────────────────────────


def test_split_message_short():
    """Short messages should not be split."""
    result = split_message("hello", 100)
    assert result == ["hello"]


def test_split_message_exact_limit():
    text = "a" * 100
    result = split_message(text, 100)
    assert result == [text]


def test_split_message_splits_on_newline():
    text = "line one\nline two\nline three"
    result = split_message(text, 15)
    assert len(result) >= 2
    assert result[0] == "line one"


def test_split_message_splits_on_space():
    text = "word " * 20  # 100 chars
    result = split_message(text.strip(), 30)
    assert len(result) >= 2
    # Each chunk should be <= 30 chars
    for chunk in result:
        assert len(chunk) <= 30


def test_split_message_hard_split():
    """When no newline or space, hard-split at the limit."""
    text = "a" * 200
    result = split_message(text, 50)
    assert len(result) == 4
    assert result[0] == "a" * 50


def test_split_message_empty():
    result = split_message("", 100)
    assert result == [""]


def test_split_message_telegram_limit():
    """Simulate a long message against Telegram's 4096 limit."""
    text = "paragraph\n" * 500  # ~5000 chars
    result = split_message(text, 4096)
    for chunk in result:
        assert len(chunk) <= 4096


def test_split_message_discord_limit():
    """Simulate against Discord's 2000 limit."""
    text = "some text with words " * 120  # ~2520 chars
    result = split_message(text.strip(), 2000)
    for chunk in result:
        assert len(chunk) <= 2000


# ── markdown_to_telegram_html ──────────────────────────────────────


def test_markdown_to_html_bold():
    assert "<b>bold</b>" in markdown_to_telegram_html("**bold**")


def test_markdown_to_html_italic():
    assert "<i>italic</i>" in markdown_to_telegram_html("_italic_")


def test_markdown_to_html_strikethrough():
    assert "<s>deleted</s>" in markdown_to_telegram_html("~~deleted~~")


def test_markdown_to_html_code_block():
    result = markdown_to_telegram_html("```python\nprint('hi')\n```")
    assert "<pre><code>" in result
    assert "print" in result


def test_markdown_to_html_inline_code():
    result = markdown_to_telegram_html("use `git status`")
    assert "<code>git status</code>" in result


def test_markdown_to_html_link():
    result = markdown_to_telegram_html("[click](https://example.com)")
    assert '<a href="https://example.com">click</a>' in result


def test_markdown_to_html_header_stripped():
    result = markdown_to_telegram_html("# Header Text")
    assert "#" not in result
    assert "Header Text" in result


def test_markdown_to_html_escapes_html():
    result = markdown_to_telegram_html("1 < 2 & 3 > 0")
    assert "&lt;" in result
    assert "&amp;" in result
    assert "&gt;" in result


def test_markdown_to_html_bullet_list():
    result = markdown_to_telegram_html("- item one\n- item two")
    assert result.count("\u2022") == 2  # bullet character


def test_markdown_to_html_empty():
    assert markdown_to_telegram_html("") == ""


def test_markdown_to_html_code_preserves_special_chars():
    """Code blocks should escape HTML but not apply formatting."""
    result = markdown_to_telegram_html("```\n<div>**bold**</div>\n```")
    assert "<b>" not in result  # Bold should NOT be applied inside code
    assert "&lt;div&gt;" in result


# ── get_file_extension ─────────────────────────────────────────────


def test_get_extension_by_mime():
    assert get_file_extension("image", "image/png") == ".png"
    assert get_file_extension("audio", "audio/ogg") == ".ogg"
    assert get_file_extension("video", "video/mp4") == ".mp4"


def test_get_extension_by_media_type():
    assert get_file_extension("image") == ".jpg"
    assert get_file_extension("voice") == ".ogg"
    assert get_file_extension("audio") == ".mp3"


def test_get_extension_unknown():
    assert get_file_extension("unknown") == ""


def test_get_extension_mime_overrides_media_type():
    """MIME type should take priority over media type."""
    assert get_file_extension("image", "image/webp") == ".webp"


# ── format_reply_context ──────────────────────────────────────────


def test_format_reply_context_basic():
    result = format_reply_context("Alice", "hello there")
    assert result == "[replying to Alice: hello there]"


def test_format_reply_context_truncates():
    long_text = "a" * 300
    result = format_reply_context("Bob", long_text)
    assert result is not None
    assert len(result) < 300
    assert result.endswith("...]")


def test_format_reply_context_none_author():
    result = format_reply_context(None, "message")
    assert "someone" in result


def test_format_reply_context_empty_content():
    assert format_reply_context("Alice", "") is None
    assert format_reply_context("Alice", "   ") is None


def test_format_reply_context_none_content():
    assert format_reply_context("Alice", None) is None
