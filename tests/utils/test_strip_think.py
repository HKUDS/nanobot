import pytest

from nanobot.utils.helpers import strip_think


class TestStripThinkTag:
    """Test <thought>...</thought> block stripping (Gemma 4 and similar models)."""

    def test_closed_tag(self):
        assert strip_think("Hello <thought>reasoning</thought> World") == "Hello  World"

    def test_unclosed_trailing_tag(self):
        assert strip_think("<thought>ongoing...") == ""

    def test_multiline_tag(self):
        assert strip_think("<thought>\nline1\nline2\n</thought>End") == "End"

    def test_tag_with_nested_angle_brackets(self):
        text = "<thought>a < 3 and b > 2</thought>result"
        assert strip_think(text) == "result"

    def test_multiple_tag_blocks(self):
        text = "A<thought>x</thought>B<thought>y</thought>C"
        assert strip_think(text) == "ABC"

    def test_tag_only_whitespace_inside(self):
        assert strip_think("before<thought>  </thought>after") == "beforeafter"

    def test_self_closing_tag_not_matched(self):
        assert strip_think("<thought/>some text") == "<thought/>some text"

    def test_normal_text_unchanged(self):
        assert strip_think("Just normal text") == "Just normal text"

    def test_empty_string(self):
        assert strip_think("") == ""


class TestStripThinkFalsePositive:
    """Ensure mid-content <think>/<thought> tags are NOT stripped (#3004)."""

    def test_backtick_think_tag_preserved(self):
        text = "*Think Stripping:* A new utility to strip `<think>` tags from output."
        assert strip_think(text) == text

    def test_prose_think_tag_preserved(self):
        text = "The model emits <think> at the start of its response."
        assert strip_think(text) == text

    def test_code_block_think_tag_preserved(self):
        text = "Example:\n```\ntext = re.sub(r\"<think>[\\s\\S]*\", \"\", text)\n```\nDone."
        assert strip_think(text) == text

    def test_backtick_thought_tag_preserved(self):
        text = "Gemma 4 uses `<thought>` blocks for reasoning."
        assert strip_think(text) == text

    def test_prefix_unclosed_think_still_stripped(self):
        assert strip_think("<think>reasoning without closing") == ""

    def test_prefix_unclosed_think_with_whitespace(self):
        assert strip_think("  <think>reasoning...") == ""

    def test_prefix_unclosed_thought_still_stripped(self):
        assert strip_think("<thought>reasoning without closing") == ""
