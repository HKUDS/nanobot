"""Shared metadata helpers for scheduled cron session turns."""

from __future__ import annotations

from typing import Any, Mapping

from nanobot.cron.types import CronJob
from nanobot.session.automation_turns import (
    AutomationTurnSpec,
    automation_history_overrides_for_spec,
    automation_trigger,
)

CRON_TRIGGER_META = "_cron_trigger"
CRON_DEFER_UNTIL_IDLE_META = "_cron_defer_until_session_idle"
CRON_HISTORY_META = "_cron_turn"


def _cron_history_text(trigger: Mapping[str, Any]) -> str | None:
    persist_content = trigger.get("persist_content")
    return (
        persist_content
        if isinstance(persist_content, str) and persist_content.strip()
        else None
    )


CRON_AUTOMATION_SPEC = AutomationTurnSpec(
    kind="cron",
    trigger_meta_key=CRON_TRIGGER_META,
    legacy_history_meta_key=CRON_HISTORY_META,
    history_fields={
        "cron_job_id": "job_id",
        "cron_job_name": "job_name",
        "cron_run_id": "run_id",
        "cron_prompt_ref": "prompt_ref",
    },
    text_builder=_cron_history_text,
)


def cron_trigger(metadata: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return structured cron trigger metadata when present."""
    return automation_trigger(metadata, CRON_AUTOMATION_SPEC)


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
    return automation_history_overrides_for_spec(metadata, CRON_AUTOMATION_SPEC)


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
