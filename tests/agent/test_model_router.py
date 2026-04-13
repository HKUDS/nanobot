"""Tests for the lightweight model router."""

from __future__ import annotations

import pytest

from nanobot.agent.model_router import (
    pick_model,
    _last_user_text,
    _last_user_length,
    _user_turn_count,
    _has_tool_history,
)

MAIN = "anthropic/claude-opus-4-5"
LIGHT = "anthropic/claude-sonnet-4"


# ── Helper to build message lists ────────────────────────────────────

def _user(text: str) -> dict:
    return {"role": "user", "content": text}


def _assistant(text: str) -> dict:
    return {"role": "assistant", "content": text}


def _tool_result(tool_call_id: str = "call_1", content: str = "ok") -> dict:
    return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


def _user_multipart(text: str, image_url: str = "data:image/png;base64,abc") -> dict:
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": image_url}},
        ],
    }


# ═══════════════════════════════════════════════════════════════════════
# 1. Routing disabled (strategy="none" or light_model=None)
# ═══════════════════════════════════════════════════════════════════════

class TestRoutingDisabled:
    """When routing is off, always return main model regardless of messages."""

    def test_strategy_none_returns_main(self):
        msgs = [_user("hello")]
        assert pick_model(msgs, MAIN, LIGHT, "none") == MAIN

    def test_light_model_none_returns_main(self):
        msgs = [_user("hello")]
        assert pick_model(msgs, MAIN, None, "auto") == MAIN

    def test_light_model_empty_string_returns_main(self):
        msgs = [_user("hello")]
        assert pick_model(msgs, MAIN, "", "auto") == MAIN

    def test_default_strategy_is_none(self):
        msgs = [_user("hello")]
        # default strategy parameter is "none"
        assert pick_model(msgs, MAIN, LIGHT) == MAIN


# ═══════════════════════════════════════════════════════════════════════
# 2. Auto routing — simple tasks → light model
# ═══════════════════════════════════════════════════════════════════════

class TestAutoRoutingSimple:
    """Short, early, tool-free conversations should route to light model."""

    def test_short_greeting(self):
        msgs = [_user("你好")]
        assert pick_model(msgs, MAIN, LIGHT, "auto") == LIGHT

    def test_simple_question(self):
        msgs = [_user("What time is it?")]
        assert pick_model(msgs, MAIN, LIGHT, "auto") == LIGHT

    def test_two_turn_simple_chat(self):
        msgs = [
            _user("hi"),
            _assistant("Hello! How can I help?"),
            _user("What's the weather?"),
        ]
        assert pick_model(msgs, MAIN, LIGHT, "auto") == LIGHT

    def test_multipart_short_text(self):
        msgs = [_user_multipart("What is this?")]
        assert pick_model(msgs, MAIN, LIGHT, "auto") == LIGHT


# ═══════════════════════════════════════════════════════════════════════
# 3. Auto routing — complex tasks → main model
# ═══════════════════════════════════════════════════════════════════════

class TestAutoRoutingComplex:
    """Complex keyword or structural signals should keep main model."""

    @pytest.mark.parametrize("keyword", [
        "请帮我重构这段代码",
        "debug this function",
        "分析一下这个日志",
        "implement a REST API",
        "帮我写代码实现排序",
        "fix the bug in line 42",
        "deploy to production",
        "review this PR",
        "请帮我设计一个数据库架构",
        "optimize the query performance",
    ])
    def test_complex_keywords_use_main(self, keyword):
        msgs = [_user(keyword)]
        assert pick_model(msgs, MAIN, LIGHT, "auto") == MAIN

    def test_long_message_uses_main(self):
        """A message > 200 chars should not be considered simple."""
        long_text = "Please explain " + "x " * 150  # well over 200 chars
        msgs = [_user(long_text)]
        assert pick_model(msgs, MAIN, LIGHT, "auto") == MAIN

    def test_many_user_turns_uses_main(self):
        """More than 2 user turns → not simple."""
        msgs = [
            _user("hi"),
            _assistant("hello"),
            _user("how are you"),
            _assistant("good"),
            _user("tell me a joke"),
        ]
        assert pick_model(msgs, MAIN, LIGHT, "auto") == MAIN

    def test_tool_history_uses_main(self):
        """If there are tool results in history, it's a complex session."""
        msgs = [
            _user("list files"),
            _assistant("Sure"),
            _tool_result("call_1", "file1.py\nfile2.py"),
            _assistant("Here are the files."),
            _user("thanks"),
        ]
        assert pick_model(msgs, MAIN, LIGHT, "auto") == MAIN

    def test_complex_keyword_overrides_short_message(self):
        """Even a short message with a complex keyword → main model."""
        msgs = [_user("debug it")]
        assert pick_model(msgs, MAIN, LIGHT, "auto") == MAIN

    def test_chinese_complex_keyword(self):
        msgs = [_user("帮我修复")]
        assert pick_model(msgs, MAIN, LIGHT, "auto") == MAIN


