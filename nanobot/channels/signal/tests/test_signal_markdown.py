"""Unit tests for the Signal markdown → plain text + textStyle converter."""

import pytest

from nanobot.channels.signal.runtime import _markdown_to_signal, _partition_styles
from nanobot.utils.helpers import split_message


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


@pytest.mark.parametrize(
    "markdown, expected_plain",
    [
        pytest.param("", "", id="empty"),
        pytest.param("hello world", "hello world", id="plain_text"),
        pytest.param("> some quote", "some quote", id="blockquote_strips_marker"),
        pytest.param(
            "[Click here](https://example.com)",
            "Click here (https://example.com)",
            id="link_text_differs_from_url",
        ),
        pytest.param(
            "[https://example.com](https://example.com)",
            "https://example.com",
            id="link_text_equals_url",
        ),
        pytest.param("**bold", "**bold", id="unclosed_bold_falls_through_as_plain"),
        pytest.param("use `grep", "use `grep", id="unclosed_inline_code_falls_through_as_plain"),
    ],
)
def test_markdown_without_styles(markdown, expected_plain):
    plain, styles = _markdown_to_signal(markdown)
    assert plain == expected_plain
    assert styles == []


@pytest.mark.parametrize(
    "markdown, expected_plain, styled_text, style",
    [
        pytest.param("say **hello** now", "say hello now", "hello", "BOLD", id="bold_stars"),
        pytest.param("say __hello__ now", "say hello now", "hello", "BOLD", id="bold_underscores"),
        pytest.param("say *hello* now", "say hello now", "hello", "ITALIC", id="italic_star"),
        pytest.param("say _hello_ now", "say hello now", "hello", "ITALIC", id="italic_underscore"),
        pytest.param("say ~~hello~~ now", "say hello now", "hello", "STRIKETHROUGH", id="strikethrough"),
        pytest.param("run `ls -la` here", "run ls -la here", "ls -la", "MONOSPACE", id="inline_code"),
        pytest.param("# My Title", "My Title", "My Title", "BOLD", id="header_becomes_bold"),
        pytest.param("## Sub-section", "Sub-section", "Sub-section", "BOLD", id="h2_becomes_bold"),
    ],
)
def test_markdown_style_mapping(markdown, expected_plain, styled_text, style):
    plain, styles = _markdown_to_signal(markdown)
    assert plain == expected_plain
    assert styles_for(plain, styles) == {styled_text: [style]}


# ---------------------------------------------------------------------------
# Code
# ---------------------------------------------------------------------------


def test_code_block():
    plain, styles = _markdown_to_signal("```\nprint('hi')\n```")
    assert "print('hi')" in plain
    assert styles_for(plain, styles).get("print('hi')\n") == ["MONOSPACE"] or "MONOSPACE" in str(
        styles_for(plain, styles)
    )


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
        assert start + length <= limit, f"range {entry} exceeds utf-16 length {limit} of {plain!r}"


@pytest.mark.parametrize(
    "markdown, expected_plain, styled_text, style",
    [
        pytest.param("**hi 🎉 bye**", "hi 🎉 bye", "hi 🎉 bye", "BOLD", id="bold_with_emoji_inside"),
        pytest.param("*bye 🎉*", "bye 🎉", "bye 🎉", "ITALIC", id="italic_with_trailing_emoji"),
        pytest.param("🎉 **bold**", "🎉 bold", "bold", "BOLD", id="bold_after_emoji_prefix"),
        pytest.param("🎉 **a 🎊 b**", "🎉 a 🎊 b", "a 🎊 b", "BOLD", id="bold_after_and_inside_emoji"),
        pytest.param("**𠮷野家**", "𠮷野家", "𠮷野家", "BOLD", id="supplementary_cjk_in_bold"),
        pytest.param("**hi 👨‍👩‍👧 bye**", "hi 👨‍👩‍👧 bye", "hi 👨‍👩‍👧 bye", "BOLD", id="zwj_emoji_in_bold"),
    ],
)
def test_style_offsets_use_utf16(markdown, expected_plain, styled_text, style):
    plain, styles = _markdown_to_signal(markdown)
    assert plain == expected_plain
    assert utf16_styles_for(plain, styles) == {styled_text: [style]}
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


# ---------------------------------------------------------------------------
# Chunk redistribution
#
# split_message can break a long Signal payload into multiple chunks. The
# style ranges from _markdown_to_signal are anchored to the full text, so
# they must be redistributed per-chunk with rebased offsets — otherwise
# styles for chunks 1..N are silently lost.
# ---------------------------------------------------------------------------


def test_partition_styles_single_chunk_passthrough():
    plain, styles = _markdown_to_signal("**bold** plain *it*")
    parts = _partition_styles(plain, [plain], styles)
    assert parts == [styles]


def test_partition_styles_no_styles():
    plain = "hello world"
    assert _partition_styles(plain, [plain], []) == [[]]
    assert _partition_styles(plain, ["hello", "world"], []) == [[], []]


def test_partition_styles_drops_styles_outside_chunks():
    """Whitespace trimmed by split_message must not carry a style range."""
    plain = "a   b"
    # Fake a style spanning the trimmed whitespace only.
    chunks = ["a", "b"]
    parts = _partition_styles(plain, chunks, ["1:3:BOLD"])
    assert parts == [[], []]


def test_partition_styles_keeps_offset_in_indented_chunk():
    """Styles after preserved indentation remain relative to the chunk."""
    plain = "header\n    code"
    chunks = split_message(plain, 10)

    assert chunks == ["header", "    code"]
    assert _partition_styles(plain, chunks, ["11:4:BOLD"]) == [[], ["4:4:BOLD"]]


