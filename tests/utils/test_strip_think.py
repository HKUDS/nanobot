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
