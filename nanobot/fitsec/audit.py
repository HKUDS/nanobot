"""
FIT-Sec Audit Logger
====================
Append-only event stream for tool call decisions and executions.
"""
from __future__ import annotations
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .types import (
    AuditEntry,
    PolicyDecision,
    ToolCall,
    ToolManifest,
)


class AuditLogger:
    """
    Append-only audit log for all tool call decisions.

    Every decision is logged with:
    - Requested action
    - Ω-level
    - Policy decision + rationale
    - Gate metrics snapshot
    - Execution result or error
    """

    def __init__(
        self,
        log_path: Optional[Path] = None,
        in_memory: bool = False,
    ):
        self._log_path = log_path
        self._in_memory = in_memory
        self._entries: List[AuditEntry] = []

        # Ensure log directory exists
        if log_path and not in_memory:
            log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        tool_call: ToolCall,
        manifest: Optional[ToolManifest],
        policy_decision: PolicyDecision,
        executed: bool,
        result: Optional[Any] = None,
        error: Optional[str] = None,
    ) -> AuditEntry:
        """Log a tool call decision and outcome."""
        entry = AuditEntry(
            entry_id=str(uuid.uuid4()),
            tool_call=tool_call,
            manifest=manifest,
            policy_decision=policy_decision,
            executed=executed,
            result=result,
            error=error,
            timestamp=time.time(),
        )

        self._entries.append(entry)

        if self._log_path and not self._in_memory:
            self._append_to_file(entry)

        return entry

    def _append_to_file(self, entry: AuditEntry) -> None:
        """Append entry to JSONL file."""
        record = self._entry_to_dict(entry)
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _entry_to_dict(self, entry: AuditEntry) -> Dict[str, Any]:
        """Convert entry to serializable dict."""
        return {
            "entry_id": entry.entry_id,
            "timestamp": entry.timestamp,
            "timestamp_iso": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(entry.timestamp)
            ),
            "tool_call": {
                "tool_id": entry.tool_call.tool_id,
                "action": entry.tool_call.action,
                "args": entry.tool_call.args,
            },
            "manifest": entry.manifest.to_dict() if entry.manifest else None,
            "decision": entry.policy_decision.to_dict(),
            "executed": entry.executed,
            "result_type": type(entry.result).__name__ if entry.result else None,
            "error": entry.error,
        }

    def get_entries(
        self,
        limit: Optional[int] = None,
        tool_id: Optional[str] = None,
        decision_filter: Optional[str] = None,
    ) -> List[AuditEntry]:
        """Query audit entries."""
        entries = self._entries

        if tool_id:
            entries = [e for e in entries if e.tool_call.tool_id == tool_id]

        if decision_filter:
            entries = [
                e for e in entries
                if e.policy_decision.decision.name == decision_filter
            ]

        if limit:
            entries = entries[-limit:]

        return entries

    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics."""
        total = len(self._entries)
        if total == 0:
            return {"total": 0}

        allowed = sum(
            1 for e in self._entries
            if e.policy_decision.decision.name == "ALLOW"
        )
        denied = sum(
            1 for e in self._entries
            if e.policy_decision.decision.name == "DENY"
        )
        executed = sum(1 for e in self._entries if e.executed)
        errors = sum(1 for e in self._entries if e.error)

        by_omega = {}
        for e in self._entries:
            omega = e.policy_decision.omega_level.name
            by_omega[omega] = by_omega.get(omega, 0) + 1

        return {
            "total": total,
            "allowed": allowed,
            "denied": denied,
            "executed": executed,
            "errors": errors,
            "by_omega_level": by_omega,
        }

    def export_jsonl(self, path: Path) -> None:
        """Export all entries to JSONL file."""
        with open(path, "w", encoding="utf-8") as f:
            for entry in self._entries:
                record = self._entry_to_dict(entry)
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def clear(self) -> None:
        """Clear in-memory entries (does not affect file log)."""
        self._entries = []
