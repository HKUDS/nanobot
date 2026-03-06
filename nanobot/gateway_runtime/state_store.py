"""Filesystem-backed state store for gateway runtime metadata."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from nanobot.config.loader import get_data_dir
from nanobot.gateway_runtime.models import GatewayRuntimeState


class GatewayStateStore:
    """Read and write gateway runtime files under ~/.nanobot."""

    def __init__(self, data_dir: Path | None = None, instance_key: str | None = None):
        # Runtime filesystem layout:
        #   <data>/run/gateway[.<instance>].pid
        #   <data>/run/gateway[.<instance>].state.json
        #   <data>/run/gateway[.<instance>].lock   (reserved for future lock)
        #   <data>/logs/gateway[.<instance>].log
        base_dir = data_dir or get_data_dir()
        self.run_dir = base_dir / "run"
        self.logs_dir = base_dir / "logs"
        suffix = f".{_safe_instance_suffix(instance_key)}" if instance_key else ""
        self.pid_path = self.run_dir / f"gateway{suffix}.pid"
        self.state_path = self.run_dir / f"gateway{suffix}.state.json"
        self.lock_path = self.run_dir / f"gateway{suffix}.lock"
        self.log_path = self.logs_dir / f"gateway{suffix}.log"

    def write_state(self, payload: GatewayRuntimeState) -> None:
        """Persist structured runtime metadata (mode/reason/timestamps, etc.)."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        # Write to a temp file in the same directory, then atomically swap.
        fd, tmp_name = tempfile.mkstemp(
            prefix="gateway.state.",
            suffix=".tmp",
            dir=self.run_dir,
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            tmp_path.replace(self.state_path)
        finally:
            tmp_path.unlink(missing_ok=True)

    def read_state(self) -> GatewayRuntimeState | None:
        """Load runtime state; treat parse errors as transient read failures."""
        if not self.state_path.exists():
            return None
        try:
            with self.state_path.open(encoding="utf-8") as handle:
                loaded = json.load(handle)
        except (json.JSONDecodeError, OSError, ValueError):
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
        return self.log_path

    def read_log_tail(self, tail: int = 200) -> list[str]:
        """Read last N lines from gateway log file."""
        if tail <= 0:
            return []
        log_path = self.resolve_log_path()
        if not log_path.exists():
            return []
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        return lines[-tail:]


def build_gateway_instance_key(
    *,
    workspace: str | None = None,
    config_path: str | None = None,
) -> str | None:
    """Build a deterministic instance key from gateway-scoping CLI inputs."""
    if not workspace and not config_path:
        return None
    ws = _normalize_optional_path(workspace)
    cfg = _normalize_optional_path(config_path)
    raw = f"workspace={ws}|config={cfg}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _normalize_optional_path(raw: str | None) -> str:
    if raw is None:
        return ""
    return str(Path(raw).expanduser())


def _safe_instance_suffix(raw: str) -> str:
    # Instance keys are expected to be hex-ish; keep filenames safe regardless.
    return "".join(ch for ch in raw if ch.isalnum() or ch in {"-", "_", "."}) or "default"
