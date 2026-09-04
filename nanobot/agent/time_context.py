"""Built-in current-time runtime context provider.

PR #4891 replaced ContextBuilder's default runtime-context injection with
pluggable per-turn providers, but no built-in provider was registered to keep
model-level time awareness, so a configured ``agents.defaults.timezone``
stopped having any effect on turns (issue #5645). This module restores that
capability on the provider mechanism the refactor introduced, using the same
time format as the pre-#4891 ContextBuilder block.
"""

from typing import Any

from nanobot.runtime_context import RuntimeContextBlock

TIME_CONTEXT_SOURCE = "current_time"


def current_time_str(timezone: str | None = None) -> str:
    """Return the current time string (same format as the pre-#4891 block)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    try:
        tz = ZoneInfo(timezone) if timezone else None
    except Exception:
        tz = None

    now = datetime.now(tz=tz) if tz else datetime.now().astimezone()
    offset = now.strftime("%z")
    offset_fmt = f"{offset[:3]}:{offset[3:]}" if len(offset) == 5 else offset
    tz_name = timezone or (now.strftime("%Z") or "UTC")
    return f"{now.strftime('%Y-%m-%d %H:%M (%A)')} ({tz_name}, UTC{offset_fmt})"


def current_time_provider(timezone: str | None = None):
    """Build a per-turn provider that reports the current time in ``timezone``."""

    async def _provider(_request: Any) -> list[RuntimeContextBlock]:
        return [
            RuntimeContextBlock(
                source=TIME_CONTEXT_SOURCE,
                content=(
                    "[Runtime Context — current time]\n"
                    f"Current Time: {current_time_str(timezone)}\n"
                    "[/Runtime Context]"
                ),
            )
        ]

    return _provider
