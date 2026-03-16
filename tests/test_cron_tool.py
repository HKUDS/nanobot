"""Tests for nanobot.agent.tools.cron — CronTool."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nanobot.agent.tools.cron import CronTool


@pytest.fixture()
def cron_tool() -> CronTool:
    svc = MagicMock()
    tool = CronTool(cron_service=svc)
    tool.set_context(channel="test", chat_id="123")
    return tool


class TestCronToolProperties:
    def test_name(self, cron_tool: CronTool):
        assert cron_tool.name == "cron"

    def test_description(self, cron_tool: CronTool):
        assert "schedule" in cron_tool.description.lower()

    def test_parameters(self, cron_tool: CronTool):
        params = cron_tool.parameters
        assert "action" in params["properties"]


class TestCronToolExecute:
    async def test_unknown_action(self, cron_tool: CronTool):
        result = await cron_tool.execute(action="unknown")
        assert not result.success

    async def test_add_missing_message(self, cron_tool: CronTool):
        result = await cron_tool.execute(action="add")
        assert not result.success
        assert "message" in result.output.lower()

    async def test_add_no_context(self):
        svc = MagicMock()
        tool = CronTool(cron_service=svc)
        # No set_context called
        result = await tool.execute(action="add", message="hi")
        assert not result.success
        assert "context" in result.output.lower()

    async def test_add_with_every_seconds(self, cron_tool: CronTool):
        mock_job = MagicMock(name="test", id="j1")
        mock_job.name = "test"
        cron_tool._cron.add_job.return_value = mock_job
        result = await cron_tool.execute(action="add", message="remind me", every_seconds=60)
        assert result.success
        assert "j1" in result.output

    async def test_add_with_cron_expr(self, cron_tool: CronTool):
        mock_job = MagicMock(id="j2")
        mock_job.name = "daily"
        cron_tool._cron.add_job.return_value = mock_job
        result = await cron_tool.execute(action="add", message="daily task", cron_expr="0 9 * * *")
        assert result.success

    async def test_add_with_at(self, cron_tool: CronTool):
        mock_job = MagicMock(id="j3")
        mock_job.name = "once"
        cron_tool._cron.add_job.return_value = mock_job
        result = await cron_tool.execute(action="add", message="one-time", at="2026-12-25T10:00:00")
        assert result.success

    async def test_add_no_schedule_fails(self, cron_tool: CronTool):
        result = await cron_tool.execute(action="add", message="no sched")
        assert not result.success
        assert "required" in result.output.lower()

    async def test_add_tz_without_cron_fails(self, cron_tool: CronTool):
        result = await cron_tool.execute(
            action="add", message="tz test", every_seconds=60, tz="America/Vancouver"
        )
        assert not result.success
        assert "tz" in result.output.lower()

    async def test_add_invalid_tz(self, cron_tool: CronTool):
        result = await cron_tool.execute(
            action="add", message="bad tz", cron_expr="0 9 * * *", tz="Invalid/Zone"
        )
        assert not result.success
        assert "timezone" in result.output.lower()

    async def test_list_empty(self, cron_tool: CronTool):
        cron_tool._cron.list_jobs.return_value = []
        result = await cron_tool.execute(action="list")
        assert result.success
        assert "no" in result.output.lower()

    async def test_list_with_jobs(self, cron_tool: CronTool):
        job = MagicMock(id="j1")
        job.name = "reminder"
        job.schedule.kind = "every"
        cron_tool._cron.list_jobs.return_value = [job]
        result = await cron_tool.execute(action="list")
        assert result.success
        assert "reminder" in result.output

    async def test_remove_missing_id(self, cron_tool: CronTool):
        result = await cron_tool.execute(action="remove")
        assert not result.success
        assert "job_id" in result.output.lower()

    async def test_remove_success(self, cron_tool: CronTool):
        cron_tool._cron.remove_job.return_value = True
        result = await cron_tool.execute(action="remove", job_id="j1")
        assert result.success


# ---------------------------------------------------------------------------
# Integration-style tests with a fake in-memory cron service
# ---------------------------------------------------------------------------


class _FakeCron:
    def __init__(self) -> None:
        self.jobs: dict[str, SimpleNamespace] = {}

    def add_job(self, **kwargs):
        job = SimpleNamespace(id="job-1", name=kwargs["name"], schedule=kwargs["schedule"])
        self.jobs[job.id] = job
        return job

    def list_jobs(self):
        return list(self.jobs.values())

    def remove_job(self, job_id: str) -> bool:
        return self.jobs.pop(job_id, None) is not None


def test_cron_tool_invalid_and_remove_paths() -> None:
    tool = CronTool(_FakeCron())

    bad_msg = tool._add_job(message="", every_seconds=1, cron_expr=None, tz=None, at=None)
    assert not bad_msg.success

    tool.set_context("telegram", "123")
    bad_tz = tool._add_job(message="hello", every_seconds=None, cron_expr=None, tz="UTC", at=None)
    assert not bad_tz.success

    missing_schedule = tool._add_job(
        message="hello", every_seconds=None, cron_expr=None, tz=None, at=None
    )
    assert not missing_schedule.success

    assert not tool._remove_job(None).success
    assert not tool._remove_job("missing").success


def test_cron_tool_add_list_remove_success() -> None:
    tool = CronTool(_FakeCron())
    tool.set_context("telegram", "123")

    created = tool._add_job("hello", every_seconds=10, cron_expr=None, tz=None, at=None)
    assert created.success

    listed = tool._list_jobs()
    assert listed.success
    assert "Scheduled jobs" in listed.output

    removed = tool._remove_job("job-1")
    assert removed.success


@pytest.mark.asyncio
async def test_cron_tool_execute_dispatch() -> None:
    tool = CronTool(_FakeCron())
    tool.set_context("telegram", "123")

    out = await tool.execute(action="add", message="ping", every_seconds=1)
    assert out.success

    listed = await tool.execute(action="list")
    assert listed.success

    rm = await tool.execute(action="remove", job_id="job-1")
    assert rm.success

    unknown = await tool.execute(action="wat")
    assert not unknown.success
