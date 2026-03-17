import asyncio
from pathlib import Path

from nanobot.agent.tools.cron import CronTool, create_scoped_job
from nanobot.cron.service import CronService


def test_cron_tool_adds_topic_context_for_web_sessions(tmp_path: Path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json")
    tool = CronTool(service)
    tool.set_context("web", "browser", "web:pgx:topic-1", "pgx")

    result = asyncio.run(
        tool.execute(
            action="add",
            message="Daily review",
            cron_expr="0 9 * * *",
            tz="Asia/Shanghai",
        )
    )

    assert "Created job" in result
    [job] = service.list_jobs(include_disabled=True)
    assert job.payload.assistant_id == "pgx"
    assert job.payload.topic_session_id == "web:pgx:topic-1"


def test_cron_tool_lists_and_removes_only_current_topic_jobs(tmp_path: Path) -> None:
    service = CronService(tmp_path / "cron" / "jobs.json")
    tool = CronTool(service)
    tool.set_context("web", "browser", "web:pgx:topic-1", "pgx")

    current = create_scoped_job(
        service,
        message="Current topic job",
        channel="web",
        chat_id="browser",
        cron_expr="0 9 * * *",
        tz="Asia/Shanghai",
        assistant_id="pgx",
        topic_session_id="web:pgx:topic-1",
    )
    other = create_scoped_job(
        service,
        message="Other topic job",
        channel="web",
        chat_id="browser",
        cron_expr="0 10 * * *",
        tz="Asia/Shanghai",
        assistant_id="pgx",
        topic_session_id="web:pgx:topic-2",
    )

    listing = asyncio.run(tool.execute(action="list"))
    assert current.id in listing
    assert other.id not in listing

    removed = asyncio.run(tool.execute(action="remove", job_id=other.id))
    assert removed == f"Job {other.id} not found"
    assert service.list_jobs(include_disabled=True)

    removed = asyncio.run(tool.execute(action="remove", job_id=current.id))
    assert removed == f"Removed job {current.id}"
    remaining_ids = [job.id for job in service.list_jobs(include_disabled=True)]
    assert remaining_ids == [other.id]
