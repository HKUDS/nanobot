"""Tests for GEPA slash commands: /evolve-run, /evolve-status (E4-G2)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nanobot.agent.evolution.gepa_runner import GepaRunResult
from nanobot.agent.evolution.gepa_status import GepaRunStatus, GepaRunStore, gepa_run_in_progress
from nanobot.bus.events import InboundMessage
from nanobot.command.evolve import (
    cmd_evolve_run,
    cmd_evolve_status,
    format_gepa_completion_message,
    format_gepa_run_status,
    resolve_gepa_notify_delivery,
)
from nanobot.command.router import CommandContext
from nanobot.config.schema import EvolutionConfig, EvolutionGepaConfig


def _make_loop_with_evolution(
    tmp_path: Path,
    *,
    gepa_enabled: bool = True,
    schedule: MagicMock | None = None,
) -> SimpleNamespace:
    evolution = EvolutionConfig(
        enable=True,
        gepa=EvolutionGepaConfig(enable=gepa_enabled),
    )
    return SimpleNamespace(
        context=SimpleNamespace(workspace=tmp_path, warm_skill_index=MagicMock()),
        _evolution=evolution,
        _schedule_gepa_run=schedule or MagicMock(),
    )


def _make_ctx(tmp_path: Path, raw: str, *, args: str = "", loop: SimpleNamespace) -> CommandContext:
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content=raw)
    return CommandContext(
        msg=msg,
        session=None,
        key=msg.session_key,
        raw=raw,
        args=args,
        loop=loop,
    )


@pytest.mark.asyncio
async def test_evolve_run_schedules_background(tmp_path: Path) -> None:
    schedule = MagicMock()
    loop = _make_loop_with_evolution(tmp_path, schedule=schedule)
    ctx = _make_ctx(
        tmp_path,
        "/evolve-run",
        args="deploy-k8s",
        loop=loop,
    )

    out = await cmd_evolve_run(ctx)

    schedule.assert_called_once_with(
        skill_name="deploy-k8s",
        trigger="slash",
        notify_to=("cli", "direct"),
    )
    assert "GEPA run started" in out.content


@pytest.mark.asyncio
async def test_evolve_run_rejects_when_disabled(tmp_path: Path) -> None:
    loop = _make_loop_with_evolution(tmp_path, gepa_enabled=False)
    ctx = _make_ctx(tmp_path, "/evolve-run", loop=loop)

    out = await cmd_evolve_run(ctx)

    assert "disabled" in out.content.lower()


@pytest.mark.asyncio
async def test_evolve_run_rejects_when_already_running(tmp_path: Path) -> None:
    loop = _make_loop_with_evolution(tmp_path)
    GepaRunStore(tmp_path).save(
        GepaRunStatus(run_id="run-1", phase="optimizing", started_at="2026-05-24T00:00:00Z"),
    )
    ctx = _make_ctx(tmp_path, "/evolve-run", loop=loop)

    out = await cmd_evolve_run(ctx)

    assert "already running" in out.content.lower()
    loop._schedule_gepa_run.assert_not_called()


def test_gepa_run_in_progress_detects_active_phases() -> None:
    assert gepa_run_in_progress(GepaRunStatus(phase="optimizing")) is True
    assert gepa_run_in_progress(GepaRunStatus(phase="completed")) is False
    assert gepa_run_in_progress(GepaRunStatus.idle()) is False


def test_format_gepa_completion_message_empty() -> None:
    assert format_gepa_completion_message(GepaRunResult()) is None


def test_format_gepa_completion_message_lists_proposals() -> None:
    text = format_gepa_completion_message(
        GepaRunResult(proposals_created=("abcdef12-3456-7890", "fedcba98-7654")),
    )

    assert "2 GEPA proposals ready" in text
    assert "abcdef12" in text
    assert "fedcba98" in text
    assert "/evolve-show" in text


def test_resolve_gepa_notify_slash_with_proposals() -> None:
    evolution = EvolutionConfig(enable=True, gepa=EvolutionGepaConfig(enable=True))
    result = GepaRunResult(proposals_created=("proposal-1",))

    delivery = resolve_gepa_notify_delivery(
        result=result,
        trigger="slash",
        evolution=evolution,
        notify_to=("telegram", "chat-42"),
    )

    assert delivery == ("telegram", "chat-42")


def test_resolve_gepa_notify_slash_skips_without_proposals() -> None:
    evolution = EvolutionConfig(enable=True, gepa=EvolutionGepaConfig(enable=True))

    assert (
        resolve_gepa_notify_delivery(
            result=GepaRunResult(),
            trigger="slash",
            evolution=evolution,
            notify_to=("cli", "direct"),
        )
        is None
    )


def test_resolve_gepa_notify_cron_when_configured() -> None:
    evolution = EvolutionConfig(
        enable=True,
        gepa=EvolutionGepaConfig(
            enable=True,
            notify_on_complete=True,
            notify_channel="telegram",
            notify_chat_id="user-1",
        ),
    )
    result = GepaRunResult(proposals_created=("proposal-1",))

    delivery = resolve_gepa_notify_delivery(
        result=result,
        trigger="cron",
        evolution=evolution,
    )

    assert delivery == ("telegram", "user-1")


def test_resolve_gepa_notify_cron_off_by_default() -> None:
    evolution = EvolutionConfig(enable=True, gepa=EvolutionGepaConfig(enable=True))
    result = GepaRunResult(proposals_created=("proposal-1",))

    assert (
        resolve_gepa_notify_delivery(
            result=result,
            trigger="cron",
            evolution=evolution,
        )
        is None
    )


def test_resolve_gepa_notify_cli_never_notifies() -> None:
    evolution = EvolutionConfig(enable=True, gepa=EvolutionGepaConfig(enable=True))
    result = GepaRunResult(proposals_created=("proposal-1",))

    assert (
        resolve_gepa_notify_delivery(
            result=result,
            trigger="cli",
            evolution=evolution,
            notify_to=("cli", "direct"),
        )
        is None
    )


def test_format_gepa_run_status_idle() -> None:
    assert "idle" in format_gepa_run_status(GepaRunStatus.idle()).lower()


def test_format_gepa_run_status_completed() -> None:
    status = GepaRunStatus(
        run_id="abcdef12-3456",
        phase="completed",
        trigger="slash",
        skill_name="deploy-k8s",
        started_at="2026-05-24T00:00:00Z",
        finished_at="2026-05-24T00:05:00Z",
        proposals_created=("proposal-1",),
        budget_usd_spent=1.25,
        message="done",
    )

    text = format_gepa_run_status(status)

    assert "completed" in text
    assert "deploy-k8s" in text
    assert "proposal-1"[:8] in text
    assert "/evolve-show" in text


@pytest.mark.asyncio
async def test_evolve_status_reads_store(tmp_path: Path) -> None:
    GepaRunStore(tmp_path).save(
        GepaRunStatus(run_id="run-xyz", phase="failed", error="boom"),
    )
    loop = _make_loop_with_evolution(tmp_path)
    ctx = _make_ctx(tmp_path, "/evolve-status", loop=loop)

    out = await cmd_evolve_status(ctx)

    assert "failed" in out.content
    assert "boom" in out.content
