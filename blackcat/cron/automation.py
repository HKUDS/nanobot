"""Shared metadata helpers for scheduled automation turns."""

from __future__ import annotations

from typing import Any, Mapping

from blackcat.cron.types import CronJob

AUTOMATION_TRIGGER_META = "_automation_trigger"
AUTOMATION_DEFER_UNTIL_IDLE_META = "_defer_until_session_idle"
AUTOMATION_HISTORY_META = "_automation_turn"


def automation_trigger(metadata: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return structured automation trigger metadata when present."""
    raw = (metadata or {}).get(AUTOMATION_TRIGGER_META)
    return raw if isinstance(raw, dict) else None


def is_automation_turn(metadata: Mapping[str, Any] | None) -> bool:
    return automation_trigger(metadata) is not None


def defer_until_session_idle(metadata: Mapping[str, Any] | None) -> bool:
    return bool(
        is_automation_turn(metadata)
        and (metadata or {}).get(AUTOMATION_DEFER_UNTIL_IDLE_META) is True
    )


def automation_run_id(metadata: Mapping[str, Any] | None) -> str | None:
    trigger = automation_trigger(metadata)
    if not trigger:
        return None
    value = trigger.get("run_id")
    return value if isinstance(value, str) and value else None


def is_bound_agent_job(job: CronJob) -> bool:
    """True for new session-bound user automations, excluding legacy delivery payloads."""
    payload = job.payload
    if payload.kind != "agent_turn" or not payload.session_key:
        return False
    return not (
        payload.deliver
        or payload.channel
        or payload.to
        or payload.channel_meta
    )
