"""Shared resolution of channel progress switches.

``ChannelManager`` uses these to decide whether to *deliver* progress, and the
agent loop uses ``channels_config_resolve_bool`` to decide whether to let the
model *write* progress notes. Both sides must read the same value: if delivery
and generation disagree, the user either sees notes they asked to suppress or
sees nothing from a switch that reads as on.
"""

from __future__ import annotations

from typing import Any, cast

# Every bool channel switch ``ChannelManager`` resolves from config needs an entry
# here, or a raw JSON/TOML config written in camelCase silently falls back to the
# schema default instead of the value the user set.
BOOL_CAMEL_ALIASES: dict[str, str] = {
    "send_progress": "sendProgress",
    "send_tool_hints": "sendToolHints",
    "show_reasoning": "showReasoning",
    "show_compaction_notices": "showCompactionNotices",
}


def channels_config_resolve_bool(section: Any, key: str) -> bool | None:
    """Return *key* from *section* when it is a bool, otherwise ``None``.

    Accepts both a Pydantic model and a raw dict, and checks the camelCase alias
    (``sendProgress`` for ``send_progress``) so JSON/TOML configs work alongside
    the schema. Returns ``None`` rather than a default so callers can layer a
    per-channel value over a global one.
    """
    if section is None:
        return None
    if isinstance(section, dict):
        section_data = cast(dict[str, Any], section)
        value = section_data.get(key)
        if value is None:
            camel = BOOL_CAMEL_ALIASES.get(key)
            if camel:
                value = section_data.get(camel)
        return value if isinstance(value, bool) else None
    value = getattr(section, key, None)
    return value if isinstance(value, bool) else None
