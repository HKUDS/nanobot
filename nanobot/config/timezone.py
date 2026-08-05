"""Backend timezone detection for automatic agent defaults."""

from zoneinfo import ZoneInfo

from tzlocal import get_localzone_name


def detect_system_timezone() -> str:
    """Return the host's IANA timezone, falling back safely to UTC."""
    try:
        timezone = get_localzone_name()
        ZoneInfo(timezone)
    except Exception:
        return "UTC"
    return timezone
