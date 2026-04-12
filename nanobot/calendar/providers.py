"""Calendar provider implementations."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from nanobot.calendar.errors import CalendarError, CalendarErrorCode
from nanobot.calendar.types import CalendarEvent


def now_ms() -> int:
    """Current timestamp (ms)."""
    return int(time.time() * 1000)


def parse_iso_datetime(value: str, timezone: str) -> datetime:
    """Parse ISO datetime; naive input will be interpreted with provided timezone."""
    from zoneinfo import ZoneInfo

    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(timezone))
    return dt


class CalendarProvider(Protocol):
    """Provider protocol."""

    name: str

    def configured(self) -> bool:
        """Whether provider is ready for use."""
        ...

    def list_calendars(self) -> list[dict[str, Any]]:
        """List available calendars."""
        ...

    def list_events(
        self,
        *,
        calendar_id: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
        attendee: str | None = None,
    ) -> list[CalendarEvent]:
        """List events."""
        ...

    def get_event(self, *, calendar_id: str | None = None, event_id: str) -> CalendarEvent | None:
        """Get one event by id."""
        ...

    def create_event(
        self,
        *,
        calendar_id: str | None = None,
        title: str,
        start_at: str,
        end_at: str,
        timezone: str,
        description: str = "",
        location: str = "",
        attendees: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CalendarEvent:
        """Create an event."""
        ...

    def update_event(
        self,
        *,
        calendar_id: str | None = None,
        event_id: str,
        fields: dict[str, Any],
    ) -> CalendarEvent | None:
        """Update an event and return updated value."""
        ...

    def delete_event(self, *, calendar_id: str | None = None, event_id: str) -> bool:
        """Delete event by id."""
        ...


class LocalCalendarProvider:
    """File-backed local calendar provider."""

    name = "local"

    def __init__(self, store_path: Path):
        self.store_path = store_path
        self._events: list[CalendarEvent] | None = None
        self._last_mtime = 0.0

    def configured(self) -> bool:
        return True

    def list_calendars(self) -> list[dict[str, Any]]:
        return [{"id": "default", "name": "Default", "is_primary": True}]

    def _load(self) -> list[CalendarEvent]:
        if self._events is not None and self.store_path.exists():
            mtime = self.store_path.stat().st_mtime
            if mtime != self._last_mtime:
                self._events = None
        if self._events is not None:
            return self._events

        if not self.store_path.exists():
            self._events = []
            return self._events
        try:
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
            self._events = [
                CalendarEvent(
                    id=e["id"],
                    provider=e["provider"],
                    calendar_id=e.get("calendarId", "default"),
                    title=e["title"],
                    start_at=e["startAt"],
                    end_at=e["endAt"],
                    timezone=e["timezone"],
                    description=e.get("description", ""),
                    location=e.get("location", ""),
                    attendees=list(e.get("attendees", [])),
                    metadata=dict(e.get("metadata", {})),
                    created_at_ms=e.get("createdAtMs", 0),
                    updated_at_ms=e.get("updatedAtMs", 0),
                )
                for e in data.get("events", [])
            ]
        except Exception:
            self._events = []
        return self._events

    def _save(self) -> None:
        if self._events is None:
            return
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "events": [
                {
                    "id": e.id,
                    "provider": e.provider,
                    "calendarId": e.calendar_id,
                    "title": e.title,
                    "startAt": e.start_at,
                    "endAt": e.end_at,
                    "timezone": e.timezone,
                    "description": e.description,
                    "location": e.location,
                    "attendees": e.attendees,
                    "metadata": e.metadata,
                    "createdAtMs": e.created_at_ms,
                    "updatedAtMs": e.updated_at_ms,
                }
                for e in self._events
            ],
        }
        self.store_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self._last_mtime = self.store_path.stat().st_mtime

    def list_events(
        self,
        *,
        calendar_id: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
        attendee: str | None = None,
    ) -> list[CalendarEvent]:
        calendar_id = calendar_id or "default"
        events = [e for e in self._load() if e.calendar_id == calendar_id]
        if attendee:
            events = [e for e in events if attendee in e.attendees]

        if not start_at and not end_at:
            return sorted(events, key=lambda e: e.start_at)

        start_dt = parse_iso_datetime(start_at, "UTC") if start_at else None
        end_dt = parse_iso_datetime(end_at, "UTC") if end_at else None
        filtered: list[CalendarEvent] = []
        for event in events:
            event_start = parse_iso_datetime(event.start_at, event.timezone)
            event_end = parse_iso_datetime(event.end_at, event.timezone)
            if start_dt and event_end <= start_dt:
                continue
            if end_dt and event_start >= end_dt:
                continue
            filtered.append(event)
        return sorted(filtered, key=lambda e: e.start_at)

    def get_event(self, *, calendar_id: str | None = None, event_id: str) -> CalendarEvent | None:
        calendar_id = calendar_id or "default"
        for event in self._load():
            if event.calendar_id == calendar_id and event.id == event_id:
                return event
        return None

    def create_event(
        self,
        *,
        calendar_id: str | None = None,
        title: str,
        start_at: str,
        end_at: str,
        timezone: str,
        description: str = "",
        location: str = "",
        attendees: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CalendarEvent:
        calendar_id = calendar_id or "default"
        # Validate datetime range
        start_dt = parse_iso_datetime(start_at, timezone)
        end_dt = parse_iso_datetime(end_at, timezone)
        if end_dt <= start_dt:
            raise CalendarError(CalendarErrorCode.INVALID_ARGUMENT, "end_at must be after start_at")

        now = now_ms()
        event = CalendarEvent(
            id=str(uuid.uuid4())[:8],
            provider=self.name,
            calendar_id=calendar_id,
            title=title,
            start_at=start_dt.isoformat(),
            end_at=end_dt.isoformat(),
            timezone=timezone,
            description=description,
            location=location,
            attendees=list(attendees or []),
            metadata=dict(metadata or {}),
            created_at_ms=now,
            updated_at_ms=now,
        )
        events = self._load()
        events.append(event)
        self._save()
        return event

    def update_event(
        self,
        *,
        calendar_id: str | None = None,
        event_id: str,
        fields: dict[str, Any],
    ) -> CalendarEvent | None:
        calendar_id = calendar_id or "default"
        events = self._load()
        for idx, event in enumerate(events):
            if event.calendar_id != calendar_id or event.id != event_id:
                continue
            merged = asdict(event)
            merged.update(fields)
            timezone = str(merged.get("timezone") or event.timezone)
            start_dt = parse_iso_datetime(str(merged["start_at"]), timezone)
            end_dt = parse_iso_datetime(str(merged["end_at"]), timezone)
            if end_dt <= start_dt:
                raise CalendarError(
                    CalendarErrorCode.INVALID_ARGUMENT,
                    "end_at must be after start_at",
                )

            merged["start_at"] = start_dt.isoformat()
            merged["end_at"] = end_dt.isoformat()
            merged["updated_at_ms"] = now_ms()
            merged["attendees"] = list(merged.get("attendees") or [])
            merged["metadata"] = dict(merged.get("metadata") or {})
            updated = CalendarEvent(**merged)
            events[idx] = updated
            self._save()
            return updated
        return None

    def delete_event(self, *, calendar_id: str | None = None, event_id: str) -> bool:
        calendar_id = calendar_id or "default"
        events = self._load()
        before = len(events)
        self._events = [
            e for e in events if not (e.calendar_id == calendar_id and e.id == event_id)
        ]
        if len(self._events) == before:
            return False
        self._save()
        return True


class FeishuCalendarProvider:
    """Feishu/Lark calendar provider using OAuth 2.0 user access token.

    On first use it opens a browser for authorization and starts a local HTTP
    server to capture the OAuth callback.  The resulting tokens are persisted
    under the ``feishu.token`` key of the shared auth file
    (default ``~/.nanobot/auth.json``) and refreshed automatically.

    App credentials come from constructor arguments or environment variables —
    they are NOT stored in the auth file.  The auth file is provider-keyed so
    multiple calendar providers can share a single file::

        {
          "feishu": {
            "token": {
              "access_token": "...",
              "refresh_token": "...",
              "expires_at": 1234567890
            }
          }
        }

    Required (constructor arg or env var):
      app_id / NANOBOT_FEISHU_APP_ID      – Feishu application App ID
      app_secret / NANOBOT_FEISHU_APP_SECRET  – Feishu application App Secret
    Optional:
      calendar_id / NANOBOT_FEISHU_CALENDAR_ID – Default calendar ID (default: "primary")
      redirect_uri / NANOBOT_FEISHU_REDIRECT_URI – OAuth redirect URI
      domain / NANOBOT_FEISHU_DOMAIN       – "feishu" or "lark" (default: "feishu")
    """

    name = "feishu"

    def __init__(
        self,
        app_id: str | None = None,
        app_secret: str | None = None,
        auth_path: Path | None = None,
        redirect_uri: str | None = None,
        default_calendar_id: str | None = None,
        domain: str | None = None,
        # Legacy aliases kept for backwards compatibility
        config_path: Path | None = None,
        token_path: Path | None = None,
    ):
        import os

        self._auth_path = (
            auth_path or config_path or token_path or (Path.home() / ".nanobot" / "auth.json")
        )

        self._app_id = app_id or os.environ.get("NANOBOT_FEISHU_APP_ID", "")
        self._app_secret = app_secret or os.environ.get("NANOBOT_FEISHU_APP_SECRET", "")
        self._redirect_uri = redirect_uri or os.environ.get(
            "NANOBOT_FEISHU_REDIRECT_URI", "http://localhost:9527/callback"
        )
        self._default_calendar_id = default_calendar_id or os.environ.get(
            "NANOBOT_FEISHU_CALENDAR_ID", "primary"
        )
        self._domain = domain or os.environ.get("NANOBOT_FEISHU_DOMAIN", "feishu")
        self.reason = ""
        self._token_cache: dict[str, Any] | None = None
        self._primary_calendar_id: str | None = None

    # ------------------------------------------------------------------ #
    # CalendarProvider protocol                                             #
    # ------------------------------------------------------------------ #

    def configured(self) -> bool:
        try:
            import lark_oapi  # noqa: F401
        except ImportError:
            self.reason = "lark_oapi not installed"
            return False
        if not self._app_id or not self._app_secret:
            self.reason = (
                "app_id / app_secret not configured; set them via the Feishu channel config "
                "or env vars NANOBOT_FEISHU_APP_ID / NANOBOT_FEISHU_APP_SECRET"
            )
            return False
        token = self._load_token()
        if not token:
            self.reason = "not authorized yet; use calendar action to trigger OAuth"
            return False
        if not token.get("refresh_token"):
            self.reason = "no refresh_token stored; re-authorize"
            return False
        self.reason = ""
        return True

    # ------------------------------------------------------------------ #
    # Token management                                                      #
    # ------------------------------------------------------------------ #

    def _read_auth_file(self) -> dict[str, Any]:
        """Read the shared auth file; return empty dict if missing or invalid."""
        if not self._auth_path.exists():
            return {}
        try:
            return json.loads(self._auth_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_auth_file(self, data: dict[str, Any]) -> None:
        self._auth_path.parent.mkdir(parents=True, exist_ok=True)
        self._auth_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_token(self) -> dict[str, Any] | None:
        if self._token_cache is not None:
            return self._token_cache
        token = self._read_auth_file().get("feishu", {}).get("token")
        if not token:
            return None
        self._token_cache = token
        return token

    def _save_token(self, data: dict[str, Any]) -> None:
        auth = self._read_auth_file()
        auth.setdefault("feishu", {})["token"] = data
        self._write_auth_file(auth)
        self._token_cache = data

    def _clear_token(self) -> None:
        """Remove the stored OAuth token from the auth file."""
        self._token_cache = None
        auth = self._read_auth_file()
        auth.get("feishu", {}).pop("token", None)
        if not auth.get("feishu"):
            auth.pop("feishu", None)
        self._write_auth_file(auth)

    def _get_access_token(self) -> str:
        """Return a valid access token, refreshing or re-authorizing as needed."""
        token = self._load_token()
        if not token:
            token = self._do_oauth()
        # Refresh proactively if it expires within 5 minutes
        if time.time() >= token.get("expires_at", 0) - 300:
            try:
                token = self._do_refresh(token["refresh_token"])
            except CalendarError:
                # Refresh token expired – clear cached token and re-auth
                self._clear_token()
                token = self._do_oauth()
        return str(token["access_token"])

    def _do_oauth(self) -> dict[str, Any]:
        """Launch browser OAuth flow and wait for the local callback."""
        import secrets
        import urllib.parse
        import webbrowser
        from http.server import BaseHTTPRequestHandler, HTTPServer

        from loguru import logger

        code_holder: list[str] = []
        error_holder: list[str] = []
        expected_state = secrets.token_urlsafe(24)

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
                if params.get("state") != expected_state:
                    error_holder.append("OAuth state mismatch")
                    self.send_response(400)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(
                        "<html><body><h2>授权失败：state 校验失败，请重试。</h2></body></html>".encode()
                    )
                    return
                if "error" in params:
                    error_holder.append(str(params.get("error")))
                    self.send_response(400)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(
                        "<html><body><h2>授权失败，请关闭窗口后重试。</h2></body></html>".encode()
                    )
                    return
                if "code" in params:
                    code_holder.append(params["code"])
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(
                        "<html><body><h2>授权成功！可以关闭此窗口。</h2></body></html>".encode()
                    )
                    return
                error_holder.append("OAuth callback missing code")
                self.send_response(400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    "<html><body><h2>授权失败：回调参数不完整，请重试。</h2></body></html>".encode()
                )

            def log_message(self, *_: Any) -> None:
                pass

        parsed = urllib.parse.urlparse(self._redirect_uri)
        port = parsed.port or 80
        scope = "calendar:calendar:readonly calendar:calendar.event:create calendar:calendar.event:update calendar:calendar.event:delete"
        auth_url = (
            "https://open.feishu.cn/open-apis/authen/v1/authorize"
            f"?app_id={self._app_id}"
            f"&redirect_uri={urllib.parse.quote(self._redirect_uri, safe='')}"
            f"&scope={urllib.parse.quote(scope, safe='')}"
            f"&state={urllib.parse.quote(expected_state, safe='')}"
        )

        logger.info("Feishu calendar OAuth: opening browser for authorization")
        logger.info("If the browser did not open, visit: {}", auth_url)
        webbrowser.open(auth_url)

        server = HTTPServer(("127.0.0.1", port), _Handler)
        server.timeout = 1
        deadline = time.time() + 120
        while not code_holder and not error_holder and time.time() < deadline:
            server.handle_request()
        server.server_close()

        if error_holder:
            raise CalendarError(
                CalendarErrorCode.AUTH_FAILED,
                f"OAuth authorization failed: {error_holder[0]}",
            )
        if not code_holder:
            raise CalendarError(
                CalendarErrorCode.PROVIDER_UNAVAILABLE,
                "OAuth authorization timed out (120 s). Please try again.",
            )
        return self._exchange_code(code_holder[0])

    def _exchange_code(self, code: str) -> dict[str, Any]:
        from lark_oapi.api.authen.v1 import (
            CreateAccessTokenRequest,
            CreateAccessTokenRequestBody,
        )

        client = self._build_lark_client()
        body = (
            CreateAccessTokenRequestBody.builder()
            .grant_type("authorization_code")
            .code(code)
            .build()
        )
        request = CreateAccessTokenRequest.builder().request_body(body).build()
        response = client.authen.v1.access_token.create(request)
        if not response.success():
            raise CalendarError(
                CalendarErrorCode.PROVIDER_UNAVAILABLE,
                f"Failed to exchange OAuth code: {response.msg}",
                details={"lark_code": response.code},
            )
        d = response.data
        token: dict[str, Any] = {
            "access_token": d.access_token,
            "refresh_token": d.refresh_token,
            "expires_at": time.time() + (d.expires_in or 7200),
            "refresh_expires_at": time.time() + (d.refresh_expires_in or 2_592_000),
        }
        # Save user identity fields for personal calendar resolution
        if d.open_id:
            token["open_id"] = d.open_id
        if d.user_id:
            token["user_id"] = d.user_id
        self._save_token(token)
        return token

    def _do_refresh(self, refresh_token: str) -> dict[str, Any]:
        from lark_oapi.api.authen.v1 import (
            CreateRefreshAccessTokenRequest,
            CreateRefreshAccessTokenRequestBody,
        )

        client = self._build_lark_client()
        body = (
            CreateRefreshAccessTokenRequestBody.builder()
            .grant_type("refresh_token")
            .refresh_token(refresh_token)
            .build()
        )
        request = CreateRefreshAccessTokenRequest.builder().request_body(body).build()
        response = client.authen.v1.refresh_access_token.create(request)
        if not response.success():
            raise CalendarError(
                CalendarErrorCode.PROVIDER_UNAVAILABLE,
                f"Token refresh failed: {response.msg}",
                details={"lark_code": response.code},
            )
        d = response.data
        previous = self._load_token() or {}
        token = {
            "access_token": d.access_token,
            "refresh_token": d.refresh_token,
            "expires_at": time.time() + (d.expires_in or 7200),
            "refresh_expires_at": time.time() + (d.refresh_expires_in or 2_592_000),
        }
        # Preserve identity claims when refresh response does not include them.
        if getattr(d, "open_id", None):
            token["open_id"] = d.open_id
        elif previous.get("open_id"):
            token["open_id"] = previous["open_id"]
        if getattr(d, "user_id", None):
            token["user_id"] = d.user_id
        elif previous.get("user_id"):
            token["user_id"] = previous["user_id"]
        self._save_token(token)
        return token

    # ------------------------------------------------------------------ #
    # Lark client helpers                                                   #
    # ------------------------------------------------------------------ #

    def _build_lark_client(self, *, enable_set_token: bool = True) -> Any:
        import lark_oapi as lark
        from lark_oapi.core.const import FEISHU_DOMAIN, LARK_DOMAIN

        domain = LARK_DOMAIN if self._domain == "lark" else FEISHU_DOMAIN
        return (
            lark.Client.builder()
            .app_id(self._app_id)
            .app_secret(self._app_secret)
            .domain(domain)
            .enable_set_token(enable_set_token)
            .build()
        )

    def _build_option(self) -> Any:
        from lark_oapi.core.model import RequestOption

        return RequestOption.builder().user_access_token(self._get_access_token()).build()

    def _check_response(self, response: Any, action: str) -> Any:
        if not response.success():
            raise CalendarError(
                CalendarErrorCode.API_ERROR,
                f"Feishu API error on {action}: {response.msg}",
                details={"lark_code": response.code, "action": action},
            )
        return response.data

    # ------------------------------------------------------------------ #
    # Calendar ID resolution                                                #
    # ------------------------------------------------------------------ #

    def _resolve_calendar_id(self, calendar_id: str | None) -> str:
        cal_id = calendar_id or self._default_calendar_id
        if cal_id != "primary":
            return cal_id
        if self._primary_calendar_id:
            return self._primary_calendar_id

        from lark_oapi.api.calendar.v4 import PrimaryCalendarRequest
        from loguru import logger

        client = self._build_lark_client()
        option = self._build_option()

        request = PrimaryCalendarRequest.builder().user_id_type("open_id").build()
        response = client.calendar.v4.calendar.primary(request, option)
        if response.success() and response.data and response.data.calendars:
            for uc in response.data.calendars:
                if uc.calendar and uc.calendar.calendar_id:
                    found = uc.calendar.calendar_id
                    logger.debug(
                        "Feishu calendar resolution: primary calendar {} ({})",
                        found,
                        uc.calendar.summary,
                    )
                    self._primary_calendar_id = found
                    return found

        raise CalendarError(
            CalendarErrorCode.API_ERROR,
            "Could not find the user's primary calendar. "
            "Please set NANOBOT_FEISHU_CALENDAR_ID to the correct calendar ID "
            "(use 'calendar action: list_calendars, provider: feishu' to see available calendars).",
        )

    # ------------------------------------------------------------------ #
    # Time conversion helpers                                               #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _timeinfo_to_iso(ti: Any, fallback_tz: str = "UTC") -> str:
        """Convert a Feishu TimeInfo to an ISO datetime string."""
        from datetime import timezone as dt_timezone
        from zoneinfo import ZoneInfo

        if ti is None:
            raise CalendarError(
                CalendarErrorCode.INVALID_ARGUMENT, "missing TimeInfo in API response"
            )
        tz = ti.timezone or fallback_tz
        if ti.timestamp:
            # timestamp is UTC unix seconds; convert to event's local timezone
            utc_dt = datetime.fromtimestamp(float(ti.timestamp), tz=dt_timezone.utc)
            return utc_dt.astimezone(ZoneInfo(tz)).isoformat()
        if ti.date:
            return parse_iso_datetime(f"{ti.date}T00:00:00", tz).isoformat()
        raise CalendarError(
            CalendarErrorCode.INVALID_ARGUMENT, "TimeInfo has neither timestamp nor date"
        )

    @staticmethod
    def _iso_to_timeinfo(iso: str, tz: str) -> Any:
        """Convert ISO datetime string to a Feishu TimeInfo builder result."""
        from lark_oapi.api.calendar.v4 import TimeInfo

        dt = parse_iso_datetime(iso, tz)
        ts = str(int(dt.timestamp()))
        ti = TimeInfo()
        ti.timestamp = ts
        ti.timezone = tz
        return ti

    # ------------------------------------------------------------------ #
    # Attendee helpers                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _attendee_to_str(att: Any) -> str | None:
        if att is None:
            return None
        if att.third_party_email:
            return att.third_party_email
        if att.display_name:
            return att.display_name
        if att.user_id:
            return att.user_id
        return None

    @staticmethod
    def _str_to_attendee(value: str) -> Any:
        from lark_oapi.api.calendar.v4 import CalendarEventAttendee

        att = CalendarEventAttendee()
        att.type = "user"
        if "@" in value:
            att.third_party_email = value
        else:
            att.open_id = value
        return att

    # ------------------------------------------------------------------ #
    # Internal event converter                                              #
    # ------------------------------------------------------------------ #

    def _event_from_lark(self, lark_event: Any, calendar_id: str) -> CalendarEvent:
        tz = "UTC"
        if lark_event.start_time and lark_event.start_time.timezone:
            tz = lark_event.start_time.timezone

        attendees: list[str] = []
        for att in lark_event.attendees or []:
            s = self._attendee_to_str(att)
            if s:
                attendees.append(s)

        created_ms = 0
        if lark_event.create_time:
            try:
                created_ms = int(float(lark_event.create_time) * 1000)
            except (ValueError, TypeError):
                pass

        location = ""
        if lark_event.location and lark_event.location.name:
            location = lark_event.location.name

        return CalendarEvent(
            id=str(lark_event.event_id or ""),
            provider=self.name,
            calendar_id=calendar_id,
            title=str(lark_event.summary or ""),
            start_at=self._timeinfo_to_iso(lark_event.start_time, tz),
            end_at=self._timeinfo_to_iso(lark_event.end_time, tz),
            timezone=tz,
            description=str(lark_event.description or ""),
            location=location,
            attendees=attendees,
            metadata={},
            created_at_ms=created_ms,
            updated_at_ms=created_ms,
        )

    # ------------------------------------------------------------------ #
    # Calendar CRUD                                                         #
    # ------------------------------------------------------------------ #

    def list_calendars(self) -> list[dict[str, Any]]:
        from lark_oapi.api.calendar.v4 import ListCalendarRequest

        client = self._build_lark_client()
        option = self._build_option()
        request = ListCalendarRequest.builder().page_size(50).build()
        data = self._check_response(
            client.calendar.v4.calendar.list(request, option), "list_calendars"
        )
        result: list[dict[str, Any]] = []
        for cal in data.calendar_list or []:
            result.append(
                {
                    "id": cal.calendar_id,
                    "name": cal.summary or "",
                    "type": cal.type or "",
                    "role": cal.role or "",
                    "is_primary": cal.type == "primary",
                    "is_owned": cal.role == "owner",
                }
            )
        return result

    def list_events(
        self,
        *,
        calendar_id: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
        attendee: str | None = None,
    ) -> list[CalendarEvent]:
        from lark_oapi.api.calendar.v4 import ListCalendarEventRequest

        cal_id = self._resolve_calendar_id(calendar_id)
        client = self._build_lark_client()
        option = self._build_option()

        use_time_range = bool(start_at and end_at)

        builder = ListCalendarEventRequest.builder().calendar_id(cal_id).user_id_type("open_id")
        if use_time_range:
            # Per Feishu docs: start_time/end_time returns data in one shot
            # (no pagination), capped by page_size. Use max allowed value.
            builder = (
                builder.page_size(1000)
                .start_time(str(int(parse_iso_datetime(start_at, "UTC").timestamp())))
                .end_time(str(int(parse_iso_datetime(end_at, "UTC").timestamp())))
            )
        else:
            builder = builder.page_size(500)

        all_events: list[CalendarEvent] = []
        page_token: str | None = None
        while True:
            if page_token:
                builder = builder.page_token(page_token)
            data = self._check_response(
                client.calendar.v4.calendar_event.list(builder.build(), option), "list_events"
            )
            for ev in data.items or []:
                event = self._event_from_lark(ev, cal_id)
                if attendee and attendee not in event.attendees:
                    continue
                all_events.append(event)
            if use_time_range or not data.has_more:
                break
            page_token = data.page_token

        return sorted(all_events, key=lambda e: e.start_at)

    def get_event(self, *, calendar_id: str | None = None, event_id: str) -> CalendarEvent | None:
        from lark_oapi.api.calendar.v4 import GetCalendarEventRequest

        cal_id = self._resolve_calendar_id(calendar_id)
        client = self._build_lark_client()
        option = self._build_option()
        request = (
            GetCalendarEventRequest.builder()
            .calendar_id(cal_id)
            .event_id(event_id)
            .user_id_type("open_id")
            .build()
        )
        response = client.calendar.v4.calendar_event.get(request, option)
        if not response.success():
            if response.code == 404:
                return None
            self._check_response(response, "get_event")
        if not response.data or not response.data.event:
            return None
        return self._event_from_lark(response.data.event, cal_id)

    def create_event(
        self,
        *,
        calendar_id: str | None = None,
        title: str,
        start_at: str,
        end_at: str,
        timezone: str,
        description: str = "",
        location: str = "",
        attendees: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CalendarEvent:
        from lark_oapi.api.calendar.v4 import (
            CalendarEvent as LarkCalendarEvent,
        )
        from lark_oapi.api.calendar.v4 import (
            CreateCalendarEventRequest,
            EventLocation,
        )

        cal_id = self._resolve_calendar_id(calendar_id)
        client = self._build_lark_client()
        option = self._build_option()

        body = LarkCalendarEvent()
        body.summary = title
        body.description = description
        body.start_time = self._iso_to_timeinfo(start_at, timezone)
        body.end_time = self._iso_to_timeinfo(end_at, timezone)
        if location:
            loc = EventLocation()
            loc.name = location
            body.location = loc
        if attendees:
            body.attendees = [self._str_to_attendee(a) for a in attendees]

        request = (
            CreateCalendarEventRequest.builder()
            .calendar_id(cal_id)
            .user_id_type("open_id")
            .request_body(body)
            .build()
        )
        data = self._check_response(
            client.calendar.v4.calendar_event.create(request, option), "create_event"
        )
        if not data.event:
            raise CalendarError(CalendarErrorCode.API_ERROR, "create_event returned no event")
        return self._event_from_lark(data.event, cal_id)

    def update_event(
        self,
        *,
        calendar_id: str | None = None,
        event_id: str,
        fields: dict[str, Any],
    ) -> CalendarEvent | None:
        from lark_oapi.api.calendar.v4 import (
            CalendarEvent as LarkCalendarEvent,
        )
        from lark_oapi.api.calendar.v4 import (
            EventLocation,
            PatchCalendarEventRequest,
        )

        cal_id = self._resolve_calendar_id(calendar_id)
        existing = self.get_event(calendar_id=cal_id, event_id=event_id)
        if existing is None:
            return None

        tz = fields.get("timezone") or existing.timezone
        body = LarkCalendarEvent()
        if "title" in fields:
            body.summary = fields["title"]
        if "description" in fields:
            body.description = fields["description"]
        if "start_at" in fields:
            body.start_time = self._iso_to_timeinfo(fields["start_at"], tz)
        if "end_at" in fields:
            body.end_time = self._iso_to_timeinfo(fields["end_at"], tz)
        if "location" in fields:
            loc = EventLocation()
            loc.name = fields["location"]
            body.location = loc
        if "attendees" in fields and fields["attendees"] is not None:
            body.attendees = [self._str_to_attendee(a) for a in fields["attendees"]]

        client = self._build_lark_client()
        option = self._build_option()
        request = (
            PatchCalendarEventRequest.builder()
            .calendar_id(cal_id)
            .event_id(event_id)
            .user_id_type("open_id")
            .request_body(body)
            .build()
        )
        data = self._check_response(
            client.calendar.v4.calendar_event.patch(request, option), "update_event"
        )
        if not data.event:
            return None
        return self._event_from_lark(data.event, cal_id)

    def delete_event(self, *, calendar_id: str | None = None, event_id: str) -> bool:
        from lark_oapi.api.calendar.v4 import DeleteCalendarEventRequest

        cal_id = self._resolve_calendar_id(calendar_id)
        client = self._build_lark_client()
        option = self._build_option()
        request = (
            DeleteCalendarEventRequest.builder().calendar_id(cal_id).event_id(event_id).build()
        )
        response = client.calendar.v4.calendar_event.delete(request, option)
        if not response.success():
            if response.code == 404:
                return False
            self._check_response(response, "delete_event")
        return True
