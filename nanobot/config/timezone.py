"""Backend timezone detection for automatic agent defaults."""

from zoneinfo import ZoneInfo

from tzlocal import get_localzone_name

_UTC_ALIASES = frozenset(
    {"Etc/GMT", "Etc/UTC", "GMT", "GMT0", "Greenwich", "UCT", "Universal", "Zulu"}
)


def detect_system_timezone() -> str:
    """Return the host's IANA timezone, falling back safely to UTC."""
    try:
        timezone = get_localzone_name()
        ZoneInfo(timezone)
    except Exception:
        return "UTC"
    return "UTC" if timezone in _UTC_ALIASES else timezone
