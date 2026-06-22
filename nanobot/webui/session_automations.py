"""Automation payloads for the embedded WebUI."""

from __future__ import annotations

from collections.abc import Collection
from typing import Any, Protocol

from nanobot.cron.session_turns import CRON_HISTORY_META
from nanobot.cron.types import CronJob
from nanobot.session.manager import _message_preview_text


class _CronServiceLike(Protocol):
    def list_jobs(self, include_disabled: bool = False) -> list[CronJob]: ...

    def list_bound_cron_jobs_for_session(
        self,
        session_key: str,
        *,
        include_disabled: bool = True,
    ) -> list[CronJob]: ...


class _SessionManagerLike(Protocol):
    def read_session_file(self, key: str) -> dict[str, Any] | None: ...


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


def all_automations_payload(
    cron_service: _CronServiceLike | None,
    *,
    session_manager: _SessionManagerLike | None = None,
    pending_job_ids: Collection[str] | None = None,
) -> dict[str, Any]:
    """Return all cron jobs visible to the WebUI automation manager."""
    jobs = cron_service.list_jobs(include_disabled=True) if cron_service is not None else []
    return {
        "jobs": serialize_automation_jobs(
            jobs,
            pending_job_ids=pending_job_ids,
            include_details=True,
            session_manager=session_manager,
        )
    }


def serialize_automation_jobs(
    jobs: list[CronJob],
    *,
    pending_job_ids: Collection[str] | None = None,
    include_details: bool = False,
    session_manager: _SessionManagerLike | None = None,
) -> list[dict[str, Any]]:
    return [
        _serialize_job(
            job,
            pending=job.id in (pending_job_ids or ()),
            include_details=include_details,
            session_manager=session_manager,
        )
        for job in jobs
    ]


def _serialize_job(
    job: CronJob,
    *,
    pending: bool = False,
    include_details: bool = False,
    session_manager: _SessionManagerLike | None = None,
) -> dict[str, Any]:
    payload = {
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
    if not include_details:
        return payload

    payload["protected"] = job.payload.kind == "system_event"
    payload["delete_after_run"] = job.delete_after_run
    payload["created_at_ms"] = job.created_at_ms
    payload["updated_at_ms"] = job.updated_at_ms
    payload["payload"].update({"kind": job.payload.kind})
    payload["state"].update(
        {
            "last_run_at_ms": job.state.last_run_at_ms,
            "last_error": job.state.last_error,
            "run_history": [
                {
                    "run_at_ms": record.run_at_ms,
                    "status": record.status,
                    "duration_ms": record.duration_ms,
                    "error": record.error,
                }
                for record in job.state.run_history[-5:]
            ],
        }
    )
    payload["origin"] = _origin_payload(job, session_manager)
    return payload


def _origin_payload(
    job: CronJob,
    session_manager: _SessionManagerLike | None,
) -> dict[str, Any] | None:
    channel = job.payload.origin_channel
    chat_id = job.payload.origin_chat_id
    if not channel or not chat_id:
        return None
    title = ""
    preview = ""
    if channel != "websocket":
        return {
            "channel": channel,
            "title": title,
            "preview": preview,
        }

    session_key = f"{channel}:{chat_id}"
    if session_manager is not None:
        data = session_manager.read_session_file(session_key)
        if isinstance(data, dict):
            title = str(data.get("title") or "")
            preview = _session_preview(data.get("messages"))

    return {
        "session_key": session_key,
        "channel": channel,
        "chat_id": chat_id,
        "title": title,
        "preview": preview,
    }


def _session_preview(messages: Any) -> str:
    if not isinstance(messages, list):
        return ""
    fallback_preview = ""
    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get(CRON_HISTORY_META) is True:
            continue
        text = _message_preview_text(message)
        if not text:
            continue
        if message.get("role") == "user":
            return text
        if not fallback_preview and message.get("role") == "assistant":
            fallback_preview = text
    return fallback_preview
