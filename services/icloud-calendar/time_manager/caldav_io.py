from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .core import Event

DEFAULT_URL = "https://caldav.icloud.com/"


def credentials(config_path: str = "") -> tuple[str, str, str]:
    if config_path:
        from nanobot.integrations.credentials import icloud_credentials
        return icloud_credentials(Path(config_path))
    username = os.environ.get("ICLOUD_CALDAV_USERNAME", "").strip()
    password = os.environ.get("ICLOUD_CALDAV_APP_PASSWORD", "").strip()
    url = os.environ.get("ICLOUD_CALDAV_URL", DEFAULT_URL).strip()
    missing = [name for name, value in (("ICLOUD_CALDAV_USERNAME", username), ("ICLOUD_CALDAV_APP_PASSWORD", password)) if not value]
    if missing:
        raise RuntimeError("Brak wymaganych sekretów: " + ", ".join(missing))
    return username, password, url


def connect(config_path: str = ""):
    from caldav import get_davclient
    username, password, url = credentials(config_path)
    return get_davclient(url=url, username=username, password=password, timeout=30)


def display_name(calendar: Any) -> str:
    try:
        return str(calendar.get_display_name())
    except Exception:
        return str(getattr(calendar, "name", "")) or "(bez nazwy)"


def temporal(value: Any) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    if hasattr(value, "dt"):
        value = value.dt
    return value.isoformat(), isinstance(value, date) and not isinstance(value, datetime)


def text_values(component: Any, key: str) -> tuple[str, ...]:
    raw = component.get(key)
    if raw is None:
        return ()
    values = raw if isinstance(raw, list) else [raw]
    return tuple(str(value) for value in values)


def scan_all(zone: ZoneInfo, start: datetime, end: datetime, *, config_path: str = "") -> tuple[list[Event], list[dict[str, str]]]:
    events: list[Event] = []
    calendars_info: list[dict[str, str]] = []
    with connect(config_path) as client:
        calendars = client.principal().get_calendars()
        for calendar in calendars:
            name = display_name(calendar)
            calendar_url = str(getattr(calendar, "url", ""))
            calendars_info.append({"name": name, "url": calendar_url})
            resources = calendar.search(start=start, end=end, event=True, expand=True)
            for resource in resources:
                ical = resource.get_icalendar_instance()
                for component in ical.walk("VEVENT"):
                    start_value, all_day = temporal(component.get("DTSTART"))
                    if not start_value:
                        continue
                    end_value, _ = temporal(component.get("DTEND"))
                    if end_value is None and component.get("DURATION") is not None:
                        duration = component.get("DURATION")
                        duration = duration.dt if hasattr(duration, "dt") else duration
                        start_dt = component.get("DTSTART").dt
                        end_value = (start_dt + duration).isoformat()
                    uid = str(component.get("UID") or "").strip()
                    recurrence = temporal(component.get("RECURRENCE-ID"))[0]
                    source_url = str(getattr(resource, "url", "")) or None
                    identity = (recurrence or "master") if uid else (recurrence or start_value)
                    key = f"{calendar_url}|{uid or source_url}|{identity}"
                    sequence_raw = component.get("SEQUENCE")
                    try:
                        sequence = int(sequence_raw or 0)
                    except (TypeError, ValueError):
                        sequence = 0
                    if any(existing.key == key for existing in events):
                        raise RuntimeError(f"Kolizja tożsamości wydarzenia CalDAV: {key}")
                    events.append(Event(
                        key=key, calendar=name, calendar_url=calendar_url, uid=uid,
                        recurrence_id=recurrence, title=str(component.get("SUMMARY") or "(bez tytułu)"),
                        start=start_value, end=end_value, all_day=all_day,
                        location=str(component.get("LOCATION")) if component.get("LOCATION") is not None else None,
                        description=str(component.get("DESCRIPTION")) if component.get("DESCRIPTION") is not None else None,
                        status=str(component.get("STATUS")) if component.get("STATUS") is not None else None,
                        transparency=str(component.get("TRANSP")) if component.get("TRANSP") is not None else None,
                        organizer=str(component.get("ORGANIZER")) if component.get("ORGANIZER") is not None else None,
                        attendees=text_values(component, "ATTENDEE"), categories=text_values(component, "CATEGORIES"),
                        sequence=sequence, last_modified=temporal(component.get("LAST-MODIFIED"))[0], source_url=source_url,
                    ))
    return events, calendars_info


