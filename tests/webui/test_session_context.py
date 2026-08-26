from nanobot.providers.base import LLMUsage
from nanobot.session import Session
from nanobot.utils.helpers import estimate_message_tokens
from nanobot.webui.session_context import session_context_payload


def test_session_context_separates_archive_progress_from_replay() -> None:
    messages = [
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "recent question"},
        {"role": "assistant", "content": "recent answer"},
    ]
    session = Session(
        key="websocket:context",
        messages=messages,
        last_consolidated=2,
        metadata={
            "_last_summary": {
                "text": "The archived conversation settled the old question.",
                "last_active": "2026-08-13T10:00:00Z",
            }
        },
    )

    replay = session.get_history(max_messages=0, include_runtime_context=False)
    replay_tokens = sum(estimate_message_tokens(message) for message in replay)
    summary_tokens = estimate_message_tokens(
        {"role": "system", "content": "The archived conversation settled the old question."}
    )
    payload = session_context_payload(session)

    assert payload == {
        "schema_version": 1,
        "session_key": "websocket:context",
        "total_messages": 4,
        "archived_messages": 2,
        "replay_messages": len(replay),
        "estimated_replay_tokens": replay_tokens,
        "estimated_summary_tokens": summary_tokens,
        "estimated_session_tokens": replay_tokens + summary_tokens,
        "archived_summary": "The archived conversation settled the old question.",
        "archived_summary_at": "2026-08-13T10:00:00Z",
        "last_usage": None,
    }


def test_session_context_tolerates_untrusted_summary_metadata() -> None:
    session = Session(
        key="websocket:context",
        messages=[{"role": "user", "content": "hello"}],
        metadata={"_last_summary": "invalid"},
    )

    payload = session_context_payload(session)

    assert payload["archived_summary"] is None
    assert payload["archived_summary_at"] is None


def test_session_context_sanitizes_usage_metadata() -> None:
    usage = LLMUsage.reported(
        input_tokens=120,
        output_tokens=8,
        total_tokens=175,
        cache_read_tokens=48,
    ).with_timing(generation_ms=400, ttft_ms=75)
    session = Session(
        key="websocket:context",
        metadata={"_last_usage": usage.to_dict()},
    )

    payload = session_context_payload(session)

    assert payload["last_usage"] == {
        "prompt_tokens": 120,
        "completion_tokens": 8,
        "total_tokens": 175,
        "context_tokens": 120,
        "cached_tokens": 48,
        "request_count": 1,
        "estimated_tokens": 0,
        "generation_ms": 400,
        "measured_completion_tokens": 8,
        "ttft_ms": 75,
        "timed_requests": 1,
    }
