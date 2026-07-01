"""Automation payloads for the embedded WebUI."""

from __future__ import annotations

from collections.abc import Collection
from typing import Any, Protocol

from nanobot.cron.types import CronJob
from nanobot.session.automation_turns import is_automation_history_message
from nanobot.session.manager import _message_preview_text
from nanobot.triggers.local_types import LocalTrigger

AutomationJob = CronJob | LocalTrigger


class _CronServiceLike(Protocol):
    def list_jobs(self, include_disabled: bool = False) -> list[CronJob]: ...

    def list_bound_cron_jobs_for_session(
        self,
        session_key: str,
        *,
        include_disabled: bool = True,
    ) -> list[CronJob]: ...


class _LocalTriggerStoreLike(Protocol):
    def list_triggers(self, *, include_disabled: bool = False) -> list[LocalTrigger]: ...

    def list_for_session(
        self,
        session_key: str,
        *,
        include_disabled: bool = True,
    ) -> list[LocalTrigger]: ...


class _SessionManagerLike(Protocol):
    def read_session_file(self, key: str) -> dict[str, Any] | None: ...


def session_automation_jobs(
    cron_service: _CronServiceLike | None,
    session_key: str,
    *,
    local_trigger_store: _LocalTriggerStoreLike | None = None,
) -> list[AutomationJob]:
    """Return user automations attached to the WebUI session."""
    jobs: list[AutomationJob] = []
    if cron_service is not None:
        jobs.extend(
            cron_service.list_bound_cron_jobs_for_session(
                session_key,
                include_disabled=True,
            )
        )
    if local_trigger_store is not None:
        jobs.extend(
            local_trigger_store.list_for_session(
                session_key,
                include_disabled=True,
            )
        )
    return jobs


def session_automations_payload(
    cron_service: _CronServiceLike | None,
    session_key: str,
    *,
    local_trigger_store: _LocalTriggerStoreLike | None = None,
    pending_job_ids: Collection[str] | None = None,
) -> dict[str, Any]:
    """Return user-created automation jobs attached to a WebUI session."""
    return {
        "jobs": serialize_automation_jobs(
            session_automation_jobs(
                cron_service,
                session_key,
                local_trigger_store=local_trigger_store,
            ),
            pending_job_ids=pending_job_ids,
        )
    }


def all_automations_payload(
    cron_service: _CronServiceLike | None,
    *,
    local_trigger_store: _LocalTriggerStoreLike | None = None,
    session_manager: _SessionManagerLike | None = None,
    pending_job_ids: Collection[str] | None = None,
) -> dict[str, Any]:
    """Return all cron jobs visible to the WebUI automation manager."""
    jobs: list[AutomationJob] = []
    if cron_service is not None:
        jobs.extend(cron_service.list_jobs(include_disabled=True))
    if local_trigger_store is not None:
        jobs.extend(local_trigger_store.list_triggers(include_disabled=True))
    return {
        "jobs": serialize_automation_jobs(
            jobs,
            pending_job_ids=pending_job_ids,
            include_details=True,
            session_manager=session_manager,
        )
    }


def serialize_automation_jobs(
    jobs: list[AutomationJob],
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
    job: AutomationJob,
    *,
    pending: bool = False,
    include_details: bool = False,
    session_manager: _SessionManagerLike | None = None,
) -> dict[str, Any]:
    if isinstance(job, LocalTrigger):
        return _serialize_trigger(
            job,
            pending=pending,
            include_details=include_details,
            session_manager=session_manager,
        )

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


def _serialize_trigger(
    trigger: LocalTrigger,
    *,
    pending: bool = False,
    include_details: bool = False,
    session_manager: _SessionManagerLike | None = None,
) -> dict[str, Any]:
    command = f'nanobot trigger {trigger.id} "message"'
    payload = {
        "id": trigger.id,
        "name": trigger.name,
        "enabled": trigger.enabled,
        "kind": "local_trigger",
        "schedule": {
            "kind": "local",
            "at_ms": None,
            "every_ms": None,
            "expr": None,
            "tz": None,
        },
        "payload": {
            "kind": "local_trigger",
            "message": command,
            "command": command,
        },
        "state": {
            "next_run_at_ms": None,
            "last_status": trigger.last_status,
            "pending": pending,
        },
    }
    if not include_details:
        return payload

    payload["protected"] = False
    payload["delete_after_run"] = False
    payload["created_at_ms"] = trigger.created_at_ms
    payload["updated_at_ms"] = trigger.updated_at_ms
    payload["state"].update(
        {
            "last_run_at_ms": trigger.last_run_at_ms,
            "last_error": trigger.last_error,
            "run_history": [
                {
                    "run_at_ms": record.run_at_ms,
                    "status": record.status,
                    "duration_ms": 0,
                    "error": record.error,
                }
                for record in trigger.run_history[-5:]
            ],
        }
    )
    payload["origin"] = _trigger_origin_payload(trigger, session_manager)
    payload["trigger"] = {
        "id": trigger.id,
        "command": command,
    }
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
    return _websocket_origin_payload(
        session_key=session_key,
        channel=channel,
        chat_id=chat_id,
        session_manager=session_manager,
    )


def _trigger_origin_payload(
    trigger: LocalTrigger,
    session_manager: _SessionManagerLike | None,
) -> dict[str, Any] | None:
    channel = trigger.channel
    chat_id = trigger.chat_id
    if not channel or not chat_id:
        return None
    if channel != "websocket":
        return {
            "channel": channel,
            "title": "",
            "preview": "",
        }

    return _websocket_origin_payload(
        session_key=trigger.session_key or f"{channel}:{chat_id}",
        channel=channel,
        chat_id=chat_id,
        session_manager=session_manager,
    )


def _websocket_origin_payload(
    *,
    session_key: str,
    channel: str,
    chat_id: str,
    session_manager: _SessionManagerLike | None,
) -> dict[str, Any]:
    title = ""
    preview = ""
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
        if is_automation_history_message(message):
            continue
        text = _message_preview_text(message)
        if not text:
            continue
        if message.get("role") == "user":
            return text
        if not fallback_preview and message.get("role") == "assistant":
            fallback_preview = text
    return fallback_preview
