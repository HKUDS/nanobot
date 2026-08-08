from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from nanobot.agent.hook import AgentHookContext
from nanobot.providers.base import ToolCallRequest
from nanobot.webui.token_usage import (
    TokenUsageHook,
    record_response_token_usage,
    record_token_usage,
    token_usage_payload,
)


def _write_state(tmp_path, days: dict, *, recent_calls: list[dict] | None = None) -> None:
    state_dir = tmp_path / "webui"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "token-usage.json").write_text(
        json.dumps({"days": days, "recent_calls": recent_calls or []}), encoding="utf-8"
    )


def test_payload_tolerates_malformed_persisted_day_keys(tmp_path, monkeypatch) -> None:
    """Day keys that are not real dates must not break settings payloads.

    normalize_token_usage_state only length-checks day keys, so a hand-edited
    10-char key survives reads and atomic rewrites; token_usage_payload then
    parsed it with an unguarded fromisoformat, failing every /api/settings and
    /api/settings/usage request until the file was fixed by hand.
    """
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")
    _write_state(tmp_path, {
        "not-a-dat3": {"total_tokens": 7, "requests": 1},
        "2026-13-01": {"total_tokens": 9, "requests": 1},
        "2026-06-02": {"total_tokens": 5, "requests": 1},
    })

    payload = token_usage_payload(
        timezone_name="UTC",
        now=datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc),
    )

    assert payload["total_tokens"] == 5
    assert payload["total_tokens_30d"] == 5
    assert payload["requests_30d"] == 1
    assert payload["active_days_30d"] == 1


def test_record_scrubs_malformed_day_keys(tmp_path, monkeypatch) -> None:
    """Rewrites drop malformed day keys instead of persisting them forever."""
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")
    _write_state(tmp_path, {
        "not-a-dat3": {"total_tokens": 7, "requests": 1},
        "2026-06-02": {"total_tokens": 5, "requests": 1},
    })

    record_token_usage(
        {"prompt_tokens": 1, "completion_tokens": 1},
        timezone_name="UTC",
        now=datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc),
    )

    raw = json.loads((tmp_path / "webui" / "token-usage.json").read_text(encoding="utf-8"))
    assert "not-a-dat3" not in raw["days"]
    assert "2026-06-02" in raw["days"]
    assert "2026-06-03" in raw["days"]


