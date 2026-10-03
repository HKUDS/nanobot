"""Tests for AnthropicProvider._merge_consecutive."""

from nanobot.providers.anthropic_provider import AnthropicProvider


class TestMergeConsecutive:
    """Verify role alternation and trailing-assistant stripping."""

    def test_basic_alternation(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "bye"},
        ]
        result = AnthropicProvider._merge_consecutive(msgs)
        assert len(result) == 3
        assert [m["role"] for m in result] == ["user", "assistant", "user"]

    def test_consecutive_same_role_merged(self):
        msgs = [
            {"role": "user", "content": "a"},
            {"role": "user", "content": "b"},
            {"role": "assistant", "content": "reply"},
        ]
        result = AnthropicProvider._merge_consecutive(msgs)
        # Two user messages merged into one, trailing assistant stripped
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_trailing_assistant_stripped(self):
        """Anthropic rejects prefill — trailing assistant must be removed."""
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        result = AnthropicProvider._merge_consecutive(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "hello"

    def test_multiple_trailing_assistant_stripped(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "a"},
            {"role": "user", "content": "ok"},
            {"role": "assistant", "content": "b"},
            {"role": "assistant", "content": "c"},
        ]
        result = AnthropicProvider._merge_consecutive(msgs)
        # b+c merged into one assistant, then stripped as trailing
        assert len(result) == 3
        assert result[-1]["role"] == "user"
        assert result[-1]["content"] == "ok"

    def test_empty_messages(self):
        assert AnthropicProvider._merge_consecutive([]) == []

    def test_single_user_message(self):
        msgs = [{"role": "user", "content": "hi"}]
        result = AnthropicProvider._merge_consecutive(msgs)
        assert len(result) == 1

    def test_single_assistant_rerouted_to_user(self):
        """When stripping leaves nothing, the last assistant is rerouted to
        ``user`` so we don't produce an empty messages array."""
        msgs = [{"role": "assistant", "content": "hi"}]
        result = AnthropicProvider._merge_consecutive(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "hi"

    def test_all_assistants_collapse_then_rerouted(self):
        """Consecutive trailing assistants merge into one, which is then
        rerouted as a user turn carrying the merged content."""
        msgs = [
            {"role": "assistant", "content": "a"},
            {"role": "assistant", "content": "b"},
        ]
        result = AnthropicProvider._merge_consecutive(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        # "b" was merged into "a"'s block list during the merge pass.
        assert result[0]["content"] == [
            {"type": "text", "text": "a"},
            {"type": "text", "text": "b"},
        ]

    def test_assistant_with_tool_use_not_rerouted(self):
        """A trailing assistant carrying ``tool_use`` blocks cannot become a
        user turn (Anthropic rejects ``tool_use`` inside user messages), so
        the method returns an empty list rather than forging a bad request."""
        msgs = [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "let me search"},
                    {"type": "tool_use", "id": "t1", "name": "search", "input": {}},
                ],
            }
        ]
        result = AnthropicProvider._merge_consecutive(msgs)
        assert result == []

    def test_leading_assistant_gets_synthetic_user(self):
        """If the first turn is a bare assistant (e.g. history truncation
        dropped the original user request), prepend a synthetic opener so
        the conversation still starts with ``user``."""
        msgs = [
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "ok"},
            {"role": "assistant", "content": "reply"},
        ]
        result = AnthropicProvider._merge_consecutive(msgs)
        assert [m["role"] for m in result] == ["user", "assistant", "user"]
        assert result[0]["content"] == "(conversation continued)"
        assert result[1]["content"] == "hi"
        assert result[2]["content"] == "ok"

    def test_leading_assistant_with_tool_use_left_alone(self):
        """Don't prepend a synthetic opener before an assistant carrying
        ``tool_use``; doing so would orphan the paired ``tool_result`` that
        follows.  The caller will see the original 400 rather than a
        harder-to-diagnose tool-pair mismatch."""
        msgs = [
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "search", "input": {}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
                ],
            },
        ]
        result = AnthropicProvider._merge_consecutive(msgs)
        assert [m["role"] for m in result] == ["assistant", "user"]
