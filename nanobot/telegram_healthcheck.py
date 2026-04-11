"""Docker healthcheck for Telegram long-polling liveness."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

_DEFAULT_STATE_PATH = "/tmp/nanobot-telegram-health.json"
_DEFAULT_CONFIG_PATH = "/root/.nanobot/config.json"
_DEFAULT_MAX_AGE_S = 120.0


def _env_path(name: str, default: str) -> Path:
    return Path(os.getenv(name, default)).expanduser()


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _proc1_cmdline() -> list[str]:
    try:
        raw = Path("/proc/1/cmdline").read_bytes()
    except OSError:
        return []
    return [part.decode("utf-8", errors="ignore") for part in raw.split(b"\x00") if part]


def _is_gateway_process(args: list[str]) -> bool:
    return any(arg == "gateway" or arg.endswith("/gateway") for arg in args)


def _config_path_from_args(args: list[str]) -> Path:
    env_override = os.getenv("NANOBOT_HEALTHCHECK_CONFIG_PATH")
    if env_override:
        return Path(env_override).expanduser()

    for index, arg in enumerate(args):
        if arg in {"--config", "-c"} and index + 1 < len(args):
            return Path(args[index + 1]).expanduser()
        if arg.startswith("--config="):
            return Path(arg.split("=", 1)[1]).expanduser()
    return Path(_DEFAULT_CONFIG_PATH).expanduser()


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _telegram_enabled(config_path: Path) -> bool:
    data = _load_json(config_path)
    if not data:
        return False
    channels = data.get("channels")
    if not isinstance(channels, dict):
        return False
    telegram = channels.get("telegram")
    if not isinstance(telegram, dict):
        return False
    return bool(telegram.get("enabled", False))


def run_healthcheck() -> int:
    cmdline = _proc1_cmdline()
    if cmdline and not _is_gateway_process(cmdline):
        print("healthy: nanobot is not running in gateway mode")
        return 0

    config_path = _config_path_from_args(cmdline)
    if not _telegram_enabled(config_path):
        print(f"healthy: telegram channel is disabled in {config_path}")
        return 0

    state_path = _env_path("NANOBOT_TELEGRAM_HEALTH_PATH", _DEFAULT_STATE_PATH)
    state = _load_json(state_path)
    if not state:
        print(f"unhealthy: telegram polling state file is missing or unreadable: {state_path}")
        return 1

    max_age_s = _env_float("NANOBOT_TELEGRAM_HEALTH_MAX_AGE_S", _DEFAULT_MAX_AGE_S)
    last_ok = state.get("last_ok")
    if not isinstance(last_ok, (float, int)):
        print(f"unhealthy: telegram polling has not reported a successful cycle yet: {state_path}")
        return 1

    age_s = max(0.0, time.time() - float(last_ok))
    if age_s > max_age_s:
        detail = state.get("last_error") or state.get("detail") or state.get("status") or "stale"
        print(f"unhealthy: last successful Telegram poll was {age_s:.1f}s ago ({detail})")
        return 1

    print(f"healthy: last successful Telegram poll was {age_s:.1f}s ago")
    return 0


def main() -> int:
    return run_healthcheck()


if __name__ == "__main__":
    raise SystemExit(main())