def test_payload_canonicalizes_python_only_iso_timestamps(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")
    _write_state(
        tmp_path,
        {},
        recent_calls=[{
            "timestamp": "2021-W01-1",
            "source": "user",
            "prompt_tokens": 10,
            "completion_tokens": 5,
        }],
    )

    payload = token_usage_payload(now=datetime(2026, 6, 3, tzinfo=timezone.utc))

    assert payload["recent_calls"][0]["timestamp"] == "2021-01-04T00:00:00Z"


def test_record_token_usage_aggregates_by_local_day(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")

    record_token_usage(
        {"prompt_tokens": 100, "completion_tokens": 40, "cached_tokens": 20},
        timezone_name="Asia/Shanghai",
        now=datetime(2026, 6, 2, 18, 0, tzinfo=timezone.utc),
    )
    record_token_usage(
        {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        timezone_name="Asia/Shanghai",
        now=datetime(2026, 6, 2, 19, 0, tzinfo=timezone.utc),
    )

    payload = token_usage_payload(
        timezone_name="Asia/Shanghai",
        now=datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc),
    )

    assert payload["total_tokens_30d"] == 155
    assert payload["active_days_30d"] == 1
    assert payload["requests_30d"] == 2
    assert payload["days"] == [
        {
            "date": "2026-06-03",
            "prompt_tokens": 110,
            "completion_tokens": 45,
            "cached_tokens": 20,
            "total_tokens": 155,
            "provider_tokens": 155,
            "estimated_tokens": 0,
            "requests": 2,
            "provider_requests": 2,
            "estimated_requests": 0,
            "sources": {
                "user": {
                    "prompt_tokens": 110,
                    "completion_tokens": 45,
                    "cached_tokens": 20,
                    "total_tokens": 155,
                    "provider_tokens": 155,
                    "estimated_tokens": 0,
                    "requests": 2,
                    "provider_requests": 2,
                    "estimated_requests": 0,
                }
            },
        }
    ]


def test_record_token_usage_skips_empty_usage(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")

    record_token_usage({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})

    payload = token_usage_payload(now=datetime(2026, 6, 3, tzinfo=timezone.utc))
    assert payload["days"] == []
    assert payload["total_tokens_30d"] == 0


def test_record_token_usage_keeps_estimated_split(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")

    record_token_usage(
        {"prompt_tokens": 100, "completion_tokens": 25, "estimated_tokens": 125},
        now=datetime(2026, 6, 3, tzinfo=timezone.utc),
    )

    payload = token_usage_payload(now=datetime(2026, 6, 3, tzinfo=timezone.utc))

    assert payload["days"][0]["total_tokens"] == 125
    assert payload["days"][0]["provider_tokens"] == 0
    assert payload["days"][0]["estimated_tokens"] == 125
    assert payload["days"][0]["estimated_requests"] == 1


def test_record_token_usage_keeps_source_breakdown(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")

    record_token_usage(
        {"prompt_tokens": 100, "completion_tokens": 25},
        source="user",
        now=datetime(2026, 6, 3, tzinfo=timezone.utc),
    )
    record_token_usage(
        {"prompt_tokens": 20, "completion_tokens": 5},
        source="dream",
        now=datetime(2026, 6, 3, tzinfo=timezone.utc),
    )

    payload = token_usage_payload(now=datetime(2026, 6, 3, tzinfo=timezone.utc))
    row = payload["days"][0]

    assert row["total_tokens"] == 150
    assert row["sources"]["user"]["total_tokens"] == 125
    assert row["sources"]["user"]["requests"] == 1
    assert row["sources"]["dream"]["total_tokens"] == 25
    assert row["sources"]["dream"]["requests"] == 1


def test_record_token_usage_keeps_recent_call_details(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")

    record_token_usage(
        {"prompt_tokens": 100, "completion_tokens": 25, "cached_tokens": 40},
        source="cron",
        now=datetime(2026, 6, 3, 12, 30, tzinfo=timezone.utc),
        session_key="cron:drink-water",
        iteration=1,
        tools=["read_file", "message"],
    )

    payload = token_usage_payload(now=datetime(2026, 6, 3, 13, 0, tzinfo=timezone.utc))

    assert payload["recent_calls"] == [
        {
            "timestamp": "2026-06-03T12:30:00Z",
            "source": "cron",
            "prompt_tokens": 100,
            "completion_tokens": 25,
            "cached_tokens": 40,
            "total_tokens": 125,
            "provider_tokens": 125,
            "estimated_tokens": 0,
            "session_key": "cron:drink-water",
            "iteration": 1,
            "tools": ["read_file", "message"],
        }
    ]


def test_record_token_usage_bounds_recent_calls(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")
    monkeypatch.setattr("nanobot.webui.token_usage._MAX_RECENT_CALLS", 2)

    for second in range(3):
        record_token_usage(
            {"prompt_tokens": second + 1, "completion_tokens": 1},
            now=datetime(2026, 6, 3, 12, 0, second, tzinfo=timezone.utc),
            session_key=f"webui:{second}",
        )

    payload = token_usage_payload(now=datetime(2026, 6, 3, 13, 0, tzinfo=timezone.utc))

    assert [call["session_key"] for call in payload["recent_calls"]] == ["webui:2", "webui:1"]


def test_record_response_token_usage_uses_response_usage(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")
    monkeypatch.setattr("nanobot.webui.token_usage._local_day", lambda *_, **__: "2026-06-03")

    record_response_token_usage(
        SimpleNamespace(usage={"prompt_tokens": 20, "completion_tokens": 5}),
        source="dream",
        session_key="dream:20260603-120000",
    )

    payload = token_usage_payload(now=datetime(2026, 6, 3, tzinfo=timezone.utc))
    assert payload["days"][0]["sources"]["dream"]["total_tokens"] == 25
    assert payload["recent_calls"][0]["session_key"] == "dream:20260603-120000"


@pytest.mark.asyncio
async def test_token_usage_hook_classifies_source_from_session_key(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")
    monkeypatch.setattr("nanobot.webui.token_usage._local_day", lambda *_, **__: "2026-06-03")

    hook = TokenUsageHook()
    await hook.after_iteration(
        AgentHookContext(
            iteration=0,
            messages=[],
            session_key="cron:drink-water",
            usage={"prompt_tokens": 10, "completion_tokens": 5},
            tool_calls=[ToolCallRequest(id="call-1", name="read_file", arguments={})],
        )
    )

    payload = token_usage_payload(now=datetime(2026, 6, 3, tzinfo=timezone.utc))

    assert payload["days"][0]["sources"]["cron"]["total_tokens"] == 15
    assert payload["recent_calls"][0]["session_key"] == "cron:drink-water"
    assert payload["recent_calls"][0]["iteration"] == 0
    assert payload["recent_calls"][0]["tools"] == ["read_file"]
