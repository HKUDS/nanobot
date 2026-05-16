"""Unit tests for the Signal markdown → plain text + textStyle converter."""

from nanobot.channels.signal import _markdown_to_signal


def styles_for(plain: str, text_styles: list[str]) -> dict[str, list[str]]:
    """Return a dict mapping each styled substring to its style list."""
    result: dict[str, list[str]] = {}
    for entry in text_styles:
        start_s, length_s, style = entry.split(":", 2)
        start, length = int(start_s), int(length_s)
        span = plain[start : start + length]
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