def choose_management_calendar(principal: Any, calendars: list[Any], selector: str) -> Any:
    if selector == "auto":
        raise RuntimeError("Automatyczny wybór kalendarza jest niedozwolony dla zapisu; ustaw dedykowaną nazwę")
    matches = [c for c in calendars if display_name(c).casefold() == selector.casefold() or str(getattr(c, "url", "")).rstrip("/") == selector.rstrip("/")]
    if len(matches) > 1:
        raise RuntimeError(f"Niejednoznaczna nazwa kalendarza zarządzającego: {selector}")
    if matches:
        return matches[0]
    if "://" in selector:
        raise RuntimeError(f"Nie znaleziono kalendarza zarządzającego: {selector}")
    return principal.make_calendar(name=selector)


def sync_sleep_blocks(events: list[Event], *, zone: ZoneInfo, selector: str, days: int, default_wake, prep_minutes: int, sleep_hours: float, now: datetime, config_path: str = "") -> list[str]:
    from datetime import UTC

    from caldav.lib.error import NotFoundError
    from icalendar import Calendar
    from icalendar import Event as ICalEvent

    from .core import sleep_window

    updated: list[str] = []
    with connect(config_path) as client:
        principal = client.principal()
        calendars = principal.get_calendars()
        calendar = choose_management_calendar(principal, calendars, selector)
        for offset in range(days + 1):
            wake_day = now.date() + timedelta(days=offset)
            bedtime, wake = sleep_window(wake_day, events, zone, default_wake, prep_minutes, sleep_hours)
            uid = f"nanobot-sleep-{wake_day.isoformat()}@nanobot"
            root = Calendar()
            root.add("prodid", "-//Nanobot//iCloud Time Manager//PL")
            root.add("version", "2.0")
            item = ICalEvent()
            item.add("uid", uid)
            item.add("dtstamp", datetime.now(UTC))
            item.add("dtstart", bedtime)
            item.add("dtend", wake)
            item.add("summary", "Sen")
            item.add("description", "Blok snu zarządzany automatycznie przez Nanobota na podstawie planu dnia.")
            item.add("categories", ["NANOBOT", "SEN"])
            item.add("transp", "OPAQUE")
            item.add("X-NANOBOT-MANAGED", "sleep-v1")
            root.add_component(item)
            raw = root.to_ical().decode("utf-8")
            try:
                resource = calendar.get_event_by_uid(uid)
            except NotFoundError:
                calendar.save_event(raw)
                updated.append(uid)
                continue

            existing = next(iter(resource.get_icalendar_instance().walk("VEVENT")), None)
            if existing is None or str(existing.get("X-NANOBOT-MANAGED") or "") != "sleep-v1":
                raise RuntimeError(f"Odmowa nadpisania wydarzenia bez znacznika własności Nanobota: {uid}")
            old_start = existing.get("DTSTART").dt
            old_end = existing.get("DTEND").dt
            if old_start == bedtime and old_end == wake:
                continue
            with resource.edit_icalendar_instance() as existing_root:
                target = next(iter(existing_root.walk("VEVENT")))
                for key, value in (("DTSTART", bedtime), ("DTEND", wake), ("DTSTAMP", datetime.now(UTC))):
                    if key in target:
                        del target[key]
                    target.add(key, value)
                target["SEQUENCE"] = int(target.get("SEQUENCE") or 0) + 1
            resource.save()
            resource.load()
            verified = next(iter(resource.get_icalendar_instance().walk("VEVENT")))
            if str(verified.get("UID")) != uid or verified.get("DTSTART").dt != bedtime or verified.get("DTEND").dt != wake:
                raise RuntimeError(f"Weryfikacja zapisu bloku snu nie powiodła się: {uid}")
            updated.append(uid)
    return updated
