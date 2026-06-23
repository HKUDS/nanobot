"""Shared metadata helpers for scheduled cron session turns."""

from __future__ import annotations

from typing import Any, Mapping

from blackcat.cron.types import CronJob

CRON_TRIGGER_META = "_cron_trigger"
CRON_DEFER_UNTIL_IDLE_META = "_cron_defer_until_session_idle"
CRON_HISTORY_META = "_cron_turn"


def cron_trigger(metadata: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return structured cron trigger metadata when present."""
    raw = (metadata or {}).get(CRON_TRIGGER_META)
    return raw if isinstance(raw, dict) else None


def is_cron_turn(metadata: Mapping[str, Any] | None) -> bool:
    return cron_trigger(metadata) is not None


def defer_cron_until_session_idle(metadata: Mapping[str, Any] | None) -> bool:
    return bool(
        is_cron_turn(metadata)
        and (metadata or {}).get(CRON_DEFER_UNTIL_IDLE_META) is True
    )


def cron_run_id(metadata: Mapping[str, Any] | None) -> str | None:
    trigger = cron_trigger(metadata)
    if not trigger:
        return None
    value = trigger.get("run_id")
    return value if isinstance(value, str) and value else None


def cron_history_overrides(metadata: Mapping[str, Any] | None) -> tuple[str | None, dict[str, Any]]:
    """Return session-history text/metadata overrides for a cron turn."""
    trigger = cron_trigger(metadata)
    if not trigger:
        return None, {}
    persist_content = trigger.get("persist_content")
    text = (
        persist_content
        if isinstance(persist_content, str) and persist_content.strip()
        else None
    )
    return text, {
        CRON_HISTORY_META: True,
        "cron_job_id": trigger.get("job_id"),
        "cron_job_name": trigger.get("job_name"),
        "cron_run_id": trigger.get("run_id"),
        "cron_prompt_ref": trigger.get("prompt_ref"),
    }


def is_bound_cron_job(job: CronJob) -> bool:
    """True for session-bound cron jobs with complete delivery context."""
    payload = job.payload
    if (
        payload.kind != "agent_turn"
        or not payload.session_key
        or not payload.origin_channel
        or not payload.origin_chat_id
    ):
        return False
    return not (
        payload.deliver
        or payload.channel
        or payload.to
        or payload.channel_meta
    )
