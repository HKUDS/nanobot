"""Shared handling for session-bound automation turns."""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from nanobot.session.automation_spec import (
    AUTOMATION_HISTORY_META as AUTOMATION_HISTORY_META,
)
from nanobot.session.automation_spec import (
    AutomationTurnSpec as AutomationTurnSpec,
)
from nanobot.session.automation_spec import (
    automation_history_overrides_for_spec as automation_history_overrides_for_spec,
)
from nanobot.session.automation_spec import (
    automation_trigger as automation_trigger,
)


@lru_cache(maxsize=1)
def _automation_specs() -> tuple[AutomationTurnSpec, ...]:
    from nanobot.cron.session_turns import CRON_AUTOMATION_SPEC
    from nanobot.triggers.local_session_turns import LOCAL_TRIGGER_AUTOMATION_SPEC

    return (CRON_AUTOMATION_SPEC, LOCAL_TRIGGER_AUTOMATION_SPEC)


def automation_history_overrides(
    metadata: Mapping[str, Any] | None,
) -> tuple[str | None, dict[str, Any]]:
    """Return session-history text/metadata overrides for supported automation turns."""
    for spec in _automation_specs():
        text, extra = automation_history_overrides_for_spec(metadata, spec)
        if extra:
            return text, extra
    return None, {}


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
