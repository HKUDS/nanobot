from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from nanobot.agent.hook import AgentHookContext
from nanobot.providers.base import LLMUsage
from nanobot.webui.token_usage import (
    TokenUsageHook,
    read_token_usage_state,
    record_response_token_usage,
    record_token_usage,
    token_usage_payload,
    write_token_usage_state,
)


def _write_state(tmp_path, days: dict) -> None:
    state_dir = tmp_path / "webui"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "token-usage.json").write_text(
        json.dumps({"schema_version": 2, "days": days}), encoding="utf-8"
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
        LLMUsage.reported(input_tokens=1, output_tokens=1),
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
        LLMUsage.reported(
            input_tokens=100,
            output_tokens=40,
            cache_read_tokens=20,
        ),
        timezone_name="Asia/Shanghai",
        now=datetime(2026, 6, 2, 18, 0, tzinfo=timezone.utc),
    )
    record_token_usage(
        LLMUsage.reported(input_tokens=10, output_tokens=5),
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
            "input_tokens": 110,
            "output_tokens": 45,
            "cache_read_tokens": 20,
            "cache_write_tokens": 0,
            "cache_read_observed_input_tokens": 100,
            "cache_write_observed_input_tokens": 0,
            "total_tokens": 155,
            "reported_tokens": 155,
            "estimated_tokens": 0,
            "requests": 2,
            "reported_requests": 2,
            "estimated_requests": 0,
            "sources": {
                "user": {
                    "input_tokens": 110,
                    "output_tokens": 45,
                    "cache_read_tokens": 20,
                    "cache_write_tokens": 0,
                    "cache_read_observed_input_tokens": 100,
                    "cache_write_observed_input_tokens": 0,
                    "total_tokens": 155,
                    "reported_tokens": 155,
                    "estimated_tokens": 0,
                    "requests": 2,
                    "reported_requests": 2,
                    "estimated_requests": 0,
                }
            },
        }
    ]


