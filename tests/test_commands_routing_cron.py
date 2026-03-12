from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nanobot.cli.commands import app
from nanobot.config.schema import Config

runner = CliRunner()


def test_routing_trace_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = Config()
    cfg.agents.defaults.workspace = str(tmp_path)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda: cfg)

    missing = runner.invoke(app, ["routing", "trace"])
    assert missing.exit_code == 0
    assert "No routing trace" in missing.stdout

    trace_path = tmp_path / "memory" / "routing_trace.jsonl"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text("\n", encoding="utf-8")
    empty = runner.invoke(app, ["routing", "trace"])
    assert empty.exit_code == 0
    assert "Trace file is empty" in empty.stdout

    trace_path.write_text(
        "not-json\n"
        + json.dumps(
            {
                "timestamp": "2026-03-11T00:00:00",
                "event": "classify",
                "role": "general",
                "confidence": 0.9,
                "success": True,
                "message": "hi",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    ok = runner.invoke(app, ["routing", "trace", "--last", "5"])
    assert ok.exit_code == 0
    assert "Routing Trace" in ok.stdout


def test_routing_metrics_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = Config()
    cfg.agents.defaults.workspace = str(tmp_path)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda: cfg)

    missing = runner.invoke(app, ["routing", "metrics"])
    assert missing.exit_code == 0
    assert "No routing metrics" in missing.stdout

    metrics_path = tmp_path / "memory" / "routing_metrics.json"
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text("bad-json", encoding="utf-8")
    bad = runner.invoke(app, ["routing", "metrics"])
    assert bad.exit_code == 1
    assert "Failed to read metrics" in bad.stdout

    metrics_path.write_text(
        json.dumps(
            {
                "routing_classifications": 2,
                "routing_delegations": 1,
                "routing_cycles_blocked": 0,
                "routing_classify_latency_sum_ms": 30,
                "routing_classify_latency_max_ms": 20,
                "delegation_latency_sum_ms": 50,
                "delegation_latency_max_ms": 50,
                "role_invocations:general": 2,
                "role_tool_calls:general": 3,
            }
        ),
        encoding="utf-8",
    )
    ok = runner.invoke(app, ["routing", "metrics"])
    assert ok.exit_code == 0
    assert "Routing Metrics" in ok.stdout
    assert "Per-Role Stats" in ok.stdout


def test_cron_run_success_and_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = Config()
    cfg.agents.defaults.workspace = str(tmp_path)

    monkeypatch.setattr("nanobot.config.loader.load_config", lambda: cfg)
    monkeypatch.setattr("nanobot.config.loader.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _cfg: object())

    class _Bus:
        pass

    class _AgentLoop:
        def __init__(self, **kwargs):
            pass

        async def process_direct(self, *args, **kwargs):
            return "cron-response"

    class _Payload:
        message = "job"
        channel = "cli"
        to = "direct"

    class _Job:
        id = "j1"
        payload = _Payload()

    class _CronService:
        should_run = True

        def __init__(self, _path: Path):
            self.on_job = None

        async def run_job(self, _job_id: str, force: bool = False):
            if self.should_run and self.on_job is not None:
                await self.on_job(_Job())
            return self.should_run

    monkeypatch.setattr("nanobot.bus.queue.MessageBus", _Bus)
    monkeypatch.setattr("nanobot.agent.loop.AgentLoop", _AgentLoop)
    monkeypatch.setattr("nanobot.cron.service.CronService", _CronService)

    ok = runner.invoke(app, ["cron", "run", "job-1", "--force"])
    assert ok.exit_code == 0
    assert "Job executed" in ok.stdout

    _CronService.should_run = False
    fail = runner.invoke(app, ["cron", "run", "job-1"])
    assert fail.exit_code == 0
    assert "Failed to run job" in fail.stdout
