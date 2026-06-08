"""Session-scoped automation payloads for the embedded WebUI."""

from __future__ import annotations

from typing import Any, Protocol

from nanobot.cron.types import CronJob


class _CronServiceLike(Protocol):
    def list_jobs(self, *, include_disabled: bool = False) -> list[CronJob]: ...


def session_automations_payload(
    cron_service: _CronServiceLike | None,
    session_key: str,
) -> dict[str, Any]:
    """Return user-created automation jobs attached to a WebUI session."""
    jobs: list[CronJob] = []
    if cron_service is not None:
        all_jobs = cron_service.list_jobs(include_disabled=True)
        jobs = [job for job in all_jobs if _job_matches_session(job, session_key)]
    return {"jobs": [_serialize_job(job) for job in jobs]}


def _job_matches_session(job: CronJob, session_key: str) -> bool:
    payload = job.payload
    if payload.kind != "agent_turn":
        return False
    if payload.session_key:
        return payload.session_key == session_key
    if payload.channel and payload.to:
        return f"{payload.channel}:{payload.to}" == session_key
    return False


def _serialize_job(job: CronJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "name": job.name,
        "enabled": job.enabled,
        "schedule": {
            "kind": job.schedule.kind,
            "at_ms": job.schedule.at_ms,
            "every_ms": job.schedule.every_ms,
            "expr": job.schedule.expr,
            "tz": job.schedule.tz,
        },
        "payload": {
            "message": job.payload.message,
        },
        "state": {
            "next_run_at_ms": job.state.next_run_at_ms,
            "last_status": job.state.last_status,
        },
    }
