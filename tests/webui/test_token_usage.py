from __future__ import annotations

from datetime import datetime, timezone

from nanobot.webui.token_usage import (
    record_token_usage,
    token_usage_payload,
)


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
