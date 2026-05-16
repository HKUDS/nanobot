"""Unit tests for the Signal markdown → plain text + textStyle converter."""

from nanobot.channels.signal import _markdown_to_signal


def _utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def styles_for(plain: str, text_styles: list[str]) -> dict[str, list[str]]:
    """Return a dict mapping each styled substring to its style list."""
    result: dict[str, list[str]] = {}
    for entry in text_styles:
        start_s, length_s, style = entry.split(":", 2)
        start, length = int(start_s), int(length_s)
        span = plain[start : start + length]
        result.setdefault(span, []).append(style)
    return result


def utf16_styles_for(plain: str, text_styles: list[str]) -> dict[str, list[str]]:
    """Like styles_for, but slices `plain` using UTF-16 offsets (Signal's units)."""
    encoded = plain.encode("utf-16-le")
    result: dict[str, list[str]] = {}
    for entry in text_styles:
        start_s, length_s, style = entry.split(":", 2)
        start, length = int(start_s), int(length_s)
        span = encoded[start * 2 : (start + length) * 2].decode("utf-16-le")
        result.setdefault(span, []).append(style)
    return result


# ---------------------------------------------------------------------------
# Basic cases
# ---------------------------------------------------------------------------


def test_empty():
    plain, styles = _markdown_to_signal("")
    assert plain == ""
    assert styles == []


def test_plain_text():
    plain, styles = _markdown_to_signal("hello world")
    assert plain == "hello world"
    assert styles == []


def test_bold_stars():
    plain, styles = _markdown_to_signal("say **hello** now")
    assert plain == "say hello now"
    assert styles_for(plain, styles) == {"hello": ["BOLD"]}


def test_bold_underscores():
    plain, styles = _markdown_to_signal("say __hello__ now")
    assert plain == "say hello now"
    assert styles_for(plain, styles) == {"hello": ["BOLD"]}


def test_italic_star():
    plain, styles = _markdown_to_signal("say *hello* now")
    assert plain == "say hello now"
    assert styles_for(plain, styles) == {"hello": ["ITALIC"]}


def test_italic_underscore():
    plain, styles = _markdown_to_signal("say _hello_ now")
    assert plain == "say hello now"
    assert styles_for(plain, styles) == {"hello": ["ITALIC"]}


def test_strikethrough():
    plain, styles = _markdown_to_signal("say ~~hello~~ now")
    assert plain == "say hello now"
    assert styles_for(plain, styles) == {"hello": ["STRIKETHROUGH"]}


# ---------------------------------------------------------------------------
# Code
# ---------------------------------------------------------------------------


def test_inline_code():
    plain, styles = _markdown_to_signal("run `ls -la` here")
    assert plain == "run ls -la here"
    assert styles_for(plain, styles) == {"ls -la": ["MONOSPACE"]}


def test_code_block():
    plain, styles = _markdown_to_signal("```\nprint('hi')\n```")
    assert "print('hi')" in plain
    assert styles_for(plain, styles).get("print('hi')\n") == ["MONOSPACE"] or \
           "MONOSPACE" in str(styles_for(plain, styles))


def test_code_block_with_lang():
    plain, styles = _markdown_to_signal("```python\ncode\n```")
    assert "code" in plain
    assert any("MONOSPACE" in s for s in styles)


def test_code_block_not_processed_further():
    """Markdown inside a code block must not be styled."""
    plain, styles = _markdown_to_signal("```\n**not bold**\n```")
    assert "**not bold**" in plain
    # Only MONOSPACE should be applied, no BOLD
    for entry in styles:
        assert "BOLD" not in entry


def test_inline_code_not_processed_further():
    """Markdown inside inline code must not be styled."""
    plain, styles = _markdown_to_signal("use `**raw**` please")
    assert "**raw**" in plain
    for entry in styles:
        assert "BOLD" not in entry


# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------


