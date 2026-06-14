"""Session-scoped automation payloads for the embedded WebUI."""

from __future__ import annotations

from collections.abc import Collection
from typing import Any, Protocol

from nanobot.cron.types import CronJob


class _CronServiceLike(Protocol):
    def list_bound_cron_jobs_for_session(
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
    return cron_service.list_bound_cron_jobs_for_session(
        session_key,
        include_disabled=True,
    )


def session_automations_payload(
    cron_service: _CronServiceLike | None,
    session_key: str,
    *,
    pending_job_ids: Collection[str] | None = None,
) -> dict[str, Any]:
    """Return user-created automation jobs attached to a WebUI session."""
    return {
        "jobs": serialize_automation_jobs(
            session_automation_jobs(cron_service, session_key),
            pending_job_ids=pending_job_ids,
        )
    }


def serialize_automation_jobs(
    jobs: list[CronJob],
    *,
    pending_job_ids: Collection[str] | None = None,
) -> list[dict[str, Any]]:
    return [_serialize_job(job, pending=job.id in (pending_job_ids or ())) for job in jobs]


def _serialize_job(job: CronJob, *, pending: bool = False) -> dict[str, Any]:
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
            "pending": pending,
        },
    }
