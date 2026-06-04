
import time as time_module
from datetime import date, datetime, timedelta


def today_date() -> str:
    """Get today's date in YYYY-MM-DD format."""
    return datetime.now().strftime("%Y-%m-%d")

def last_24h(date:datetime) -> date:
    """Get the date and time prior 24h of entry date"""
    return (date - timedelta(hours= 24)).date()

def timestamp() -> str:
    """Get current timestamp in ISO format."""
    return datetime.now().isoformat()


def now_ms() -> int:
    """Current time as milliseconds since epoch."""
    return int(time_module.time() * 1000)

def current_time_str(timezone: str | None = None) -> str:
    """Return the current time string."""
    from zoneinfo import ZoneInfo

    try:
        tz = ZoneInfo(timezone) if timezone else None
    except (KeyError, Exception):
        tz = None

    now = datetime.now(tz=tz) if tz else datetime.now().astimezone()
    offset = now.strftime("%z")
    offset_fmt = f"{offset[:3]}:{offset[3:]}" if len(offset) == 5 else offset
    tz_name = timezone or (time_module.strftime("%Z") or "UTC")
    return f"{now.strftime('%Y-%m-%d %H:%M (%A)')} ({tz_name}, UTC{offset_fmt})"
