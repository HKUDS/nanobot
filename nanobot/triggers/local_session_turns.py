"""Shared metadata helpers for local trigger session turns."""

from __future__ import annotations

from typing import Any, Mapping

from nanobot.session.automation_turns import (
    AutomationTurnSpec,
    automation_trigger,
)

LOCAL_TRIGGER_META = "_local_trigger"


def _local_trigger_history_text(trigger: Mapping[str, Any]) -> str:
    persist_content = trigger.get("persist_content")
    if isinstance(persist_content, str) and persist_content.strip():
        return persist_content
    name = trigger.get("trigger_name")
    trigger_id = trigger.get("trigger_id")
    label = name if isinstance(name, str) and name.strip() else trigger_id
    return (
        f"Local trigger received: {label}"
        if isinstance(label, str) and label.strip()
        else "Local trigger received"
    )


LOCAL_TRIGGER_AUTOMATION_SPEC = AutomationTurnSpec(
    kind="local_trigger",
    trigger_meta_key=LOCAL_TRIGGER_META,
    history_fields={
        "trigger_id": "trigger_id",
        "trigger_name": "trigger_name",
        "trigger_delivery_id": "delivery_id",
    },
    text_builder=_local_trigger_history_text,
)


def local_trigger(metadata: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return structured local trigger metadata when present."""
    return automation_trigger(metadata, LOCAL_TRIGGER_AUTOMATION_SPEC)


def local_trigger_delivery_id(metadata: Mapping[str, Any] | None) -> str | None:
    trigger = local_trigger(metadata)
    if not trigger:
        return None
    value = trigger.get("delivery_id")
    return value if isinstance(value, str) and value else None
