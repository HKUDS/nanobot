import json
import os
import subprocess
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "nanobot" / "telegram_healthcheck.sh"


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _run_healthcheck(tmp_path: Path, *, config: dict, telegram: dict | None, runtime: dict | None):
    config_path = tmp_path / "config.json"
    telegram_path = tmp_path / "telegram-health.json"
    runtime_path = tmp_path / "runtime-health.json"
    _write_json(config_path, config)
    if telegram is not None:
        _write_json(telegram_path, telegram)
    if runtime is not None:
        _write_json(runtime_path, runtime)

    env = {
        **os.environ,
        "NANOBOT_HEALTHCHECK_CMDLINE": f"nanobot gateway --config {config_path}",
        "NANOBOT_HEALTHCHECK_CONFIG_PATH": str(config_path),
        "NANOBOT_TELEGRAM_HEALTH_PATH": str(telegram_path),
        "NANOBOT_RUNTIME_HEALTH_PATH": str(runtime_path),
        "NANOBOT_TELEGRAM_HEALTH_MAX_AGE_S": "120",
        "NANOBOT_RUNTIME_HEALTH_AGENT_MAX_AGE_S": "180",
        "NANOBOT_RUNTIME_HEALTH_DISPATCH_MAX_AGE_S": "900",
        "NANOBOT_RUNTIME_HEALTH_SEND_MAX_AGE_S": "180",
    }
    return subprocess.run(
        ["sh", str(SCRIPT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_shell_healthcheck_accepts_fresh_polling_and_runtime_state(tmp_path: Path) -> None:
    now = time.time()

    result = _run_healthcheck(
        tmp_path,
        config={"channels": {"telegram": {"enabled": True}}},
        telegram={"last_ok": now},
        runtime={"last_agent_tick": now, "active_dispatches": 0, "outbound_active": 0},
    )

    assert result.returncode == 0
    assert "healthy:" in result.stdout


def test_shell_healthcheck_fails_when_dispatch_is_stuck(tmp_path: Path) -> None:
    now = time.time()

    result = _run_healthcheck(
        tmp_path,
        config={"channels": {"telegram": {"enabled": True}}},
        telegram={"last_ok": now},
        runtime={
            "last_agent_tick": now,
            "active_dispatches": 1,
            "oldest_dispatch_started_at": now - 901,
            "outbound_active": 0,
        },
    )

    assert result.returncode == 1
    assert "dispatch has been active too long" in result.stdout


def test_shell_healthcheck_skips_telegram_state_when_telegram_disabled(tmp_path: Path) -> None:
    now = time.time()

    result = _run_healthcheck(
        tmp_path,
        config={"channels": {"telegram": {"enabled": False}}},
        telegram=None,
        runtime={"last_agent_tick": now, "active_dispatches": 0, "outbound_active": 0},
    )

    assert result.returncode == 0