def test_header_becomes_bold():
    plain, styles = _markdown_to_signal("# My Title")
    assert plain == "My Title"
    assert styles_for(plain, styles) == {"My Title": ["BOLD"]}


def test_h2_becomes_bold():
    plain, styles = _markdown_to_signal("## Sub-section")
    assert plain == "Sub-section"
    assert styles_for(plain, styles) == {"Sub-section": ["BOLD"]}


# ---------------------------------------------------------------------------
# Blockquotes
# ---------------------------------------------------------------------------


def test_blockquote_strips_marker():
    plain, styles = _markdown_to_signal("> some quote")
    assert plain == "some quote"
    assert styles == []


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------


def test_bullet_dash():
    plain, styles = _markdown_to_signal("- item one")
    assert plain == "• item one"


def test_bullet_star():
    plain, styles = _markdown_to_signal("* item two")
    assert plain == "• item two"


def test_numbered_list():
    plain, styles = _markdown_to_signal("1. first\n2. second")
    assert "1. first" in plain
    assert "2. second" in plain


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------


def test_link_text_differs_from_url():
    plain, styles = _markdown_to_signal("[Click here](https://example.com)")
    assert plain == "Click here (https://example.com)"
    assert styles == []


def test_link_text_equals_url():
    plain, styles = _markdown_to_signal("[https://example.com](https://example.com)")
    assert plain == "https://example.com"
    assert styles == []


def test_link_text_equals_url_without_scheme():
    plain, styles = _markdown_to_signal("[example.com](https://example.com)")
    assert plain == "https://example.com"


# ---------------------------------------------------------------------------
# Mixed / nesting
# ---------------------------------------------------------------------------


def test_bold_and_italic_adjacent():
    plain, styles = _markdown_to_signal("**bold** and *italic*")
    assert plain == "bold and italic"
    sd = styles_for(plain, styles)
    assert sd.get("bold") == ["BOLD"]
    assert sd.get("italic") == ["ITALIC"]


def test_header_with_inline_code():
    """Header becomes BOLD; code inside becomes MONOSPACE (not double-BOLD)."""
    plain, styles = _markdown_to_signal("# Use `grep`")
    assert plain == "Use grep"
    sd = styles_for(plain, styles)
    assert "BOLD" in sd.get("Use ", []) or "BOLD" in str(styles)
    assert "MONOSPACE" in sd.get("grep", [])


def test_multiline_mixed():
    md = "**Title**\n\nSome *italic* text.\n\n- bullet\n- another"
    plain, styles = _markdown_to_signal(md)
    assert "Title" in plain
    assert "italic" in plain
    assert "• bullet" in plain
    sd = styles_for(plain, styles)
    assert "BOLD" in sd.get("Title", [])
    assert "ITALIC" in sd.get("italic", [])


# ---------------------------------------------------------------------------
# Table rendering
# ---------------------------------------------------------------------------


def test_table_rendered_as_monospace():
    md = "| A | B |\n| - | - |\n| 1 | 2 |"
    plain, styles = _markdown_to_signal(md)
    assert "A" in plain and "B" in plain
    assert any("MONOSPACE" in s for s in styles)


# ---------------------------------------------------------------------------
# Style range format
# ---------------------------------------------------------------------------


def test_style_range_format():
    """Each style entry must be 'start:length:STYLE'."""
    _, styles = _markdown_to_signal("**bold** text")
    for entry in styles:
        parts = entry.split(":")
        assert len(parts) == 3
        assert parts[0].isdigit()
        assert parts[1].isdigit()
        assert parts[2] in {"BOLD", "ITALIC", "STRIKETHROUGH", "MONOSPACE", "SPOILER"}


def test_style_ranges_are_within_bounds():
    text = "hello **world** end"
    plain, styles = _markdown_to_signal(text)
    for entry in styles:
        start_s, length_s, _ = entry.split(":", 2)
        start, length = int(start_s), int(length_s)
        assert start >= 0
        assert start + length <= len(plain)


