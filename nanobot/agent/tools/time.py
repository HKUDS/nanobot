"""Time awareness tool — current UTC, user local time, IANA timezone, calendar."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.context import ContextAware, RequestContext
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema

_NANO_TIMER_PARAMETERS = tool_parameters_schema(
    info_type=StringSchema(
        "What information to return: 'time' | 'timezone' | 'location' | 'calendar' | 'all'.",
        enum=("time", "timezone", "location", "calendar", "all"),
        nullable=True,
    ),
    description=(
        "Selects the section of the time report. Defaults to 'all' when null or unknown."
    ),
)


def _resolve_server_tz() -> tuple[str, str]:
    """Return (label, offset_str) for the server's local timezone.

    Prefers the IANA name (``tzinfo.key``) over ``tzname()`` because the
    latter can return a numeric offset (e.g. ``"-03"``) on platforms where
    the tzdata database is incomplete — common in slim Docker images.

    When the runtime is using ``TZ=Asia/Tokyo`` style POSIX timestamps
    (resolved via ``time.tzset()``), ``tzinfo`` is a plain
    ``datetime.timezone`` with no ``.key`` and ``tzname()`` returns the
    short form (``"JST"``, ``"CEST"``). In that case we still report a
    sensible label: the ``TZ`` env var if it is a valid IANA name, else
    the ``tzname()`` result if it is not a bare offset, else a generic
    "server-local" wrapper.
    """
    server = datetime.now().astimezone()
    tzinfo = server.tzinfo
    label: str
    if tzinfo is not None:
        key = getattr(tzinfo, "key", None)
        if key:
            label = key
        else:
            name = tzinfo.tzname(server) or "UTC"
            # IANA names contain a slash (e.g. "America/Sao_Paulo");
            # offsets like "-03" or "+0530" do not.
            if "/" in name:
                label = name
            else:
                # ``TZ=Asia/Tokyo`` -> key=None, name="JST". Try the
                # env var: if it has a slash it is IANA, else fall back
                # to a wrapped short label to avoid losing the signal.
                tz_env = os.environ.get("TZ", "")
                if "/" in tz_env:
                    label = tz_env
                else:
                    label = f"server-local({name})"
    else:
        label = "UTC"
    offset = server.utcoffset()
    if offset is None:
        return label, "UTC+0"
    return label, _format_offset(offset)


def _format_offset(offset: Any) -> str:
    """Format a ``timedelta`` offset as ``UTC[+/-]H[:MM]``.

    Offsets not aligned to whole hours (India UTC+5:30, Nepal UTC+5:45,
    Chatham UTC+12:45) include the minute component. Whole-hour offsets
    stay as ``UTC+N`` to keep the output compact.
    """
    if offset is None:
        return "UTC+0"
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    abs_min = abs(total_minutes)
    hours, minutes = divmod(abs_min, 60)
    if minutes:
        return f"UTC{sign}{hours}:{minutes:02d}"
    return f"UTC{sign}{hours}"


@tool_parameters(_NANO_TIMER_PARAMETERS)
class NanoTimerTool(Tool, ContextAware):
    """Provide accurate time, timezone, and calendar information.

    Uses IANA timezone with automatic DST handling. Source of user timezone
    is :class:`ToolContext.timezone` (``agent_defaults.timezone``), injected
    via :meth:`create` — the tool never reads config files directly.
    """

    def __init__(self, timezone: str = "UTC"):
        self._timezone = timezone
        self._tz_fallback: str | None = None
        self._channel: str = ""
        self._chat_id: str = ""

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return True

    @classmethod
    def create(cls, ctx: Any) -> Tool:
        return cls(timezone=ctx.timezone)

    def set_context(self, ctx: RequestContext) -> None:
        """Record the current request context for observability/logging."""
        self._channel = ctx.channel
        self._chat_id = ctx.chat_id

    @property
    def name(self) -> str:
        return "nano_timer"

    @property
    def description(self) -> str:
        return (
            "Returns accurate time, timezone, and calendar information using IANA "
            "timezone with automatic DST handling. Call this before scheduling, "
            "cron jobs, reminders, or any time-sensitive operation where wrong "
            "time would cause harm. Also useful when the user asks about current "
            "time, date, or timezone, or when converting/comparing times across zones."
        )

    def _compute_payload(self) -> dict[str, Any]:
        """Build the time report payload from the current instant."""
        now_utc = datetime.now(timezone.utc)
        try:
            user_tz = ZoneInfo(self._timezone)
            self._tz_fallback = None
        except (ZoneInfoNotFoundError, ValueError):
            logger.warning(
                "Invalid IANA timezone '{}' in nano_timer; falling back to UTC",
                self._timezone,
            )
            user_tz = ZoneInfo("UTC")
            self._tz_fallback = self._timezone
        user_now = now_utc.astimezone(user_tz)
        server_local = datetime.now().astimezone()
        server_label, server_offset_str = _resolve_server_tz()
        user_offset = user_now.utcoffset()
        same_tz = user_tz == server_local.tzinfo
        diff_from_utc = "N/A"
        if user_offset is not None:
            total_minutes = int(user_offset.total_seconds() // 60)
            sign = "+" if total_minutes >= 0 else "-"
            abs_min = abs(total_minutes)
            hours, minutes = divmod(abs_min, 60)
            if minutes:
                diff_from_utc = f"{sign}{hours}h{minutes:02d}m"
            else:
                diff_from_utc = f"{sign}{hours}h"
        return {
            "utc": {
                "time": now_utc.strftime("%H:%M:%S"),
                "date": now_utc.strftime("%Y-%m-%d"),
                "iso": now_utc.isoformat(),
                "unix": int(now_utc.timestamp()),
            },
            "user": {
                "time": user_now.strftime("%H:%M:%S"),
                "date": user_now.strftime("%Y-%m-%d"),
                "timezone": self._tz_fallback or str(user_tz),
                "offset": _format_offset(user_offset),
            },
            "calendar": {
                "weekday": user_now.strftime("%A"),
                "week_of_year": int(user_now.strftime("%W")),
                "day_of_year": int(user_now.strftime("%j")),
                "weekend": user_now.weekday() >= 5,
            },
            "context": {
                "server_timezone": server_label,
                "server_offset": server_offset_str,
                "same_timezone": same_tz,
                "diff_from_utc_hours": diff_from_utc,
            },
        }

    def _format(self, info_type: str, payload: dict[str, Any]) -> str:
        lines: list[str] = []
        if info_type in ("time", "all"):
            utc = payload["utc"]
            user = payload["user"]
            lines.append("**UTC Time**")
            lines.append(f"  Time: {utc['time']}")
            lines.append(f"  Date: {utc['date']}")
            lines.append(f"  ISO: {utc['iso']}")
            lines.append(f"  Unix: {utc['unix']}")
            lines.append("")
            lines.append("**User Local Time**")
            lines.append(f"  Time: {user['time']}")
            lines.append(f"  Date: {user['date']}")
            lines.append(f"  Timezone: {user['timezone']}")
            lines.append(f"  Offset: {user['offset']}")
        if info_type in ("calendar", "all"):
            if lines and lines[-1] != "":
                lines.append("")
            cal = payload["calendar"]
            lines.append("**Calendar**")
            lines.append(f"  Weekday: {cal['weekday']}")
            lines.append(f"  Week of year: {cal['week_of_year']}")
            lines.append(f"  Day of year: {cal['day_of_year']}")
            lines.append(f"  Weekend: {'Yes' if cal['weekend'] else 'No'}")
        if info_type in ("timezone", "location", "all"):
            if lines and lines[-1] != "":
                lines.append("")
            ctx_block = payload["context"]
            lines.append("**Context**")
            lines.append(f"  Server timezone: {ctx_block['server_timezone']}")
            lines.append(f"  Server offset: {ctx_block['server_offset']}")
            lines.append(
                f"  Same timezone as user: "
                f"{'Yes' if ctx_block['same_timezone'] else 'No'}"
            )
            lines.append(
                f"  Difference from UTC: {ctx_block['diff_from_utc_hours']}"
            )
        if self._tz_fallback:
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(
                f"  ⚠️ timezone '{self._tz_fallback}' invalid; using UTC"
            )
        return "\n".join(lines)

    async def execute(
        self,
        info_type: str | None = "all",
        **kwargs: Any,
    ) -> str:
        """Return a markdown time report for the requested info_type."""
        try:
            if info_type is None or info_type not in (
                "time", "timezone", "location", "calendar", "all",
            ):
                if info_type is not None and info_type != "all":
                    logger.warning(
                        "nano_timer received invalid info_type='{}'; defaulting to 'all'",
                        info_type,
                    )
                info_type = "all"
            payload = self._compute_payload()
            return self._format(info_type, payload)
        except Exception as exc:
            logger.exception("nano_timer failed: {}", exc)
            return f"Error getting time information: {type(exc).__name__}: {exc}"
