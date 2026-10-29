"""Upgrade old instructions, then exercise only the ordinary scheduling APIs."""

import json

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.cli.legacy_heartbeat import import_heartbeat_task
from nanobot.config.schema import Config
from nanobot.cron.bound_runner import run_bound_cron_job
from nanobot.cron.service import CronService
from nanobot.cron.session_turns import is_bound_cron_job
from nanobot.cron.types import CronJob, CronPayload, CronRunRecord, CronSchedule
from nanobot.session.manager import SessionManager


@pytest.fixture
async def workspace(tmp_path):
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    config.tools.restrict_to_workspace = True
    config.workspace_path.mkdir()
    sessions = SessionManager(config.workspace_path)
    try:
        yield config, tmp_path / "config.json", sessions
    finally:
        await sessions.state.aclose()


def service(config):
    return CronService(config.workspace_path / "cron" / "jobs.json")


@pytest.mark.asyncio
@pytest.mark.parametrize("source_name", ["HEARTBEAT.md", "heartbeat.md"])
async def test_import_becomes_editable_runnable_task_and_does_not_resurrect(workspace, source_name):
    config, path, sessions = workspace
    source = config.workspace_path / source_name
    content = "## Active Tasks\n\n- Check the build and summarize failures.\n"
    source.write_text(content, encoding="utf-8")
    cron = service(config)
    cron.register_system_job(CronJob(
        id="heartbeat", name="heartbeat", payload=CronPayload(kind="system_event"),
        schedule=CronSchedule(kind="every", every_ms=5000),
    ))
    cron.get_job("heartbeat").state.run_history.append(CronRunRecord(run_at_ms=100, status="ok"))
    cron._save_store()
    # A real offline CLI edit must survive the import snapshot too.
    user = cron.add_job(
        "Existing", CronSchedule(kind="every", every_ms=60000), "Keep this",
        session_key="telegram:existing", origin_channel="telegram", origin_chat_id="existing",
    )
    await import_heartbeat_task(config, path, cron, sessions)
    jobs = cron.list_jobs(include_disabled=True)
    job = next(job for job in jobs if job.id != user.id)
    assert len(jobs) == 2
    assert is_bound_cron_job(job)
    assert job.enabled and job.schedule.every_ms == 1800000
    assert job.payload.message == content
    assert job.payload.origin_channel == "websocket"
    assert job.payload.origin_metadata["workspace_scope"] == {
        "project_path": str(config.workspace_path), "access_mode": "restricted",
    }
    assert job.state.run_history[0].session_key == "heartbeat"
    header = await sessions.state.read_metadata(job.payload.session_key)
    assert header["metadata"]["workspace_scope"] == job.payload.origin_metadata["workspace_scope"]
    assert source.read_text(encoding="utf-8") == content

    cron.update_job(job.id, name="Edited", message="Now check tests", schedule=CronSchedule(kind="every", every_ms=3600000))
    cron.enable_job(job.id, False)
    restarted = service(config)
    await import_heartbeat_task(config, path, restarted, sessions)
    saved = restarted.get_job(job.id)
    assert saved.name == "Edited" and saved.payload.message == "Now check tests"
    assert not saved.enabled and saved.schedule.every_ms == 3600000

    seen = []

    class Agent:
        async def submit_cron_turn(self, msg):
            seen.append(msg)
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content="Tests checked")

    async def run(job):
        return await run_bound_cron_job(job, agent=Agent(), cron=restarted)

    restarted.on_job = run
    assert await restarted.run_job(job.id, force=True)
    saved = restarted.get_job(job.id)
    assert seen[0].session_key_override == job.payload.session_key
    assert seen[0].metadata["workspace_scope"]["access_mode"] == "restricted"
    assert "Now check tests" in seen[0].content
    assert saved.state.run_history[-1].status == "ok"
    assert saved.state.run_history[-1].run_id
    assert restarted.enable_job(job.id, True).enabled
    assert restarted.remove_job(job.id) == "removed"
    source.write_text("- New file instructions must not resurrect the deleted task", encoding="utf-8")
    after_delete = service(config)
    await import_heartbeat_task(config, path, after_delete, sessions)
    assert [job.id for job in after_delete.list_jobs(include_disabled=True)] == [user.id]


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["", "# Heartbeat Tasks\n<!-- instructions -->\n## Active Tasks\n"])
async def test_empty_source_is_imported_paused_without_periodic_model_calls(workspace, content):
    config, path, sessions = workspace
    (config.workspace_path / "HEARTBEAT.md").write_text(content, encoding="utf-8")
    cron = service(config)
    await import_heartbeat_task(config, path, cron, sessions)
    assert cron.list_jobs() == []
    job, = cron.list_jobs(include_disabled=True)
    assert not job.enabled and job.state.next_run_at_ms is None
    assert job.payload.message == (content or "Add instructions before enabling this imported task.")


