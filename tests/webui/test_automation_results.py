from pathlib import Path

import pytest

from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.cron.bound_runner import run_bound_cron_job
from nanobot.cron.service import CronService
from nanobot.cron.types import CronJob, CronPayload, CronRunRecord, CronRunResult, CronSchedule
from nanobot.triggers.local_types import LocalTrigger, TriggerRunRecord
from nanobot.utils.run_records import write_run_record
from nanobot.webui.automation_results import cron_run_response, trigger_run_response


def job_with_run(run: CronRunRecord) -> CronJob:
    job = CronJob(id="job-1", name="Reminder", schedule=CronSchedule(kind="every", every_ms=60000),
                  payload=CronPayload(message="private prompt", session_key="websocket:one"))
    job.state.run_history = [run]
    return job


def write_result(path: Path, run_id: str, **changes: object) -> None:
    write_run_record(path, run_id, {
        "job_id": "job-1", "session_key": "websocket:one", "status": "ok",
        "response": "The selected response", "rendered_prompt": "private prompt", **changes,
    })


def test_reads_explicit_identity_not_the_latest_run(tmp_path: Path) -> None:
    run = CronRunRecord(run_at_ms=1000, status="ok", duration_ms=100, run_id="job-1:1001:one")
    job = job_with_run(run)
    write_result(tmp_path, run.run_id)
    write_result(tmp_path, "job-1:2001:two", response="The latest response")
    assert cron_run_response(tmp_path, job, run) == "The selected response"


@pytest.mark.parametrize("changes", [
    {"job_id": "other"}, {"session_key": "websocket:other"}, {"status": "error"},
    {"response": {"secret": "not text"}},
])
def test_validates_result_identity_and_response(tmp_path: Path, changes: dict[str, object]) -> None:
    run = CronRunRecord(1000, "ok", 100, run_id="job-1:1001:one")
    write_result(tmp_path, "job-1:1001:one", **changes)
    assert cron_run_response(tmp_path, job_with_run(run), run) is None


def test_legacy_lookup_is_unique_and_confined_to_the_execution_interval(tmp_path: Path) -> None:
    run = CronRunRecord(1000, "ok", 100)
    job = job_with_run(run)
    write_result(tmp_path, "job-1:900:old", response="old")
    write_result(tmp_path, "job-1:1002:one")
    write_result(tmp_path, "job-1:1200:later", response="later")
    assert cron_run_response(tmp_path, job, run) == "The selected response"
    write_result(tmp_path, "job-1:1003:ambiguous", response="different")
    assert cron_run_response(tmp_path, job, run) is None


def test_overlapping_history_does_not_borrow_another_runs_output(tmp_path: Path) -> None:
    run = CronRunRecord(1000, "ok", 100)
    job = job_with_run(run)
    job.state.run_history.append(CronRunRecord(1001, "ok", 99))
    write_result(tmp_path, "job-1:1002:other")
    assert cron_run_response(tmp_path, job, run) is None


def test_missing_record_is_distinct_from_empty_response(tmp_path: Path) -> None:
    run = CronRunRecord(1000, "ok", 100, run_id="job-1:1001:one")
    job = job_with_run(run)
    assert cron_run_response(tmp_path, job, run) is None
    write_result(tmp_path, "job-1:1001:one", response="")
    assert cron_run_response(tmp_path, job, run) == ""


def test_result_path_cannot_escape_the_runs_directory(tmp_path: Path) -> None:
    run = CronRunRecord(1000, "ok", 100, run_id="../private")
    runs = tmp_path / "runs"
    runs.mkdir()
    write_result(tmp_path, "private", response="outside")
    assert cron_run_response(runs, job_with_run(run), run) is None
    (runs / "broken.json").write_text("{", encoding="utf-8")
    run.run_id = "broken"
    assert cron_run_response(runs, job_with_run(run), run) is None


def test_local_trigger_uses_exact_delivery_time_and_session(tmp_path: Path) -> None:
    trigger = LocalTrigger("trg_one", "Reminder", True, "websocket", "one", "websocket:one")
    run = TriggerRunRecord(1000, "ok")
    for run_id, created, response in [("delivery-one", 1000, "first"), ("delivery-two", 2000, "latest")]:
        write_run_record(tmp_path, run_id, {
            "trigger_id": trigger.id, "session_key": trigger.session_key,
            "created_at_ms": created, "status": "ok", "response": response,
        })
    assert trigger_run_response(tmp_path, trigger, run) == "first"
    trigger.session_key = "websocket:other"
    assert trigger_run_response(tmp_path, trigger, run) is None


async def test_new_cron_run_identity_survives_reload(tmp_path: Path) -> None:
    class Agent:
        tools = ToolRegistry()

        async def submit_cron_turn(self, msg: InboundMessage) -> OutboundMessage:
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content="reply")

    async def execute(job: CronJob) -> CronRunResult:
        return await run_bound_cron_job(job, agent=Agent(), cron=service)

    service = CronService(tmp_path / "jobs.json", on_job=execute)
    job = service.add_job(name="Reminder", schedule=CronSchedule(kind="every", every_ms=60000),
                          message="hi", session_key="websocket:one", origin_channel="websocket",
                          origin_chat_id="one")
    assert await service.run_job(job.id, force=True)
    reloaded = CronService(tmp_path / "jobs.json").get_job(job.id)
    assert reloaded is not None
    record = reloaded.state.run_history[-1]
    assert record.run_id is not None
    assert cron_run_response(tmp_path / "runs", reloaded, record) == "reply"
    assert CronRunRecord.from_store_dict({"runAtMs": 1000, "status": "ok", "runId": 42}).run_id is None
