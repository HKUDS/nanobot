"""Shared metadata helpers for local external trigger session turns."""

from __future__ import annotations

from typing import Any, Mapping

from nanobot.session.automation_turns import (
    AutomationTurnSpec,
    automation_history_overrides_for_spec,
    automation_trigger,
)

EXTERNAL_TRIGGER_META = "_external_trigger"


def _external_trigger_history_text(trigger: Mapping[str, Any]) -> str:
    name = trigger.get("trigger_name")
    trigger_id = trigger.get("trigger_id")
    label = name if isinstance(name, str) and name.strip() else trigger_id
    return (
        f"External trigger received: {label}"
        if isinstance(label, str) and label.strip()
        else "External trigger received"
    )


EXTERNAL_TRIGGER_AUTOMATION_SPEC = AutomationTurnSpec(
    kind="trigger",
    trigger_meta_key=EXTERNAL_TRIGGER_META,
    history_fields={
        "trigger_id": "trigger_id",
        "trigger_name": "trigger_name",
        "trigger_delivery_id": "delivery_id",
    },
    text_builder=_external_trigger_history_text,
)


def external_trigger(metadata: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return structured external trigger metadata when present."""
    return automation_trigger(metadata, EXTERNAL_TRIGGER_AUTOMATION_SPEC)


def external_trigger_history_overrides(
    metadata: Mapping[str, Any] | None,
) -> tuple[str | None, dict[str, Any]]:
    """Return session-history text/metadata overrides for an external trigger turn."""
    return automation_history_overrides_for_spec(
        metadata,
        EXTERNAL_TRIGGER_AUTOMATION_SPEC,
    )