@pytest.mark.asyncio
async def test_previous_opt_out_is_preserved_as_normal_paused_task(workspace):
    config, path, sessions = workspace
    path.write_text(json.dumps({"gateway": {"heartbeat": {"enabled": False, "intervalS": 5}}}))
    (config.workspace_path / "HEARTBEAT.md").write_text("- Check tests", encoding="utf-8")
    cron = service(config)
    await import_heartbeat_task(config, path, cron, sessions)
    job, = cron.list_jobs(include_disabled=True)
    assert not job.enabled and job.schedule.every_ms == 1800000
    assert cron.enable_job(job.id, True).enabled


@pytest.mark.asyncio
async def test_no_source_retires_only_the_old_protected_record(workspace):
    config, path, sessions = workspace
    cron = service(config)
    cron.register_system_job(CronJob(id="heartbeat", name="heartbeat", payload=CronPayload(kind="system_event")))
    normal = cron.add_job(
        "heartbeat", CronSchedule(kind="every", every_ms=60000), "Ordinary same-name job",
        session_key="telegram:user", origin_channel="telegram", origin_chat_id="user",
    )
    await import_heartbeat_task(config, path, cron, sessions)
    assert [job.id for job in cron.list_jobs(include_disabled=True)] == [normal.id]
    assert await sessions.state.list_sessions() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("after_replace", [False, True])
async def test_failed_import_is_retryable_without_duplicate_or_lost_user_jobs(workspace, monkeypatch, after_replace):
    config, path, sessions = workspace
    source = config.workspace_path / "HEARTBEAT.md"
    source.write_text("- Check CI", encoding="utf-8")
    cron = service(config)
    write = cron._write_store

    def fail(store):
        if after_replace:
            write(store)
        raise OSError("disk unavailable")

    monkeypatch.setattr(cron, "_write_store", fail)
    with pytest.raises(OSError, match="disk unavailable"):
        await import_heartbeat_task(config, path, cron, sessions)
    restarted = service(config)
    await import_heartbeat_task(config, path, restarted, sessions)
    job, = restarted.list_jobs(include_disabled=True)
    assert job.payload.message == source.read_text(encoding="utf-8")
    assert len(await sessions.state.list_sessions()) == 1


@pytest.mark.asyncio
async def test_restricted_workspace_does_not_import_symlinked_outside_instructions(workspace, tmp_path):
    config, path, sessions = workspace
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    (config.workspace_path / "HEARTBEAT.md").symlink_to(outside)
    cron = service(config)
    with pytest.raises(ValueError, match="outside the restricted workspace"):
        await import_heartbeat_task(config, path, cron, sessions)
    assert cron.list_jobs(include_disabled=True) == []


@pytest.mark.asyncio
async def test_upgrade_without_source_does_not_turn_later_file_edits_into_a_schedule(workspace):
    config, path, sessions = workspace
    cron = service(config)
    await import_heartbeat_task(config, path, cron, sessions)
    (config.workspace_path / "HEARTBEAT.md").write_text("- Old workspace guidance asked for this file", encoding="utf-8")
    restarted = service(config)
    await import_heartbeat_task(config, path, restarted, sessions)
    assert restarted.list_jobs(include_disabled=True) == []
    assert await sessions.state.list_sessions() == []


@pytest.mark.asyncio
async def test_ambiguous_source_files_stop_import_without_losing_either(workspace):
    config, path, sessions = workspace
    upper = config.workspace_path / "HEARTBEAT.md"
    lower = config.workspace_path / "heartbeat.md"
    upper.write_text("- First task", encoding="utf-8")
    lower.write_text("- Second task", encoding="utf-8")
    if upper.samefile(lower):
        pytest.skip("case-insensitive filesystem has only one source")
    cron = service(config)
    with pytest.raises(ValueError, match="Both HEARTBEAT.md and heartbeat.md"):
        await import_heartbeat_task(config, path, cron, sessions)
    assert upper.read_text(encoding="utf-8") == "- First task"
    assert lower.read_text(encoding="utf-8") == "- Second task"
    lower.unlink()
    await import_heartbeat_task(config, path, cron, sessions)
    job, = cron.list_jobs()
    assert job.payload.message == "- First task"
