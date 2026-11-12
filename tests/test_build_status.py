from nanobot.providers.base import LLMUsage
from nanobot.utils.helpers import build_status_content


def test_status_shows_cache_hit_rate():
    content = build_status_content(
        version="0.1.0",
        model="glm-4-plus",
        start_time=1000000.0,
        last_usage=LLMUsage.reported(input_tokens=2000, output_tokens=300, cache_read_tokens=1200),
        context_window_tokens=128000,
        session_msg_count=10,
        context_tokens_estimate=5000,
    )
    assert "60% cached" in content
    assert "2000 in / 300 out" in content
    assert "Tasks: 0 active" in content


def test_status_no_cache_info():
    content = build_status_content(
        version="0.1.0",
        model="glm-4-plus",
        start_time=1000000.0,
        last_usage=LLMUsage.reported(input_tokens=2000, output_tokens=300),
        context_window_tokens=128000,
        session_msg_count=10,
        context_tokens_estimate=5000,
    )
    assert "cached" not in content.lower()
    assert "2000 in / 300 out" in content
    assert "Tasks: 0 active" in content


def test_status_zero_cache_read_tokens():
    content = build_status_content(
        version="0.1.0",
        model="glm-4-plus",
        start_time=1000000.0,
        last_usage=LLMUsage.reported(input_tokens=2000, output_tokens=300, cache_read_tokens=0),
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
        last_usage=LLMUsage.reported(input_tokens=1000, output_tokens=100, cache_read_tokens=1000),
        context_window_tokens=128000,
        session_msg_count=5,
        context_tokens_estimate=3000,
    )
    assert "100% cached" in content


def test_status_context_pct_uses_budget_not_total():
    content = build_status_content(
        version="0.1.0",
        model="test",
        start_time=1000000.0,
        last_usage=LLMUsage.reported(input_tokens=2000, output_tokens=300),
        context_window_tokens=128000,
        session_msg_count=10,
        context_tokens_estimate=120000,
        max_completion_tokens=8192,
    )
    assert "(101% of input budget)" in content


def test_status_context_pct_capped_at_999():
    content = build_status_content(
        version="0.1.0",
        model="test",
        start_time=1000000.0,
        last_usage=LLMUsage.reported(input_tokens=2000, output_tokens=300),
        context_window_tokens=10000,
        session_msg_count=10,
        context_tokens_estimate=100000,
        max_completion_tokens=4096,
    )
    assert "(999% of input budget)" in content