# ---------------------------------------------------------------------------
# Non-BMP / UTF-16 offsets
#
# Signal's BodyRange (and signal-cli's textStyle) interprets start/length in
# UTF-16 code units. Python's len() counts code points, so characters outside
# the BMP (emojis, supplementary CJK) shift offsets by +1 per occurrence.
# ---------------------------------------------------------------------------


def assert_within_utf16_bounds(plain: str, styles: list[str]) -> None:
    limit = _utf16_len(plain)
    for entry in styles:
        start_s, length_s, _ = entry.split(":", 2)
        start, length = int(start_s), int(length_s)
        assert start >= 0
        assert start + length <= limit, (
            f"range {entry} exceeds utf-16 length {limit} of {plain!r}"
        )


def test_bold_with_emoji_inside():
    plain, styles = _markdown_to_signal("**hi 🎉 bye**")
    assert plain == "hi 🎉 bye"
    assert utf16_styles_for(plain, styles) == {"hi 🎉 bye": ["BOLD"]}
    assert_within_utf16_bounds(plain, styles)


def test_italic_with_trailing_emoji():
    plain, styles = _markdown_to_signal("*bye 🎉*")
    assert plain == "bye 🎉"
    assert utf16_styles_for(plain, styles) == {"bye 🎉": ["ITALIC"]}
    assert_within_utf16_bounds(plain, styles)


def test_bold_after_emoji_prefix():
    plain, styles = _markdown_to_signal("🎉 **bold**")
    assert plain == "🎉 bold"
    assert utf16_styles_for(plain, styles) == {"bold": ["BOLD"]}
    assert_within_utf16_bounds(plain, styles)


def test_bold_after_and_inside_emoji():
    plain, styles = _markdown_to_signal("🎉 **a 🎊 b**")
    assert plain == "🎉 a 🎊 b"
    assert utf16_styles_for(plain, styles) == {"a 🎊 b": ["BOLD"]}
    assert_within_utf16_bounds(plain, styles)


def test_supplementary_cjk_in_bold():
    """Non-BMP CJK (U+20BB7) proves the bug is UTF-16, not emoji-specific."""
    plain, styles = _markdown_to_signal("**𠮷野家**")
    assert plain == "𠮷野家"
    assert utf16_styles_for(plain, styles) == {"𠮷野家": ["BOLD"]}
    assert_within_utf16_bounds(plain, styles)


def test_zwj_emoji_in_bold():
    """ZWJ family sequence = multiple surrogate pairs + BMP ZWJs."""
    plain, styles = _markdown_to_signal("**hi 👨‍👩‍👧 bye**")
    assert plain == "hi 👨‍👩‍👧 bye"
    assert utf16_styles_for(plain, styles) == {"hi 👨‍👩‍👧 bye": ["BOLD"]}
    assert_within_utf16_bounds(plain, styles)


def test_ascii_offsets_unchanged():
    """ASCII-only path must produce the same offsets as before the UTF-16 fix."""
    plain, styles = _markdown_to_signal("**bold** plain *it*")
    assert plain == "bold plain it"
    assert sorted(styles) == sorted(["0:4:BOLD", "11:2:ITALIC"])


def test_reported_daily_brief_pattern():
    """Regression for the reported bug: a single non-BMP emoji shifts every
    subsequent styled span left by 1 UTF-16 unit, lopping off the last letter.
    """
    md = (
        "**Weather**\n"
        "- Conditions: 🌩️ Thunderstorms\n\n"
        "**News**\n"
        "*World*\n"
        "*Local*\n\n"
        "**Quote of the Day**"
    )
    plain, styles = _markdown_to_signal(md)
    sd = utf16_styles_for(plain, styles)
    assert sd.get("Weather") == ["BOLD"]
    assert sd.get("News") == ["BOLD"]
    assert sd.get("World") == ["ITALIC"]
    assert sd.get("Local") == ["ITALIC"]
    assert sd.get("Quote of the Day") == ["BOLD"]
    assert_within_utf16_bounds(plain, styles)
