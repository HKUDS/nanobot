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

    def test_single_assistant_stripped(self):
        msgs = [{"role": "assistant", "content": "hi"}]
        result = AnthropicProvider._merge_consecutive(msgs)
        assert len(result) == 0
