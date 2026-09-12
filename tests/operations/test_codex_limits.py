from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from nanobot.operations import codex_limits
from nanobot.operations.codex_limits import (
    CodexLimits,
    CodexLimitsConfig,
    limits_report,
    parse_limits,
)


def quota(used: float = 34) -> dict:
    return {"accountId": "account-one", "rateLimitsByLimitId": {
        "codex": {"primary": {"usedPercent": used, "windowDurationMins": 10080, "resetsAt": 2_000_000_000}},
        "special": {"limitName": "Additional model", "primary": None,
                    "secondary": {"usedPercent": 0, "windowDurationMins": 300, "resetsAt": None}},
    }, "rateLimitResetCredits": {"availableCount": 1}, "accessToken": "MUST_NOT_BE_PERSISTED"}


def test_multiple_buckets_unknown_windows_and_account_identity():
    snapshot = parse_limits(quota(), now=1000, gateway_account="another-account")
    assert snapshot.gateway_account_matches is False
    assert snapshot.buckets[0].primary.used_percent == 34
    assert snapshot.buckets[1].primary is None
    assert snapshot.buckets[1].secondary.used_percent == 0
    dumped = snapshot.model_dump_json()
    assert "MUST_NOT_BE_PERSISTED" not in dumped
    assert "account-one" not in dumped
    assert "rateLimitResetCredits" not in dumped
    assert "inne konto" in limits_report(snapshot)


@pytest.mark.parametrize("value", [None, {}, {"rateLimits": {}}, {"rateLimitsByLimitId": {"x": {"primary": {}}}}])
def test_absent_limits_never_become_zero_usage(value):
    with pytest.raises(ValueError):
        parse_limits(value, now=1000, gateway_account=None)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1])
def test_invalid_percentages_rejected(value):
    with pytest.raises(ValueError):
        parse_limits(quota(value), now=1000, gateway_account=None)


async def test_concurrent_reads_coalesce_and_failure_retains_last_observation(tmp_path: Path, monkeypatch):
    import asyncio

    from oauth_cli_kit.storage import FileTokenStorage

    clock = [1000.0]
    monkeypatch.setattr(codex_limits.time, "time", lambda: clock[0])
    monkeypatch.setattr(FileTokenStorage, "load", lambda _: None)
    reader = AsyncMock(return_value=quota())
    monkeypatch.setattr(codex_limits, "read_app_server", reader)
    monitor = CodexLimits(CodexLimitsConfig(enable=True, owner_session_key="telegram:owner"), tmp_path / "limits.json")
    first, second = await asyncio.gather(monitor.snapshot(), monitor.snapshot())
    assert first.state == second.state == "available"
    assert reader.await_count == 1
    clock[0] += 61
    reader.side_effect = TimeoutError
    stale = await monitor.snapshot()
    assert stale.state == "stale"
    assert stale.observed_at == 1000
    assert stale.attempted_at == 1061
    assert stale.buckets[0].primary.used_percent == 34
    assert "MUST_NOT_BE_PERSISTED" not in monitor.path.read_text()


async def test_disabled_monitor_never_starts_app_server(tmp_path: Path, monkeypatch):
    reader = AsyncMock()
    monkeypatch.setattr(codex_limits, "read_app_server", reader)
    snapshot = await CodexLimits(CodexLimitsConfig(), tmp_path / "limits.json").snapshot()
    assert snapshot.state == "disabled"
    reader.assert_not_called()


async def test_documented_read_only_handshake_no_turn_or_login(tmp_path: Path):
    executable = tmp_path / "codex-test"
    executable.write_text("#!/usr/bin/python3\n" + "\n".join([
        "import json,sys",
        "a=json.loads(sys.stdin.readline()); assert a['method']=='initialize'",
        "print(json.dumps({'id':a['id'],'result':{}}),flush=True)",
        "b=json.loads(sys.stdin.readline()); assert b['method']=='initialized'",
        "c=json.loads(sys.stdin.readline()); assert c['method']=='account/rateLimits/read'",
        f"print(json.dumps({{'id':2,'result':{quota()!r}}}),flush=True)",
    ]) + "\n")
    executable.chmod(0o700)
    response = await codex_limits.read_app_server(str(executable))
    assert response == quota()
