"""Audit logging for tool executions.

Appends one JSON line per tool call to ~/.nanobot/workspace/audit.jsonl.
Each line records the timestamp, tool name, sanitised arguments, result
status, session_id, and originating channel so that operators can review
what the agent did and when.

Usage
-----
    from nanobot.agent.tools.audit import AuditLogger

    logger = AuditLogger()
    await logger.log(
        tool_name="exec",
        arguments={"command": "ls /tmp"},
        result_status="ok",
        session_id="discord:123456",
        channel="discord",
    )

    recent = logger.query(limit=20)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Argument-level secret redaction
# ---------------------------------------------------------------------------

# Field names whose values should be replaced with the placeholder below.
_SECRET_FIELDS: frozenset[str] = frozenset(
    {
        "token",
        "api_key",
        "apikey",
        "api_token",
        "password",
        "passwd",
        "secret",
        "bridge_token",
        "access_token",
        "app_token",
        "bot_token",
        "claw_token",
        "imap_password",
        "smtp_password",
        "encrypt_key",
        "verification_token",
        "client_secret",
    }
)

_REDACTED = "[REDACTED]"


def _redact(value: Any, key: str | None = None) -> Any:
    """Recursively redact known secret fields from a value.

    Parameters
    ----------
    value:
        The value to inspect (string, dict, list, or other).
    key:
        The dict key that produced this value; if it matches a known secret
        field name, the entire value is replaced with ``[REDACTED]``.
    """
    if key is not None:
        normalised = key.lower().replace("-", "_")
        if normalised in _SECRET_FIELDS:
            return _REDACTED

    if isinstance(value, dict):
        return {k: _redact(v, k) for k, v in value.items()}

    if isinstance(value, list):
        return [_redact(item) for item in value]

    return value


def _sanitise_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *arguments* with secret values replaced."""
    return _redact(arguments)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# AuditLogger
# ---------------------------------------------------------------------------


class AuditLogger:
    """Append-only JSONL audit log for tool executions.

    Parameters
    ----------
    log_path:
        Path to the JSONL file.  Defaults to
        ``~/.nanobot/workspace/audit.jsonl``.
    """

    def __init__(self, log_path: Path | None = None) -> None:
        if log_path is None:
            log_path = Path.home() / ".nanobot" / "workspace" / "audit.jsonl"
        self._log_path = log_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        result_status: str,
        session_id: str = "",
        channel: str = "",
        error: str | None = None,
        duration_ms: float | None = None,
    ) -> None:
        """Append one audit entry to the log file (synchronous).

        Parameters
        ----------
        tool_name:
            Name of the tool that was called (e.g. ``"exec"``).
        arguments:
            Raw arguments dict passed to the tool.  Secret fields are
            automatically redacted before writing.
        result_status:
            ``"ok"`` on success, ``"error"`` on failure, ``"blocked"`` when
            the guard rejected the call.
        session_id:
            The session key (e.g. ``"discord:123456789"``).
        channel:
            The inbound channel name (e.g. ``"discord"``, ``"telegram"``).
        error:
            Optional error message when *result_status* is not ``"ok"``.
        duration_ms:
            Optional wall-clock duration of the tool execution in
            milliseconds.
        """
        entry = self._build_entry(
            tool_name=tool_name,
            arguments=arguments,
            result_status=result_status,
            session_id=session_id,
            channel=channel,
            error=error,
            duration_ms=duration_ms,
        )
        self._append(entry)

    def log_llm_call(
        self,
        *,
        session_id: str = "",
        channel: str = "",
        model: str = "",
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        latency_ms: float | None = None,
        tool_calls_made: int = 0,
        ttft_ms: float | None = None,
    ) -> None:
        """Append one llm_call event to the audit log.

        Records per-iteration LLM usage so token counts and latency
        are durable beyond journald rotation.
        """
        entry: dict[str, Any] = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "event_type": "llm_call",
            "session_id": session_id,
            "channel": channel,
            "model": model,
            "pid": os.getpid(),
        }
        if tokens_in is not None:
            entry["tokens_in"] = tokens_in
        if tokens_out is not None:
            entry["tokens_out"] = tokens_out
        if latency_ms is not None:
            entry["latency_ms"] = round(latency_ms, 2)
        if tool_calls_made:
            entry["tool_calls_made"] = tool_calls_made
        if ttft_ms is not None:
            entry["ttft_ms"] = round(ttft_ms, 2)
        self._append(entry)

    def query(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return the *limit* most-recent audit entries.

        Parameters
        ----------
        limit:
            Maximum number of entries to return.  Defaults to 50.

        Returns
        -------
        list[dict]:
            Entries in chronological order (oldest first), up to *limit*
            entries.  Returns an empty list if the log file does not exist
            or is unreadable.
        """
        if not self._log_path.exists():
            return []

        entries: list[dict[str, Any]] = []
        try:
            with open(self._log_path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        # Corrupt line — skip silently.
                        continue
        except OSError:
            return []

        return entries[-limit:]

    def query_by_tool(self, tool_name: str, limit: int = 50) -> list[dict[str, Any]]:
        """Return the *limit* most-recent entries for a specific tool.

        Parameters
        ----------
        tool_name:
            Name of the tool to filter by.
        limit:
            Maximum number of entries to return.
        """
        all_entries = self.query(limit=max(limit * 10, 500))
        matching = [e for e in all_entries if e.get("tool_name") == tool_name]
        return matching[-limit:]

    def query_by_session(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Return the *limit* most-recent entries for a specific session.

        Parameters
        ----------
        session_id:
            Session key to filter by (e.g. ``"discord:123456789"``).
        limit:
            Maximum number of entries to return.
        """
        all_entries = self.query(limit=max(limit * 10, 500))
        matching = [e for e in all_entries if e.get("session_id") == session_id]
        return matching[-limit:]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_entry(
        *,
        tool_name: str,
        arguments: dict[str, Any],
        result_status: str,
        session_id: str,
        channel: str,
        error: str | None,
        duration_ms: float | None,
    ) -> dict[str, Any]:
        """Construct the dict that will be serialised to one JSONL line."""
        entry: dict[str, Any] = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "tool_name": tool_name,
            "arguments": _sanitise_arguments(arguments),
            "result_status": result_status,
            "session_id": session_id,
            "channel": channel,
            "pid": os.getpid(),
        }
        if error is not None:
            entry["error"] = error
        if duration_ms is not None:
            entry["duration_ms"] = round(duration_ms, 2)
        return entry

    def _append(self, entry: dict[str, Any]) -> None:
        """Write *entry* as a single JSON line to the log file.

        Creates parent directories if they do not exist.  Errors are
        printed to stderr rather than raised so that audit failures never
        break tool execution.
        """
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(entry, ensure_ascii=False) + "\n"
            with open(self._log_path, "a", encoding="utf-8") as fh:
                fh.write(line)
        except Exception as exc:  # pragma: no cover
            # Audit must not crash the agent.
            import sys
            print(f"[AuditLogger] Failed to write audit entry: {exc}", file=sys.stderr)
