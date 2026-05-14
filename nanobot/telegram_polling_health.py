"""Telegram polling liveness tracking for long-polling bots."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from telegram.request import HTTPXRequest

_DEFAULT_STATE_PATH = "/tmp/nanobot-telegram-health.json"


def _env_path(name: str, default: str) -> Path:
    return Path(os.getenv(name, default)).expanduser()


def _format_error(exc: Exception) -> str:
    text = str(exc).strip()
    return text or exc.__class__.__name__


@dataclass(slots=True)
class TelegramHealthState:
    """Track the last successful Telegram polling cycle in a small JSON file."""

    path: Path = field(default_factory=lambda: _env_path("NANOBOT_TELEGRAM_HEALTH_PATH", _DEFAULT_STATE_PATH))
    _last_ok: float = 0.0
    _last_error: str = ""
    _consecutive_errors: int = 0

    def mark_starting(self, detail: str = "starting") -> None:
        self._write(status="starting", detail=detail)

    def mark_ok(self, detail: str = "getUpdates ok") -> None:
        self._last_ok = time.time()
        self._last_error = ""
        self._consecutive_errors = 0
        self._write(status="ok", detail=detail)

    def mark_error(self, exc: Exception | str) -> None:
        self._consecutive_errors += 1
        self._last_error = _format_error(exc) if isinstance(exc, Exception) else str(exc)
        self._write(status="error", detail=self._last_error)

    def mark_stopped(self, detail: str = "stopped") -> None:
        self._write(status="stopped", detail=detail)

    def _write(self, *, status: str, detail: str) -> None:
        now = time.time()
        last_ok = self._last_ok or None
        payload: dict[str, Any] = {
            "status": status,
            "detail": detail,
            "updated_at": now,
            "pid": os.getpid(),
            "consecutive_errors": self._consecutive_errors,
        }
        if last_ok is not None:
            payload["last_ok"] = last_ok
            payload["last_ok_age_s"] = round(max(0.0, now - last_ok), 3)
        if self._last_error:
            payload["last_error"] = self._last_error

        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_name(f".{self.path.name}.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(self.path)


class TelegramPollingHealthRequest(HTTPXRequest):
    """HTTPX request object that records successful/failed getUpdates cycles."""

    def __init__(self, *args: Any, health_state: TelegramHealthState | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._health_state = health_state or TelegramHealthState()

    async def do_request(
        self,
        url: str,
        method: str,
        request_data: Any = None,
        read_timeout: float | None = None,
        write_timeout: float | None = None,
        connect_timeout: float | None = None,
        pool_timeout: float | None = None,
    ) -> Any:
        try:
            result = await super().do_request(
                url,
                method,
                request_data=request_data,
                read_timeout=read_timeout,
                write_timeout=write_timeout,
                connect_timeout=connect_timeout,
                pool_timeout=pool_timeout,
            )
        except Exception as exc:
            self._health_state.mark_error(exc)
            raise
        else:
            self._health_state.mark_ok()
            return result
