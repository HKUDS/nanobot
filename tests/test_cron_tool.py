from nanobot.agent.tools.cron import CronTool
from nanobot.cron.types import CronJob, CronJobState, CronPayload, CronSchedule


class _StubCronService:
    def __init__(self, jobs):
        self._jobs = jobs

    def list_jobs(self):
        return self._jobs


def test_list_jobs_returns_empty_message() -> None:
    tool = CronTool(_StubCronService([]))

    result = tool._list_jobs()

    assert result == "No scheduled jobs."


def test_list_jobs_includes_cron_expr_tz_and_next_run() -> None:
    job = CronJob(
        id="job-cron-1",
        name="daily reminder",
        schedule=CronSchedule(kind="cron", expr="0 9 * * *", tz="America/Vancouver"),
        payload=CronPayload(message="remind me"),
        state=CronJobState(next_run_at_ms=1762467600000),
    )
    tool = CronTool(_StubCronService([job]))

    result = tool._list_jobs()

    assert "id: job-cron-1" in result
    assert "kind: cron" in result
    assert "expr: 0 9 * * *" in result
    assert "tz: America/Vancouver" in result
    assert "next_run_at_ms: 1762467600000" in result


def test_list_jobs_includes_every_and_at_schedule_fields() -> None:
    every_job = CronJob(
        id="job-every-1",
        name="poll",
        schedule=CronSchedule(kind="every", every_ms=30000),
        payload=CronPayload(message="poll status"),
        state=CronJobState(next_run_at_ms=1762467605000),
    )
    at_job = CronJob(
        id="job-at-1",
        name="one-shot",
        schedule=CronSchedule(kind="at", at_ms=1762467600000),
        payload=CronPayload(message="run once"),
        state=CronJobState(next_run_at_ms=1762467600000),
    )
    tool = CronTool(_StubCronService([every_job, at_job]))

    result = tool._list_jobs()

    assert "id: job-every-1" in result
    assert "kind: every" in result
    assert "every_ms: 30000" in result
    assert "id: job-at-1" in result
    assert "kind: at" in result
    assert "at_ms: 1762467600000" in result
