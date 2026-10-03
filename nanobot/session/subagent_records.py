"""Durable task observations stored with their owning parent conversation."""

from __future__ import annotations

import math
import time
from typing import Any, cast

from loguru import logger
from pydantic import TypeAdapter, ValidationError

from nanobot.agent.subagent_status import SubagentStatus
from nanobot.session.manager import SessionManager

SUBAGENT_RECORDS_KEY = "subagent_tasks"
_STATUS = TypeAdapter(SubagentStatus)
_ACTIVE_STATES = {"queued", "running", "stopping"}


class SubagentRecordsError(ValueError):
    """The parent session's task records could not be read safely."""


class SubagentRecords:
    """Save observations, never executable sessions, prompts, or tool resources."""

    def __init__(self, sessions: SessionManager):
        self.sessions = sessions

    def exists(self, owner: str) -> bool:
        return self.sessions.get_cached(owner) is not None or self.sessions.read_session_metadata(owner) is not None

    def load(self, owner: str) -> dict[str, SubagentStatus]:
        try:
            raw: object = self.sessions.read_subagent_records(owner)
        except ValueError as exc:
            raise SubagentRecordsError("invalid task history") from exc
        if raw is None:
            return {}
        envelope = cast(dict[str, object], raw)
        entries = envelope.get("tasks")
        if envelope.get("version") != 1 or not isinstance(entries, list):
            raise SubagentRecordsError("unsupported task history")
        result: dict[str, SubagentStatus] = {}
        now = time.monotonic()
        for entry in cast(list[object], entries):
            if not isinstance(entry, dict):
                raise SubagentRecordsError("invalid task history entry")
            value = cast(dict[str, object], entry)
            elapsed = value.get("elapsed_seconds")
            if (not isinstance(elapsed, (int, float)) or isinstance(elapsed, bool)
                    or not math.isfinite(elapsed) or elapsed < 0):
                raise SubagentRecordsError("invalid task duration")
            try:
                status = _STATUS.validate_python({
                    **value, "started_at": now - elapsed,
                    "finished_at": now if value.get("completed_at") is not None else None,
                })
            except ValidationError as exc:
                raise SubagentRecordsError("invalid task history entry") from exc
            if status.owner != owner or status.task_id in result:
                raise SubagentRecordsError("invalid task ownership")
            result[status.task_id] = status
        return result

    @staticmethod
    def _payload(statuses: dict[str, SubagentStatus]) -> dict[str, Any]:
        return {
            "version": 1,
            "tasks": [
                {
                    **_STATUS.dump_python(status, mode="json", exclude={"started_at", "finished_at"}),
                    "elapsed_seconds": status.as_dict()["elapsed_seconds"],
                }
                for status in statuses.values()
            ],
        }

    def save(self, status: SubagentStatus, *, create: bool = False, fsync: bool = False) -> None:
        session = self.sessions.get_cached(status.owner)
        if session is not None and not session.policy.persist:
            return
        statuses = self.load(status.owner)
        statuses[status.task_id] = status
        if create and self.sessions.read_session_metadata(status.owner) is None:
            parent = self.sessions.get_or_create(status.owner)
            self.sessions.save(parent, fsync=fsync)
        # A late completion must not resurrect a deleted parent session.
        self.sessions.save_subagent_records(status.owner, self._payload(statuses), fsync=fsync)

    def interrupt_pending(self) -> None:
        """At host startup, seal abandoned work without executing or announcing it."""
        for parent in self.sessions.list_sessions():
            owner: str = parent["key"]
            try:
                statuses = self.load(owner)
                pending = [status for status in statuses.values() if status.state in _ACTIVE_STATES]
                for status in pending:
                    status.state = status.phase = "interrupted"
                    status.stop_reason = "host_restarted"
                    status.finished_at = time.monotonic()
                    status.completed_at = time.time()
                    status.partial = bool(status.result)
                    status.tool_events = []
                    status.receipts = {
                        key: "undelivered" if receipt == "accepted" else receipt
                        for key, receipt in status.receipts.items()
                    }
                if pending:
                    self.sessions.save_subagent_records(
                        owner, self._payload(statuses), fsync=True,
                    )
            except (OSError, SubagentRecordsError):
                logger.exception("Could not recover subagent records for {}", owner)
