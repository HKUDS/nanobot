"""Private child sessions for subagent transcripts and task observations."""

from __future__ import annotations

import math
import time
from typing import Any, cast

from loguru import logger
from pydantic import TypeAdapter, ValidationError

from nanobot.agent.subagent_status import SubagentSessionError as SubagentSessionError
from nanobot.agent.subagent_status import SubagentStatus
from nanobot.session.manager import Session, SessionManager, SessionPolicy
from nanobot.session.sqlite_store import SessionConflictError
from nanobot.session.types import PARENT_SESSION_KEY, SESSION_TYPE_KEY, SessionType

SUBAGENT = SessionType("subagent", needs_handle=False, public_history=False)
TASK_METADATA_KEY = "subagent_task"
_STATUS = TypeAdapter(SubagentStatus)
_ACTIVE_STATES = {"queued", "running", "stopping"}


class SubagentSessions:
    """Use the common session store; keep task access owned by the parent."""

    def __init__(self, sessions: SessionManager):
        self.sessions = sessions
        sessions.types.register(SUBAGENT)

    @staticmethod
    def key(task_id: str) -> str:
        return f"subagent:{task_id}"

    def exists(self, owner: str) -> bool:
        return self.sessions.get_cached(owner) is not None or self.sessions.read_session_metadata(owner) is not None

    def contains(self, task_id: str, owner: str) -> bool:
        key = self.key(task_id)
        child = self.sessions.get_cached(key)
        metadata = child.metadata if child is not None else (self.sessions.read_session_metadata(key) or {}).get("metadata", {})
        return metadata.get(SESSION_TYPE_KEY) == SUBAGENT.name and metadata.get(PARENT_SESSION_KEY) == owner

    def snapshot(self, task_id: str, owner: str) -> Session | None:
        """Read a detached child only while its parent still owns it."""
        if not self.exists(owner) or not self.contains(task_id, owner):
            return None
        return self.sessions.get_existing(self.key(task_id))

    @staticmethod
    def _payload(status: SubagentStatus) -> dict[str, Any]:
        return {
            **_STATUS.dump_python(status, mode="json", exclude={"started_at", "finished_at"}),
            "elapsed_seconds": status.as_dict()["elapsed_seconds"],
        }

    async def create(self, status: SubagentStatus, *, policy: SessionPolicy | None = None) -> Session:
        return await self.sessions.state.create_child(
            status.owner, self.key(status.task_id),
            metadata={SESSION_TYPE_KEY: SUBAGENT.name, TASK_METADATA_KEY: self._payload(status)},
            content=status.task_description, policy=policy or SessionPolicy(),
        )

    async def save(self, status: SubagentStatus) -> bool:
        try:
            await self.sessions.state.update_metadata(
                self.key(status.task_id), {TASK_METADATA_KEY: self._payload(status)},
            )
        except SessionConflictError:
            return False
        return True

    def status(self, task_id: str, owner: str) -> SubagentStatus | None:
        payload = self.sessions.read_session_metadata(self.key(task_id))
        if payload is None:
            child = self.sessions.get_cached(self.key(task_id))
            payload = {"metadata": child.metadata} if child is not None else None
        if payload is None:
            return None
        metadata = payload.get("metadata", {})
        if metadata.get(SESSION_TYPE_KEY) != SUBAGENT.name or metadata.get(PARENT_SESSION_KEY) != owner:
            return None
        raw: object = metadata.get(TASK_METADATA_KEY)
        if not isinstance(raw, dict):
            raise SubagentSessionError("invalid task session metadata")
        value = cast(dict[str, object], raw)
        elapsed = value.get("elapsed_seconds")
        if (not isinstance(elapsed, (int, float)) or isinstance(elapsed, bool)
                or not math.isfinite(elapsed) or elapsed < 0):
            raise SubagentSessionError("invalid task duration")
        now = time.monotonic()
        try:
            status = _STATUS.validate_python({
                **value, "started_at": now - elapsed,
                "finished_at": now if value.get("completed_at") is not None else None,
            })
        except ValidationError as exc:
            raise SubagentSessionError("invalid task session metadata") from exc
        if status.owner != owner or status.task_id != task_id:
            raise SubagentSessionError("invalid task ownership")
        return status

    def load(self, owner: str) -> dict[str, SubagentStatus]:
        result: dict[str, SubagentStatus] = {}
        for key in self.sessions.child_session_keys(owner):
            task_id = key.removeprefix("subagent:")
            if key != self.key(task_id):
                continue
            status = self.status(task_id, owner)
            if status is not None:
                result[task_id] = status
        return result

    async def interrupt_pending(self) -> None:
        """Seal abandoned work after the gateway acquires execution ownership."""
        for row in self.sessions.list_sessions():
            key = row["key"]
            payload = self.sessions.read_session_metadata(key)
            metadata = (payload or {}).get("metadata", {})
            if metadata.get(SESSION_TYPE_KEY) != SUBAGENT.name:
                continue
            owner = metadata.get(PARENT_SESSION_KEY)
            if not isinstance(owner, str):
                continue
            try:
                status = self.status(key.removeprefix("subagent:"), owner)
                if status is None or status.state not in _ACTIVE_STATES:
                    continue
                status.state = status.phase = "interrupted"
                status.revision += 1
                status.stop_reason = "host_restarted"
                status.finished_at = time.monotonic()
                status.completed_at = time.time()
                status.partial = bool(status.result)
                status.tool_events = []
                status.receipts = {key: "undelivered" if receipt == "accepted" else receipt
                                   for key, receipt in status.receipts.items()}
                await self.save(status)
            except (OSError, SubagentSessionError):
                logger.exception("Could not recover subagent session {}", key)
