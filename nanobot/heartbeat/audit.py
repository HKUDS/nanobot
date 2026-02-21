"""Heartbeat audit system for tracking periodic agent runs."""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger


@dataclass
class HeartbeatRun:
    """Record of a single heartbeat execution."""

    id: str
    started_at: datetime
    completed_at: datetime | None = None
    status: str = "running"  # running, completed, error, skipped
    prompt: str = ""
    response: str = ""
    tasks_found: bool = False
    tool_calls_count: int = 0
    error: str = ""

    @property
    def duration_seconds(self) -> float:
        """Get duration in seconds."""
        if self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status,
            "prompt": self.prompt,
            "response": self.response[:500] if self.response else "",  # Truncate for storage
            "tasks_found": self.tasks_found,
            "tool_calls_count": self.tool_calls_count,
            "error": self.error,
            "duration_seconds": self.duration_seconds,
        }


class HeartbeatAuditLog:
    """Manages audit log for heartbeat runs."""

    def __init__(self, workspace: Path, max_entries: int = 100):
        self.workspace = workspace
        self.max_entries = max_entries
        self.audit_file = workspace / ".nanobot" / "heartbeat_audit.json"
        self._runs: list[HeartbeatRun] = []
        self._load()

    def _load(self) -> None:
        """Load audit log from file."""
        if self.audit_file.exists():
            try:
                with open(self.audit_file, "r") as f:
                    data = json.load(f)
                    for entry in data.get("runs", []):
                        run = HeartbeatRun(
                            id=entry["id"],
                            started_at=datetime.fromisoformat(entry["started_at"]),
                            completed_at=datetime.fromisoformat(entry["completed_at"])
                            if entry.get("completed_at")
                            else None,
                            status=entry.get("status", "unknown"),
                            prompt=entry.get("prompt", ""),
                            response=entry.get("response", ""),
                            tasks_found=entry.get("tasks_found", False),
                            tool_calls_count=entry.get("tool_calls_count", 0),
                            error=entry.get("error", ""),
                        )
                        self._runs.append(run)
            except Exception as e:
                logger.warning(f"Failed to load heartbeat audit log: {e}")

    def _save(self) -> None:
        """Save audit log to file."""
        try:
            self.audit_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "last_updated": datetime.now().isoformat(),
                "runs": [run.to_dict() for run in self._runs[-self.max_entries :]],
            }
            with open(self.audit_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save heartbeat audit log: {e}")

    def start_run(self, run_id: str, prompt: str) -> HeartbeatRun:
        """Start tracking a new heartbeat run."""
        run = HeartbeatRun(
            id=run_id,
            started_at=datetime.now(),
            prompt=prompt,
        )
        self._runs.append(run)
        # Trim old entries
        if len(self._runs) > self.max_entries:
            self._runs = self._runs[-self.max_entries :]
        return run

    def complete_run(
        self,
        run: HeartbeatRun,
        response: str,
        tasks_found: bool,
        tool_calls_count: int = 0,
    ) -> None:
        """Mark a run as completed."""
        run.completed_at = datetime.now()
        run.status = "completed"
        run.response = response
        run.tasks_found = tasks_found
        run.tool_calls_count = tool_calls_count
        self._save()

    def fail_run(self, run: HeartbeatRun, error: str) -> None:
        """Mark a run as failed."""
        run.completed_at = datetime.now()
        run.status = "error"
        run.error = error
        self._save()

    def skip_run(self, run_id: str, reason: str = "No tasks") -> None:
        """Record a skipped run (no tasks found)."""
        run = HeartbeatRun(
            id=run_id,
            started_at=datetime.now(),
            completed_at=datetime.now(),
            status="skipped",
            response=reason,
            tasks_found=False,
        )
        self._runs.append(run)
        if len(self._runs) > self.max_entries:
            self._runs = self._runs[-self.max_entries :]
        self._save()

    def get_recent_runs(self, count: int = 10) -> list[HeartbeatRun]:
        """Get recent heartbeat runs."""
        return self._runs[-count:]

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about heartbeat runs."""
        if not self._runs:
            return {
                "total_runs": 0,
                "completed": 0,
                "errors": 0,
                "skipped": 0,
                "tasks_executed": 0,
            }

        total = len(self._runs)
        completed = sum(1 for r in self._runs if r.status == "completed")
        errors = sum(1 for r in self._runs if r.status == "error")
        skipped = sum(1 for r in self._runs if r.status == "skipped")
        tasks_executed = sum(1 for r in self._runs if r.tasks_found)

        return {
            "total_runs": total,
            "completed": completed,
            "errors": errors,
            "skipped": skipped,
            "tasks_executed": tasks_executed,
            "avg_duration_seconds": sum(r.duration_seconds for r in self._runs) / total,
        }

    def format_recent_runs(self, count: int = 5) -> str:
        """Format recent runs for display."""
        runs = self.get_recent_runs(count)
        if not runs:
            return "No heartbeat runs recorded yet."

        lines = ["📊 **Recent Heartbeat Runs**\n"]

        for run in reversed(runs):  # Most recent first
            # Status emoji
            emoji = {"completed": "✅", "error": "❌", "skipped": "⏭️", "running": "⏳"}.get(
                run.status, "❓"
            )

            # Format time
            time_str = run.started_at.strftime("%Y-%m-%d %H:%M")

            # Duration
            duration = f"({run.duration_seconds:.1f}s)" if run.duration_seconds > 0 else ""

            # Tasks indicator
            tasks = f"• {run.tool_calls_count} tools" if run.tool_calls_count > 0 else ""

            lines.append(f"{emoji} **{time_str}** {duration} {tasks}")

            if run.status == "error" and run.error:
                lines.append(f"   ❌ {run.error[:50]}...")
            elif run.tasks_found and run.response:
                # Show first line of response
                first_line = run.response.split("\n")[0][:60]
                lines.append(f"   📝 {first_line}...")

        # Add stats
        stats = self.get_stats()
        lines.extend(
            [
                "",
                f"📈 **Stats**: {stats['total_runs']} runs | {stats['tasks_executed']} with tasks | {stats['errors']} errors",
            ]
        )

        return "\n".join(lines)
