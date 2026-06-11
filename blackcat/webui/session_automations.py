"""Session-scoped automation payloads for the embedded WebUI."""

from __future__ import annotations

from typing import Any, Protocol

from blackcat.cron.types import CronJob


class _CronServiceLike(Protocol):
    def list_bound_agent_jobs_for_session(
        self,
        session_key: str,
        *,
        include_disabled: bool = True,
    ) -> list[CronJob]: ...


def session_automation_jobs(
    cron_service: _CronServiceLike | None,
    session_key: str,
) -> list[CronJob]:
    """Return user automations attached to the WebUI session."""
    if cron_service is None:
        return []
    return cron_service.list_bound_agent_jobs_for_session(
        session_key,
        include_disabled=True,
    )


def session_automations_payload(
    cron_service: _CronServiceLike | None,
    session_key: str,
) -> dict[str, Any]:
    """Return user-created automation jobs attached to a WebUI session."""
    return {
        "jobs": serialize_automation_jobs(session_automation_jobs(cron_service, session_key))
    }


def serialize_automation_jobs(jobs: list[CronJob]) -> list[dict[str, Any]]:
    return [_serialize_job(job) for job in jobs]


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
