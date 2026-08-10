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
    token_usage_records_payload,
)


def _write_state(tmp_path, days: dict, *, records: list[dict] | None = None) -> None:
    state_dir = tmp_path / "webui"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "token-usage.json").write_text(
        json.dumps({"days": days, "records": records or []}), encoding="utf-8"
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


def test_record_token_usage_keeps_bounded_diagnostic_record(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")

    record_token_usage(
        {"prompt_tokens": 100, "completion_tokens": 25, "cached_tokens": 40},
        source="cron",
        now=datetime(2026, 6, 3, 12, 30, tzinfo=timezone.utc),
        session_key="cron:drink-water",
        iteration=1,
        requested_tools=["read_file", "message"],
    )

    payload = token_usage_records_payload()
    updated_at = payload.pop("updated_at")

    assert isinstance(updated_at, str)
    assert payload == {
        "records": [
            {
                "timestamp": "2026-06-03T12:30:00Z",
                "day": "2026-06-03",
                "source": "cron",
                "session_key": "cron:drink-water",
                "iteration": 1,
                "requested_tools": ["read_file", "message"],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 25,
                    "cached_tokens": 40,
                    "total_tokens": 125,
                    "provider_tokens": 125,
                    "estimated_tokens": 0,
                },
            }
        ],
        "day": None,
        "recorded_requests": 1,
        "retention_limit": 50,
        "truncated": False,
    }


def test_usage_records_report_partial_retention_for_selected_day(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")
    monkeypatch.setattr("nanobot.webui.token_usage._MAX_USAGE_RECORDS", 2)

    for hour in range(3):
        record_token_usage(
            {"prompt_tokens": hour + 1, "completion_tokens": 1},
            now=datetime(2026, 6, 3, hour, tzinfo=timezone.utc),
            session_key=f"webui:{hour}",
        )

    payload = token_usage_records_payload(day="2026-06-03")

    assert [record["session_key"] for record in payload["records"]] == ["webui:2", "webui:1"]
    assert payload["recorded_requests"] == 3
    assert payload["retention_limit"] == 2
    assert payload["truncated"] is True


def test_usage_records_keep_recorded_day_after_timezone_change(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")

    record_token_usage(
        {"prompt_tokens": 100, "completion_tokens": 25},
        timezone_name="Asia/Shanghai",
        now=datetime(2026, 6, 2, 18, 0, tzinfo=timezone.utc),
    )

    payload = token_usage_records_payload(day="2026-06-03")

    assert payload["records"][0]["timestamp"] == "2026-06-02T18:00:00Z"
    assert payload["records"][0]["day"] == "2026-06-03"


@pytest.mark.parametrize("day", ["2026-6-3", "2026-06-03T00:00:00", "not-a-day"])
def test_usage_records_reject_invalid_day_filter(tmp_path, monkeypatch, day) -> None:
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")

    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        token_usage_records_payload(day=day)


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
    assert token_usage_records_payload()["records"][0]["session_key"] == (
        "dream:20260603-120000"
    )


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
    record = token_usage_records_payload()["records"][0]
    assert record["session_key"] == "cron:drink-water"
    assert record["iteration"] == 0
    assert record["requested_tools"] == ["read_file"]
