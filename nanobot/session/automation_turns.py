"""Shared handling for session-bound automation turns."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

AUTOMATION_HISTORY_META = "_automation_turn"


@dataclass(frozen=True)
class AutomationTurnSpec:
    """Source-specific wiring for one session-bound automation turn type."""

    kind: str
    trigger_meta_key: str
    legacy_history_meta_key: str | None = None
    history_fields: Mapping[str, str] = field(default_factory=dict)
    text_builder: Callable[[Mapping[str, Any]], str | None] | None = None


def automation_trigger(
    metadata: Mapping[str, Any] | None,
    spec: AutomationTurnSpec,
) -> dict[str, Any] | None:
    """Return source trigger metadata for *spec* when present."""
    raw = (metadata or {}).get(spec.trigger_meta_key)
    return raw if isinstance(raw, dict) else None


def automation_history_overrides_for_spec(
    metadata: Mapping[str, Any] | None,
    spec: AutomationTurnSpec,
) -> tuple[str | None, dict[str, Any]]:
    """Return hidden session-history text/metadata overrides for *spec*."""
    trigger = automation_trigger(metadata, spec)
    if not trigger:
        return None, {}

    details: dict[str, Any] = {"kind": spec.kind}
    extra: dict[str, Any] = {AUTOMATION_HISTORY_META: details}
    if spec.legacy_history_meta_key:
        extra[spec.legacy_history_meta_key] = True
    for history_key, trigger_key in spec.history_fields.items():
        value = trigger.get(trigger_key)
        extra[history_key] = value
        details[history_key] = value

    text = spec.text_builder(trigger) if spec.text_builder else None
    return text, extra


@lru_cache(maxsize=1)
def _automation_specs() -> tuple[AutomationTurnSpec, ...]:
    # Source modules import the generic helpers above, so keep spec loading lazy.
    from nanobot.cron.session_turns import CRON_AUTOMATION_SPEC
    from nanobot.goal_driver import GOAL_DRIVER_AUTOMATION_SPEC
    from nanobot.triggers.local_session_turns import LOCAL_TRIGGER_AUTOMATION_SPEC

    return (CRON_AUTOMATION_SPEC, LOCAL_TRIGGER_AUTOMATION_SPEC, GOAL_DRIVER_AUTOMATION_SPEC)


def automation_history_overrides(
    metadata: Mapping[str, Any] | None,
) -> tuple[str | None, dict[str, Any]]:
    """Return session-history text/metadata overrides for supported automation turns."""
    for spec in _automation_specs():
        text, extra = automation_history_overrides_for_spec(metadata, spec)
        if extra:
            return text, extra
    return None, {}


def is_automation_turn(metadata: Mapping[str, Any] | None) -> bool:
    return any(automation_trigger(metadata, spec) is not None for spec in _automation_specs())


def is_automation_history_message(message: Mapping[str, Any] | None) -> bool:
    """True for hidden automation trigger records in session history."""
    if not message:
        return False
    marker = message.get(AUTOMATION_HISTORY_META)
    if marker is True or isinstance(marker, Mapping):
        return True
    return any(
        spec.legacy_history_meta_key
        and message.get(spec.legacy_history_meta_key) is True
        for spec in _automation_specs()
    )


def is_automation_kind(value: Any) -> bool:
    return isinstance(value, str) and (
        value == "trigger" or any(spec.kind == value for spec in _automation_specs())
    )
