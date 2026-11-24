from nanobot.command.results import render
from nanobot.command.status import status_lines
from nanobot.providers.base import LLMUsage


def status_text(**kwargs):
    return render(tuple(status_lines(**kwargs)), "en")


def test_status_shows_cache_hit_rate():
    content = status_text(
        version="0.1.0",
        model="glm-4-plus",
        start_time=1000000.0,
        last_usage=LLMUsage.reported(input_tokens=2000, output_tokens=300, cache_read_tokens=1200),
        context_window_tokens=128000,
        session_msg_count=10,
        context_tokens=5000,
    )
    assert "60% cached" in content
    assert "2000 in / 300 out" in content
    assert "Tasks: 0 active" in content


def test_status_no_cache_info():
    content = status_text(
        version="0.1.0",
        model="glm-4-plus",
        start_time=1000000.0,
        last_usage=LLMUsage.reported(input_tokens=2000, output_tokens=300),
        context_window_tokens=128000,
        session_msg_count=10,
        context_tokens=5000,
    )
    assert "cached" not in content.lower()
    assert "2000 in / 300 out" in content
    assert "Tasks: 0 active" in content


def test_status_zero_cache_read_tokens():
    content = status_text(
        version="0.1.0",
        model="glm-4-plus",
        start_time=1000000.0,
        last_usage=LLMUsage.reported(input_tokens=2000, output_tokens=300, cache_read_tokens=0),
        context_window_tokens=128000,
        session_msg_count=10,
        context_tokens=5000,
    )
    assert "cached" not in content.lower()


def test_status_100_percent_cached():
    content = status_text(
        version="0.1.0",
        model="glm-4-plus",
        start_time=1000000.0,
        last_usage=LLMUsage.reported(input_tokens=1000, output_tokens=100, cache_read_tokens=1000),
        context_window_tokens=128000,
        session_msg_count=5,
        context_tokens=3000,
    )
    assert "100% cached" in content


def test_status_context_pct_rounds_half_up_against_full_window():
    content = status_text(
        version="0.1.0",
        model="test",
        start_time=1000000.0,
        last_usage=LLMUsage.reported(input_tokens=2000, output_tokens=300),
        context_window_tokens=128000,
        session_msg_count=10,
        context_tokens=16000,
    )
    assert "(≈13%)" in content


def test_status_context_pct_capped_at_100():
    content = status_text(
        version="0.1.0",
        model="test",
        start_time=1000000.0,
        last_usage=LLMUsage.reported(input_tokens=2000, output_tokens=300),
        context_window_tokens=10000,
        session_msg_count=10,
        context_tokens=100000,
    )
    assert "(≈100%)" in content


def test_status_context_unavailable_without_recorded_request():
    content = status_text(
        version="0.1.0",
        model="test",
        start_time=1000000.0,
        last_usage=None,
        context_window_tokens=128000,
        session_msg_count=0,
        context_tokens=None,
    )
    assert "📚 Context: unavailable" in content.splitlines()
