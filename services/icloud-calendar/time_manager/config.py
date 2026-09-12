from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    nanobot_config_path: str = ""
    timezone: str = "Europe/Warsaw"
    scan_interval_seconds: int = 300
    lookback_days: int = 7
    horizon_days: int = 400
    state_path: str = "data/state.sqlite3"
    trigger_id: str = ""
    workspace_path: str = "/root/.nanobot/workspace"
    management_calendar: str = "auto"
    auto_manage_sleep: bool = False
    calendar_only: bool = True
    sleep_days_ahead: int = 14
    default_wake_time: str = "07:00"
    sleep_hours: float = 8.0
    briefing_minutes_after_wake: int = 20
    morning_preparation_minutes: int = 90
    quiet_mode: str = "sleep"
    initial_scan_notifications: bool = False

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        config_path = Path(path).expanduser().resolve()
        with config_path.open("rb") as handle:
            raw = tomllib.load(handle)
        allowed = set(cls.__dataclass_fields__)
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise ValueError(f"Nieznane pola konfiguracji: {', '.join(unknown)}")
        cfg = cls(**raw)
        if cfg.scan_interval_seconds < 60:
            raise ValueError("scan_interval_seconds nie może być mniejsze niż 60")
        if not 1 <= cfg.horizon_days <= 3660:
            raise ValueError("horizon_days musi mieścić się w zakresie 1..3660")
        if not 0 <= cfg.lookback_days <= 365:
            raise ValueError("lookback_days musi mieścić się w zakresie 0..365")
        if not 1 <= cfg.sleep_days_ahead <= 60:
            raise ValueError("sleep_days_ahead musi mieścić się w zakresie 1..60")
        if not 0 <= cfg.morning_preparation_minutes <= 360:
            raise ValueError("morning_preparation_minutes musi mieścić się w zakresie 0..360")
        if not 0 <= cfg.briefing_minutes_after_wake <= 180:
            raise ValueError("briefing_minutes_after_wake musi mieścić się w zakresie 0..180")
        if cfg.quiet_mode not in {"sleep", "off"}:
            raise ValueError("quiet_mode musi mieć wartość sleep albo off")
        if not 4 <= cfg.sleep_hours <= 12:
            raise ValueError("sleep_hours musi mieścić się w zakresie 4..12")
        from .core import parse_clock
        parse_clock(cfg.default_wake_time)
        if cfg.auto_manage_sleep and not cfg.calendar_only and cfg.management_calendar == "auto":
            raise ValueError("auto_manage_sleep wymaga dedykowanej nazwy management_calendar")
        return cfg

    def resolve_state_path(self, config_path: str | Path) -> Path:
        value = Path(self.state_path).expanduser()
        if value.is_absolute():
            return value
        return Path(config_path).expanduser().resolve().parent.parent / value