def test_partition_styles_keeps_offset_after_crlf_boundary():
    plain = "header\r\n    code"
    chunks = split_message(plain, 10)

    assert chunks == ["header", "    code"]
    assert _partition_styles(plain, chunks, ["12:4:BOLD"]) == [[], ["4:4:BOLD"]]


def test_partition_styles_long_message_preserves_chunk_one_styles():
    """A bold span deep in the message must follow the message into chunk 1."""
    # Two ~30-char paragraphs separated by a blank line, then **tail**.
    line_a = "alpha " * 5  # 30 chars, ends with space
    line_b = "beta " * 5
    md = f"{line_a.strip()}\n\n{line_b.strip()}\n\n**tail**"
    plain, styles = _markdown_to_signal(md)
    # Force a split between the paragraphs.
    max_len = len(line_a.strip()) + 2  # fits paragraph A + the "\n\n"
    chunks = split_message(plain, max_len)
    assert len(chunks) >= 2, "test setup must produce a split"
    parts = _partition_styles(plain, chunks, styles)
    # The bold "tail" should land in the last chunk, with chunk-relative offset.
    final_chunk = chunks[-1]
    final_styles = parts[-1]
    assert any("BOLD" in s for s in final_styles)
    for entry in final_styles:
        s, ln, _ = entry.split(":", 2)
        start, length = int(s), int(ln)
        slice_ = final_chunk.encode("utf-16-le")[start * 2 : (start + length) * 2].decode(
            "utf-16-le"
        )
        assert slice_ == "tail"


def test_partition_styles_chunk_zero_styles_unchanged():
    """Styles entirely in chunk 0 keep their original offsets."""
    md = "**head** middle and **tail**"
    plain, styles = _markdown_to_signal(md)
    # Split so chunk 0 contains "head" and part of the rest, chunk 1 contains "tail".
    chunks = split_message(plain, 12)
    assert len(chunks) >= 2
    parts = _partition_styles(plain, chunks, styles)
    # "head" lives in chunk 0; assert its offset is unchanged (chunk 0 starts at 0).
    head_entries = [s for s in parts[0] if "BOLD" in s]
    assert any(s.startswith("0:4:") for s in head_entries)


def test_partition_styles_with_non_bmp_chunk_offset():
    """Chunk-start offsets must be expressed in UTF-16 code units."""
    # Emoji in chunk 0, bold in chunk 1.
    md = "🎉 alpha beta gamma\n\n**tail**"
    plain, styles = _markdown_to_signal(md)
    chunks = split_message(plain, 18)
    assert len(chunks) >= 2
    parts = _partition_styles(plain, chunks, styles)
    final_styles = parts[-1]
    assert any("BOLD" in s for s in final_styles)
    final_chunk = chunks[-1]
    for entry in final_styles:
        s, ln, _ = entry.split(":", 2)
        start, length = int(s), int(ln)
        slice_ = final_chunk.encode("utf-16-le")[start * 2 : (start + length) * 2].decode(
            "utf-16-le"
        )
        assert slice_ == "tail"


def test_partition_styles_range_spanning_chunks_is_split():
    """A style range that straddles a chunk boundary gets sliced into both chunks."""
    # Construct manually: plain = "abc def", style covers "abc def" (whole thing).
    plain = "abc def"
    chunks = split_message(plain, 4)  # "abc" / "def"
    assert chunks == ["abc", "def"]
    parts = _partition_styles(plain, chunks, ["0:7:BOLD"])
    # Chunk 0 holds 0:3:BOLD, chunk 1 holds 0:3:BOLD (length=3 each, "def" only
    # since the space was trimmed by lstrip).
    assert parts[0] == ["0:3:BOLD"]
    assert parts[1] == ["0:3:BOLD"]


# ---------------------------------------------------------------------------
# Adjacency, nesting, and malformed input
# ---------------------------------------------------------------------------


def test_bold_italic_combo_outer_bold_inner_italic():
    """`**_combo_**` carries both BOLD and ITALIC over the same span."""
    plain, styles = _markdown_to_signal("**_combo_**")
    assert plain == "combo"
    sd = styles_for(plain, styles)
    assert set(sd.get("combo", [])) == {"BOLD", "ITALIC"}


def test_bold_and_italic_adjacent_no_separator():
    """`**bold***italic*` produces BOLD on `bold` and ITALIC on `italic`."""
    plain, styles = _markdown_to_signal("**bold***italic*")
    assert plain == "bolditalic"
    sd = styles_for(plain, styles)
    assert sd.get("bold") == ["BOLD"]
    assert sd.get("italic") == ["ITALIC"]


def test_inline_code_inside_blockquote():
    """Blockquote prefix is stripped; inline code becomes MONOSPACE."""
    plain, styles = _markdown_to_signal("> use `grep`")
    assert plain == "use grep"
    sd = styles_for(plain, styles)
    assert sd.get("grep") == ["MONOSPACE"]


def test_header_with_inner_bold_produces_contiguous_bold_ranges():
    """`# **wrap** me` — header forces BOLD over the whole line; the inner `**`
    splits the run, yielding two contiguous BOLD ranges that together cover
    "wrap me". This is intentional — Signal renders adjacent same-style ranges
    as a single visual span.
    """
    plain, styles = _markdown_to_signal("# **wrap** me")
    assert plain == "wrap me"
    # Both ranges are BOLD; collectively they cover the whole "wrap me".
    bold_ranges = [s for s in styles if s.endswith(":BOLD")]
    assert len(bold_ranges) == 2
    covered = set()
    for entry in bold_ranges:
        start, length, _ = entry.split(":", 2)
        for i in range(int(start), int(start) + int(length)):
            covered.add(i)
    assert covered == set(range(len(plain)))
