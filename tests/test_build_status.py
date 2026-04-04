"""Tests for build_status_content cache hit rate display."""

from janniebot.utils.helpers import build_status_content


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