def test_cache_observation_denominators_distinguish_missing_from_zero(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")
    now = datetime(2026, 6, 3, tzinfo=timezone.utc)

    record_token_usage(
        LLMUsage.reported(input_tokens=100, output_tokens=10),
        source="user",
        now=now,
    )
    record_token_usage(
        LLMUsage.reported(
            input_tokens=40,
            output_tokens=5,
            cache_read_tokens=0,
            cache_write_tokens=0,
        ),
        source="dream",
        now=now,
    )

    row = token_usage_payload(now=now)["days"][0]

    assert row["cache_read_tokens"] == 0
    assert row["cache_write_tokens"] == 0
    assert row["cache_read_observed_input_tokens"] == 40
    assert row["cache_write_observed_input_tokens"] == 40
    assert row["sources"]["user"]["cache_read_observed_input_tokens"] == 0
    assert row["sources"]["user"]["cache_write_observed_input_tokens"] == 0
    assert row["sources"]["dream"]["cache_read_observed_input_tokens"] == 40
    assert row["sources"]["dream"]["cache_write_observed_input_tokens"] == 40


def _retention_state(sources: tuple[str, ...], *, day_count: int = 400) -> dict:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    source_usage = {
        "input_tokens": 100,
        "output_tokens": 10,
        "total_tokens": 110,
        "reported_tokens": 110,
        "requests": 1,
        "reported_requests": 1,
    }
    days = {}
    for offset in range(day_count):
        day = (start + timedelta(days=offset)).date().isoformat()
        days[day] = {
            "input_tokens": 100 * len(sources),
            "output_tokens": 10 * len(sources),
            "total_tokens": 110 * len(sources),
            "reported_tokens": 110 * len(sources),
            "requests": len(sources),
            "reported_requests": len(sources),
            "sources": {source: dict(source_usage) for source in sources},
        }
    return {"schema_version": 2, "days": days}


def test_write_compact_state_keeps_400_days_with_two_sources(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")

    written = write_token_usage_state(_retention_state(("user", "api")))
    persisted = (tmp_path / "webui" / "token-usage.json").read_bytes()

    assert len(written["days"]) == 400
    assert len(persisted) <= 512 * 1024
    assert persisted.endswith(b"\n")
    assert json.loads(persisted) == written


def test_write_prunes_only_oldest_days_to_fit_byte_budget(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")
    sources = ("user", "api", "cron", "dream", "system")
    raw = _retention_state(sources)
    all_dates = list(raw["days"])

    written = write_token_usage_state(raw)
    retained_dates = list(written["days"])
    persisted = (tmp_path / "webui" / "token-usage.json").read_bytes()

    assert 1 <= len(retained_dates) < len(all_dates)
    assert retained_dates == all_dates[-len(retained_dates) :]
    assert retained_dates[-1] == all_dates[-1]
    assert all(set(row["sources"]) == set(sources) for row in written["days"].values())
    assert len(persisted) <= 512 * 1024
    assert read_token_usage_state() == written


def test_write_raises_when_latest_day_alone_exceeds_byte_budget(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")
    monkeypatch.setattr("nanobot.webui.token_usage._MAX_STATE_FILE_BYTES", 256)

    with pytest.raises(ValueError, match="latest token usage day exceeds"):
        write_token_usage_state(_retention_state(("user", "api"), day_count=1))

    assert not (tmp_path / "webui" / "token-usage.json").exists()


def test_record_token_usage_skips_empty_usage(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")

    record_token_usage(LLMUsage.reported(input_tokens=0, output_tokens=0))

    payload = token_usage_payload(now=datetime(2026, 6, 3, tzinfo=timezone.utc))
    assert payload["days"] == []
    assert payload["total_tokens_30d"] == 0


def test_record_token_usage_keeps_estimated_split(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")

    record_token_usage(
        LLMUsage.estimated(input_tokens=100, output_tokens=25),
        now=datetime(2026, 6, 3, tzinfo=timezone.utc),
    )

    payload = token_usage_payload(now=datetime(2026, 6, 3, tzinfo=timezone.utc))

    assert payload["days"][0]["total_tokens"] == 125
    assert payload["days"][0]["reported_tokens"] == 0
    assert payload["days"][0]["estimated_tokens"] == 125
    assert payload["days"][0]["estimated_requests"] == 1


def test_record_token_usage_keeps_source_breakdown(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")

    record_token_usage(
        LLMUsage.reported(input_tokens=100, output_tokens=25, total_tokens=175),
        source="user",
        now=datetime(2026, 6, 3, tzinfo=timezone.utc),
    )
    record_token_usage(
        LLMUsage.reported(input_tokens=20, output_tokens=5),
        source="dream",
        now=datetime(2026, 6, 3, tzinfo=timezone.utc),
    )

    payload = token_usage_payload(now=datetime(2026, 6, 3, tzinfo=timezone.utc))
    row = payload["days"][0]

    assert row["total_tokens"] == 200
    assert row["sources"]["user"]["total_tokens"] == 175
    assert row["sources"]["user"]["requests"] == 1
    assert row["sources"]["dream"]["total_tokens"] == 25
    assert row["sources"]["dream"]["requests"] == 1


def test_record_response_token_usage_uses_response_usage(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.webui.token_usage.get_webui_dir", lambda: tmp_path / "webui")
    monkeypatch.setattr("nanobot.webui.token_usage._local_day", lambda *_, **__: "2026-06-03")

    record_response_token_usage(
        SimpleNamespace(usage=LLMUsage.reported(input_tokens=20, output_tokens=5)),
        source="dream",
    )

    payload = token_usage_payload(now=datetime(2026, 6, 3, tzinfo=timezone.utc))
    assert payload["days"][0]["sources"]["dream"]["total_tokens"] == 25


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
            usage=LLMUsage.reported(input_tokens=10, output_tokens=5),
        )
    )

    payload = token_usage_payload(now=datetime(2026, 6, 3, tzinfo=timezone.utc))

    assert payload["days"][0]["sources"]["cron"]["total_tokens"] == 15
