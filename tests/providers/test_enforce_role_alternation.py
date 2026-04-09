"""Tests for LLMProvider._enforce_role_alternation."""

from nanobot.providers.base import LLMProvider


class TestEnforceRoleAlternation:
    """Verify trailing-assistant removal and consecutive same-role merging."""

    def test_empty_messages(self):
        assert LLMProvider._enforce_role_alternation([]) == []

    def test_no_change_needed(self):
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
            {"role": "user", "content": "Bye"},
        ]
        result = LLMProvider._enforce_role_alternation(msgs)
        assert len(result) == 4
        assert result[-1]["role"] == "user"

    def test_trailing_assistant_removed(self):
        msgs = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
        ]
        result = LLMProvider._enforce_role_alternation(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_multiple_trailing_assistants_removed(self):
        msgs = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "A"},
            {"role": "assistant", "content": "B"},
        ]
        result = LLMProvider._enforce_role_alternation(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_consecutive_user_messages_merged(self):
        msgs = [
            {"role": "user", "content": "Hello"},
            {"role": "user", "content": "How are you?"},
        ]
        result = LLMProvider._enforce_role_alternation(msgs)
        assert len(result) == 1
        assert "Hello" in result[0]["content"]
        assert "How are you?" in result[0]["content"]

    def test_consecutive_assistant_messages_merged(self):
        msgs = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
            {"role": "assistant", "content": "How can I help?"},
            {"role": "user", "content": "Thanks"},
        ]
        result = LLMProvider._enforce_role_alternation(msgs)
        assert len(result) == 3
        assert "Hello!" in result[1]["content"]
        assert "How can I help?" in result[1]["content"]

    def test_system_messages_not_merged(self):
        msgs = [
            {"role": "system", "content": "System A"},
            {"role": "system", "content": "System B"},
            {"role": "user", "content": "Hi"},
        ]
        result = LLMProvider._enforce_role_alternation(msgs)
        assert len(result) == 3
        assert result[0]["content"] == "System A"
        assert result[1]["content"] == "System B"

    def test_tool_messages_not_merged(self):
        msgs = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]},
            {"role": "tool", "content": "result1", "tool_call_id": "1"},
            {"role": "tool", "content": "result2", "tool_call_id": "2"},
            {"role": "user", "content": "Next"},
        ]
        result = LLMProvider._enforce_role_alternation(msgs)
        tool_msgs = [m for m in result if m["role"] == "tool"]
        assert len(tool_msgs) == 2

    def test_non_string_content_uses_latest(self):
        msgs = [
            {"role": "user", "content": [{"type": "text", "text": "A"}]},
            {"role": "user", "content": "B"},
        ]
        result = LLMProvider._enforce_role_alternation(msgs)
        assert len(result) == 1
        assert result[0]["content"] == "B"

    def test_original_messages_not_mutated(self):
        msgs = [
            {"role": "user", "content": "Hello"},
            {"role": "user", "content": "World"},
        ]
        original_first = dict(msgs[0])
        LLMProvider._enforce_role_alternation(msgs)
        assert msgs[0] == original_first
        assert len(msgs) == 2

    def test_only_assistant_messages(self):
        msgs = [
            {"role": "assistant", "content": "A"},
            {"role": "assistant", "content": "B"},
        ]
        result = LLMProvider._enforce_role_alternation(msgs)
        assert result == []

    def test_realistic_conversation(self):
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "4"},
            {"role": "user", "content": "And 3+3?"},
            {"role": "user", "content": "(please be quick)"},
            {"role": "assistant", "content": "6"},
        ]
        result = LLMProvider._enforce_role_alternation(msgs)
        assert len(result) == 4
        assert result[2]["role"] == "assistant"
        assert result[3]["role"] == "user"
        assert "And 3+3?" in result[3]["content"]
        assert "(please be quick)" in result[3]["content"]