# ═══════════════════════════════════════════════════════════════════════
# 4. Helper function unit tests
# ═══════════════════════════════════════════════════════════════════════

class TestHelpers:

    def test_last_user_text_string(self):
        msgs = [_user("Hello World")]
        assert _last_user_text(msgs) == "hello world"

    def test_last_user_text_multipart(self):
        msgs = [_user_multipart("Check This")]
        assert "check this" in _last_user_text(msgs)

    def test_last_user_text_empty(self):
        msgs = [_assistant("hi")]
        assert _last_user_text(msgs) == ""

    def test_last_user_text_picks_last(self):
        msgs = [_user("first"), _assistant("ok"), _user("second")]
        assert _last_user_text(msgs) == "second"

    def test_last_user_length_string(self):
        msgs = [_user("abcde")]
        assert _last_user_length(msgs) == 5

    def test_last_user_length_multipart(self):
        msgs = [_user_multipart("abcde")]
        assert _last_user_length(msgs) == 5

    def test_last_user_length_empty(self):
        msgs = [_assistant("hi")]
        assert _last_user_length(msgs) == 0

    def test_user_turn_count(self):
        msgs = [_user("a"), _assistant("b"), _user("c")]
        assert _user_turn_count(msgs) == 2

    def test_user_turn_count_zero(self):
        msgs = [_assistant("b")]
        assert _user_turn_count(msgs) == 0

    def test_has_tool_history_true(self):
        msgs = [_user("hi"), _tool_result()]
        assert _has_tool_history(msgs) is True

    def test_has_tool_history_false(self):
        msgs = [_user("hi"), _assistant("hello")]
        assert _has_tool_history(msgs) is False


# ═══════════════════════════════════════════════════════════════════════
# 5. Edge cases
# ═══════════════════════════════════════════════════════════════════════

class TestEdgeCases:

    def test_empty_messages(self):
        """Empty message list should return main model (safe default)."""
        assert pick_model([], MAIN, LIGHT, "auto") == MAIN

    def test_only_assistant_messages(self):
        msgs = [_assistant("I'm ready")]
        # No user message → _last_user_text returns "" → no complex keyword
        # _user_turn_count = 0 (<=2 ✓), _last_user_length = 0 (<200 ✓), no tool ✓
        # All simple signals pass → light model
        assert pick_model(msgs, MAIN, LIGHT, "auto") == LIGHT

    def test_case_insensitive_keywords(self):
        """Keywords should match case-insensitively."""
        msgs = [_user("REFACTOR the module")]
        assert pick_model(msgs, MAIN, LIGHT, "auto") == MAIN

    def test_keyword_as_substring(self):
        """Keywords embedded in longer words should still match."""
        msgs = [_user("debugging")]
        assert pick_model(msgs, MAIN, LIGHT, "auto") == MAIN

    def test_exactly_200_chars_is_simple(self):
        """Boundary: exactly 200 chars is NOT < 200, so not simple."""
        text = "a" * 200
        msgs = [_user(text)]
        assert pick_model(msgs, MAIN, LIGHT, "auto") == MAIN

    def test_199_chars_is_simple(self):
        text = "a" * 199
        msgs = [_user(text)]
        assert pick_model(msgs, MAIN, LIGHT, "auto") == LIGHT

    def test_exactly_2_user_turns_is_simple(self):
        msgs = [_user("a"), _assistant("b"), _user("c")]
        assert pick_model(msgs, MAIN, LIGHT, "auto") == LIGHT

    def test_3_user_turns_is_complex(self):
        msgs = [
            _user("a"), _assistant("b"),
            _user("c"), _assistant("d"),
            _user("e"),
        ]
        assert pick_model(msgs, MAIN, LIGHT, "auto") == MAIN


# ═══════════════════════════════════════════════════════════════════════
# 6. Config schema integration
# ═══════════════════════════════════════════════════════════════════════

class TestConfigSchema:
    """Verify the new fields exist on AgentDefaults with correct defaults."""

    def test_defaults_have_light_model_none(self):
        from nanobot.config.schema import AgentDefaults
        d = AgentDefaults()
        assert d.light_model is None

    def test_defaults_have_routing_strategy_none(self):
        from nanobot.config.schema import AgentDefaults
        d = AgentDefaults()
        assert d.routing_strategy == "none"

    def test_light_model_can_be_set(self):
        from nanobot.config.schema import AgentDefaults
        d = AgentDefaults(light_model="openai/gpt-4o-mini")
        assert d.light_model == "openai/gpt-4o-mini"

    def test_routing_strategy_auto(self):
        from nanobot.config.schema import AgentDefaults
        d = AgentDefaults(routing_strategy="auto")
        assert d.routing_strategy == "auto"
