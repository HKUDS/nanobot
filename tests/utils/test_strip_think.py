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
        text = 'Example:\n```\ntext = re.sub(r"<think>[\\s\\S]*", "", text)\n```\nDone.'
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


class TestStripThinkMalformedLeaks:
    """Regression: Gemma 4's Ollama renderer occasionally emits a tag name
    with no closing '>', running straight into the user-facing content
    (e.g. `<think广场照明灯目前…`). The earlier regexes required '>' and
    let these through."""

    def test_malformed_think_no_gt_chinese(self):
        assert strip_think("<think广场照明灯目前绑定在'照明灯'策略下") == (
            "广场照明灯目前绑定在'照明灯'策略下"
        )

    def test_malformed_think_no_gt_english_with_space(self):
        # English leak with a space after the tag name (common streaming form).
        assert strip_think("<think The fountain opens at 09:00") == ("The fountain opens at 09:00")

    def test_malformed_thought_no_gt(self):
        assert strip_think("<thought广场照明灯") == "广场照明灯"

    def test_thinker_word_preserved(self):
        # `<thinker>` is a valid tag name variant; must not match.
        assert strip_think("<thinker>content</thinker>") == "<thinker>content</thinker>"

    def test_self_closing_preserved(self):
        assert strip_think("<think/>ok") == "<think/>ok"
        assert strip_think("<thought/>ok") == "<thought/>ok"

    def test_orphan_closing_think_at_end_stripped(self):
        # Typical leak: model opens `<think>` without closing; we strip the
        # opener from the start, leaving an orphan `</think>` at the end.
        assert strip_think("answer</think>") == "answer"

    def test_orphan_closing_think_at_start_stripped(self):
        assert strip_think("</think>answer") == "answer"

    def test_channel_marker_at_start_stripped(self):
        # Harmony / Gemma 4 channel markers leak at the start of a response.
        assert strip_think("<channel|>喷泉策略：09:00 开启") == ("喷泉策略：09:00 开启")
        assert strip_think("<|channel|>answer") == "answer"


class TestStripThinkConservativePreserve:
    """Regression: the malformed-tag / orphan cleanup must NOT touch
    legitimate prose or code that mentions these tokens literally, otherwise
    `strip_think` (which runs before history is persisted, memory.py) will
    silently rewrite the conversation transcript."""

    def test_think_dash_variant_preserved(self):
        assert strip_think("<think-foo>bar</think-foo>") == "<think-foo>bar</think-foo>"

    def test_think_underscore_variant_preserved(self):
        assert strip_think("<think_foo>bar</think_foo>") == "<think_foo>bar</think_foo>"

    def test_think_numeric_variant_preserved(self):
        assert strip_think("<think1>bar</think1>") == "<think1>bar</think1>"

    def test_think_namespaced_variant_preserved(self):
        assert strip_think("<think:foo>bar</think:foo>") == "<think:foo>bar</think:foo>"

    def test_literal_close_think_in_prose_preserved(self):
        # Mid-prose references to `</think>` in backticks or plain text must
        # not be stripped; edge-only regex protects this.
        text = "Use `</think>` to close a thinking block."
        assert strip_think(text) == text

    def test_literal_channel_marker_in_prose_preserved(self):
        text = "The Harmony spec uses `<|channel|>` and `<channel|>` markers."
        assert strip_think(text) == text

    def test_literal_channel_marker_in_code_block_preserved(self):
        text = "Example:\n```\nif line.startswith('<channel|>'):\n    skip()\n```"
        assert strip_think(text) == text
