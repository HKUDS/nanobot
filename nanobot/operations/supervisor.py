"""External ten-minute watchdog: observe live processes, never replay agent tools.

The native goal watchdog owns safe continuation under the gateway session lock.
This service checks that both the gateway and that watchdog remain alive, then
restarts a stopped/stuck gateway within a bounded, persistent restart budget.
"""

from __future__ import annotations

import argparse
import http.client
import json
import math
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from filelock import FileLock

from nanobot.operations.state import read_state, write_state

HEARTBEAT_FILE = "goal-recovery-heartbeat.json"
MAX_RESTARTS_PER_HOUR = 3
STARTUP_GRACE_SECONDS = 120


@dataclass(frozen=True)
class ServiceState:
    active: bool
    pid: int
    started_monotonic: float


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str


def decide(
    service: ServiceState, *, healthy: bool, heartbeat: dict[str, Any],
    recovery_enabled: bool, interval_seconds: int, now_monotonic: float,
) -> Decision:
    if not service.active or service.pid <= 0:
        return Decision("restart", "gateway_stopped")
    if now_monotonic - service.started_monotonic < STARTUP_GRACE_SECONDS:
        return Decision("wait", "gateway_starting")
    if not healthy:
        return Decision("restart", "gateway_unresponsive")
    if recovery_enabled:
        last_scan = heartbeat.get("monotonic_at")
        if (heartbeat.get("pid") != service.pid or not isinstance(last_scan, (int, float))
                or isinstance(last_scan, bool) or not math.isfinite(last_scan)
                or last_scan < service.started_monotonic
                or last_scan > now_monotonic + 30
                or now_monotonic - last_scan > interval_seconds * 2 + 30):
            return Decision("restart", "goal_watchdog_unresponsive")
    return Decision("healthy", "gateway_and_recovery_available")


def service_state(unit: str) -> ServiceState:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]*\.service", unit) is None:
        raise ValueError("invalid systemd service name")
    result = subprocess.run(
        ["systemctl", "show", unit,
         "--property=MainPID,ActiveState,ActiveEnterTimestampMonotonic,LoadState"],
        capture_output=True, text=True, timeout=10, check=True,
    )
    fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if fields.get("LoadState") != "loaded":
        raise ValueError("gateway service is not installed")
    return ServiceState(
        active=fields.get("ActiveState") in {"active", "activating", "reloading"},
        pid=int(fields.get("MainPID", "0")),
        started_monotonic=int(fields.get("ActiveEnterTimestampMonotonic", "0")) / 1_000_000,
    )


def health_probe(port: int) -> bool:
    # An operator probe of this host's explicit health listener, with no proxy,
    # DNS lookup, redirects, bootstrap secret, or third-party network request.
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("GET", "/health")
        response = connection.getresponse()
        payload: object = json.loads(response.read(8192))
        return (response.status == 200 and isinstance(payload, dict)
                and cast(dict[str, object], payload).get("ready") is True)
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def check(
    *, unit: str, state_path: Path, heartbeat_path: Path, port: int,
    recovery_enabled: bool, interval_seconds: int,
) -> dict[str, Any]:
    state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with FileLock(str(state_path) + ".lock", timeout=1):
        state = read_state(state_path)
        if state.get("paused") is True:
            return {"action": "paused", "reason": "operator_paused"}
        service = service_state(unit)
        healthy = health_probe(port) if service.active else False
        if service.active and not healthy:
            healthy = health_probe(port)  # Recheck a transient failure; never infer a dead handle.
        try:
            heartbeat = read_state(heartbeat_path)
        except (OSError, ValueError):
            heartbeat = {}
        decision = decide(
            service, healthy=healthy, heartbeat=heartbeat, recovery_enabled=recovery_enabled,
            interval_seconds=interval_seconds, now_monotonic=time.monotonic(),
        )
        now = time.time()
        raw_attempts = state.get("restart_attempts", [])
        if not isinstance(raw_attempts, list):
            raise ValueError("invalid supervisor restart history")
        attempts: list[float] = [float(value) for value in cast(list[object], raw_attempts)
                                 if isinstance(value, (int, float)) and math.isfinite(value)
                                 and value > now - 3600]
        if decision.action == "restart" and len(attempts) >= MAX_RESTARTS_PER_HOUR:
            decision = Decision("held", "restart_budget_exhausted")
        state.update(asdict(decision), checked_at=now, pid=service.pid, restart_attempts=attempts)
        if decision.action == "restart":
            attempts.append(now)
        # Commit the attempt BEFORE the external action, including if the process
        # dies after systemd accepts it. Re-entry cannot cause an unbounded loop.
        write_state(state_path, state)
        if decision.action == "restart":
            subprocess.run(["systemctl", "restart", "--no-block", unit],
                           check=True, capture_output=True, timeout=10)
        return state


def main() -> None:
    from nanobot.config.loader import load_config, set_config_path
    from nanobot.session.manager import SessionManager

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--unit", default="nanobot.service")
    control = parser.add_mutually_exclusive_group()
    control.add_argument("--pause", action="store_true")
    control.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    config_path = args.config.expanduser().resolve(strict=True)
    set_config_path(config_path)
    config = load_config(config_path)
    state_path = config_path.parent / "operations" / "supervisor.json"
    if args.pause or args.resume:
        state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with FileLock(str(state_path) + ".lock", timeout=1):
            state = read_state(state_path)
            state["paused"] = args.pause
            write_state(state_path, state)
        print(json.dumps({"paused": args.pause}))
        return
    sessions = SessionManager(config.workspace_path)
    print(json.dumps(check(
        unit=args.unit, state_path=state_path, heartbeat_path=sessions.sessions_dir / HEARTBEAT_FILE,
        port=config.gateway.port, recovery_enabled=config.gateway.goal_recovery.enabled,
        interval_seconds=config.gateway.goal_recovery.interval_seconds,
    )))


if __name__ == "__main__":
    main()
