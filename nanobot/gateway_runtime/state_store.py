"""Filesystem-backed state store for gateway runtime metadata."""

from __future__ import annotations

import json
from pathlib import Path

from nanobot.config.loader import get_data_dir
from nanobot.gateway_runtime.models import GatewayRuntimeState


class GatewayStateStore:
    """Read and write gateway runtime files under ~/.nanobot."""

    def __init__(self, data_dir: Path | None = None):
        # Runtime filesystem layout:
        #   <data>/run/gateway.pid
        #   <data>/run/gateway.state.json
        #   <data>/run/gateway.lock   (reserved for future single-instance lock)
        #   <data>/logs/gateway.log
        base_dir = data_dir or get_data_dir()
        self.run_dir = base_dir / "run"
        self.logs_dir = base_dir / "logs"
        self.pid_path = self.run_dir / "gateway.pid"
        self.state_path = self.run_dir / "gateway.state.json"
        self.lock_path = self.run_dir / "gateway.lock"

    def write_state(self, payload: GatewayRuntimeState) -> None:
        """Persist structured runtime metadata (mode/reason/timestamps, etc.)."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        with self.state_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

    def read_state(self) -> GatewayRuntimeState | None:
        """Load runtime state; self-heal by removing corrupted state files."""
        if not self.state_path.exists():
            return None
        try:
            with self.state_path.open(encoding="utf-8") as handle:
                loaded = json.load(handle)
        except (json.JSONDecodeError, OSError, ValueError):
            self.state_path.unlink(missing_ok=True)
            return None
        if isinstance(loaded, dict):
            return loaded
        return None

    def write_pid(self, pid: int) -> None:
        """Persist process id for managed-mode status checks."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.pid_path.write_text(str(pid), encoding="utf-8")

    def read_pid(self) -> int | None:
        """Read process id when present and valid."""
        if not self.pid_path.exists():
            return None
        try:
            return int(self.pid_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    def clear_pid(self) -> None:
        """Clear recorded pid when process exits or state resets."""
        self.pid_path.unlink(missing_ok=True)

    def resolve_log_path(self) -> Path:
        """Return standard gateway log path, creating log directory if needed."""
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        return self.logs_dir / "gateway.log"
