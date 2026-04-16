"""Tests for build_status_content cache hit rate display."""

import json

from nanobot.utils.helpers import (
    build_context_dict,
    build_status_content,
    build_status_dict,
    format_session_context_view,
)


def test_status_shows_cache_hit_rate():
    content = build_status_content(
        version="0.1.0",
        model="glm-4-plus",
        start_time=1000000.0,
        last_usage={"prompt_tokens": 2000, "completion_tokens": 300, "cached_tokens": 1200},
        context_window_tokens=128000,
        session_msg_count=10,
        context_tokens_estimate=5000,
    )
    assert "60% cached" in content
    assert "2000 in / 300 out" in content


def test_status_no_cache_info():
    """Without cached_tokens, display should not show cache percentage."""
    content = build_status_content(
        version="0.1.0",
        model="glm-4-plus",
        start_time=1000000.0,
        last_usage={"prompt_tokens": 2000, "completion_tokens": 300},
        context_window_tokens=128000,
        session_msg_count=10,
        context_tokens_estimate=5000,
    )
    assert "cached" not in content.lower()
    assert "2000 in / 300 out" in content


def test_status_zero_cached_tokens():
    """cached_tokens=0 should not show cache percentage."""
    content = build_status_content(
        version="0.1.0",
        model="glm-4-plus",
        start_time=1000000.0,
        last_usage={"prompt_tokens": 2000, "completion_tokens": 300, "cached_tokens": 0},
        context_window_tokens=128000,
        session_msg_count=10,
        context_tokens_estimate=5000,
    )
    assert "cached" not in content.lower()


def test_status_100_percent_cached():
    content = build_status_content(
        version="0.1.0",
        model="glm-4-plus",
        start_time=1000000.0,
        last_usage={"prompt_tokens": 1000, "completion_tokens": 100, "cached_tokens": 1000},
        context_window_tokens=128000,
        session_msg_count=5,
        context_tokens_estimate=3000,
    )
    assert "100% cached" in content


def test_build_status_dict_matches_token_and_cache_fields():
    d = build_status_dict(
        version="0.1.0",
        model="glm-4-plus",
        start_time=1000000.0,
        last_usage={"prompt_tokens": 2000, "completion_tokens": 300, "cached_tokens": 1200},
        context_window_tokens=128000,
        session_msg_count=10,
        context_tokens_estimate=5000,
    )
    assert d["tokens"]["last_prompt"] == 2000
    assert d["tokens"]["last_completion"] == 300
    assert d["tokens"]["cached_percent_of_prompt"] == 60
    assert d["context"]["percent_used"] > 0
    json.dumps(d)  # JSON-serializable


def test_build_status_dict_includes_search_when_given():
    d = build_status_dict(
        version="0.1.0",
        model="m",
        start_time=1000000.0,
        last_usage={},
        context_window_tokens=100,
        session_msg_count=1,
        context_tokens_estimate=0,
        search_usage={"provider": "duckduckgo", "supported": False},
    )
    assert d["search"]["provider"] == "duckduckgo"


def test_format_session_context_view_empty():
    assert format_session_context_view([]) == "No messages in current session context."


def test_format_session_context_view_messages():
    text = format_session_context_view(
        [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
    )
    assert "## Context (2 message(s))" in text
    assert "### 1. `user`" in text
    assert "hello" in text
    assert "### 2. `assistant`" in text


def test_build_context_dict():
    d = build_context_dict(
        session_key="telegram:u1",
        messages=[{"role": "user", "content": "x"}],
    )
    assert d["session_key"] == "telegram:u1"
    assert d["messages"][0]["role"] == "user"
    json.dumps(d)
