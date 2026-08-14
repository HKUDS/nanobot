"""WhatsApp-owned interactive QR connection flow."""

from __future__ import annotations

import asyncio
import os
import secrets
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from nanobot.channels.connect import ChannelConnectError, QueryParams, query_first
from nanobot.channels.whatsapp.state import recovery_marker_path, recovery_required_message
from nanobot.config.loader import load_config

if TYPE_CHECKING:
    from nanobot.channels.whatsapp.runtime import WhatsAppChannel


_SESSION_TTL_SECONDS = 600
_TERMINAL_TTL_SECONDS = 60


class WhatsAppDatabaseRecoveryError(RuntimeError):
    """The SQLite file family could not be promoted or rolled back atomically."""


@dataclass(slots=True)
class WhatsAppConnectSession:
    id: str
    channel: WhatsAppChannel
    client: Any
    result: asyncio.Future[None]
    connect_task: asyncio.Task[None]
    target_path: Path
    pending_path: Path
    created_wall: float
    deadline: float
    qr_url: str = ""
    state: Literal[
        "pending",
        "prepared",
        "finalizing",
        "promoted",
        "close_failed",
        "recovery_required",
    ] = "pending"
    closed: bool = False
    recovery_message: str = ""
    close_intent: Literal["prepare", "cancel", "expire", "fail"] | None = None
    close_error: str = ""
    close_result_message: str = ""


class WhatsAppConnectStore:
    """In-memory WhatsApp linked-device sessions for the WebUI."""

    def __init__(self) -> None:
        self._sessions: dict[str, WhatsAppConnectSession] = {}
        self._outcomes: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    async def handle(self, action: str, query: QueryParams) -> dict[str, Any]:
        if action == "start":
            force = (query_first(query, "force") or "").strip().lower() in {
                "1",
                "true",
                "yes",
            }
            return await self.start(force=force)

        session_id = (query_first(query, "session_id") or "").strip()
        if not session_id:
            raise ChannelConnectError("missing WhatsApp connect session")
        if action == "poll":
            return await self.poll(session_id)
        if action == "cancel":
            return await self.cancel(session_id)
        raise ChannelConnectError(f"unsupported WhatsApp connect action: {action}", status=404)

    async def start(self, *, force: bool = False) -> dict[str, Any]:
        async with self._lock:
            await self._cleanup_locked()
            channel, target_path = self._build_channel()
            if recovery_message := recovery_required_message(target_path):
                return {
                    "session_id": "",
                    "status": "failed",
                    "message": recovery_message,
                    "recovery_required": True,
                    "restart_blocked": True,
                    "requires_restart": False,
                    "_recovery_required": True,
                }
            active = next(
                (
                    session
                    for session in self._sessions.values()
                    if session.target_path == target_path
                ),
                None,
            )
            if active is not None:
                if active.state == "close_failed":
                    return await self._retry_close_locked(active)
                return self._session_payload(active)
            if not force and self._local_state_present(target_path):
                return {
                    "session_id": "",
                    "status": "succeeded",
                    "message": "WhatsApp is already connected.",
                    "interval_ms": 2000,
                }

            session_id = secrets.token_urlsafe(18)
            pending_path = target_path.with_name(f".{target_path.name}.{session_id}.connect")
            pending_path.parent.mkdir(parents=True, exist_ok=True)
            self._remove_database(pending_path)
            channel.config.database_path = str(pending_path)
            now_wall = time.time()

            async def capture_qr(qr_data: bytes) -> None:
                session = self._sessions.get(session_id)
                if session is not None:
                    session.qr_url = qr_data.decode("utf-8")

            client, result = channel.connect_open_client(capture_qr)
            connect_task = asyncio.create_task(
                self._connect(channel, client, result),
                name=f"whatsapp-connect-{session_id}",
            )
            session = WhatsAppConnectSession(
                id=session_id,
                channel=channel,
                client=client,
                result=result,
                connect_task=connect_task,
                target_path=target_path,
                pending_path=pending_path,
                created_wall=now_wall,
                deadline=time.monotonic() + _SESSION_TTL_SECONDS,
            )
            self._sessions[session_id] = session

            qr_wait = asyncio.create_task(self._wait_for_qr(session))
            try:
                await asyncio.wait(
                    {qr_wait, connect_task},
                    timeout=3,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                if not qr_wait.done():
                    qr_wait.cancel()
            return self._pending_payload(session)

    async def poll(self, session_id: str) -> dict[str, Any]:
        async with self._lock:
            await self._cleanup_locked()
            if outcome := self._replay_outcome(session_id):
                return outcome
            session = self._sessions.get(session_id)
            if session is None:
                return self._expired_payload(session_id)
            if session.state == "recovery_required":
                return self._recovery_payload(session)
            if session.state == "close_failed":
                return await self._retry_close_locked(session)
            if session.state == "promoted":
                return self._prepared_payload(session)
            if session.state == "prepared":
                return self._prepared_payload(session)
            if not session.result.done():
                return self._pending_payload(session)

            try:
                session.result.result()
            except asyncio.CancelledError:
                return await self._fail_session_locked(
                    session,
                    RuntimeError("WhatsApp QR login was interrupted"),
                )
            except Exception as exc:
                return await self._fail_session_locked(session, exc)
            return await self._finish_close_locked(session, "prepare")

    async def finalize(self, session_id: str) -> dict[str, Any]:
        """Promote a prepared login after its live runtime has been stopped."""
        async with self._lock:
            self._purge_outcomes()
            if outcome := self._replay_outcome(session_id):
                return outcome
            session = self._sessions.get(session_id)
            if session is None:
                return self._expired_payload(session_id)
            if session.state == "recovery_required":
                return self._recovery_payload(session)
            if session.state == "promoted":
                return self._promoted_payload(session)
            if session.state != "prepared":
                return self._pending_payload(session)

            session.state = "finalizing"
            try:
                self._commit_database(session.pending_path, session.target_path)
            except WhatsAppDatabaseRecoveryError as exc:
                session.state = "recovery_required"
                session.recovery_message = (
                    f"{exc} Do not restart or enable WhatsApp until the database files "
                    "have been reconciled."
                )
                return self._recovery_payload(session)
            except Exception as exc:
                # A complete rollback leaves the pending SQLite family intact.
                # Keep the prepared session so a transient Windows file lock can
                # be retried and so runtime restoration can be retried as part of
                # the same finalization transaction.
                session.state = "prepared"
                session.deadline = time.monotonic() + _SESSION_TTL_SECONDS
                return {
                    "session_id": session.id,
                    "status": "failed",
                    "message": f"WhatsApp session database could not be applied: {exc}",
                    "retryable": True,
                    "_requires_finalize": True,
                }

            session.state = "promoted"
            return self._promoted_payload(session)

    async def complete(self, session_id: str) -> dict[str, Any]:
        """Acknowledge that config persistence and runtime activation succeeded."""
        async with self._lock:
            self._purge_outcomes()
            if outcome := self._replay_outcome(session_id):
                return outcome
            session = self._sessions.get(session_id)
            if session is None:
                return self._expired_payload(session_id)
            if session.state == "recovery_required":
                return self._recovery_payload(session)
            if session.state != "promoted":
                return self._session_payload(session)

            self._sessions.pop(session_id, None)
            payload = {
                "session_id": session_id,
                "status": "succeeded",
                "message": "WhatsApp is connected.",
            }
            self._remember_outcome(payload)
            return payload

    async def cancel(self, session_id: str) -> dict[str, Any]:
        async with self._lock:
            await self._cleanup_locked()
            if outcome := self._replay_outcome(session_id):
                return outcome
            session = self._sessions.get(session_id)
            if session is None:
                return self._expired_payload(session_id)
            if session.state == "recovery_required":
                return self._recovery_payload(session)
            if session.state == "promoted":
                # Promotion is irreversible after the old backup family has
                # been removed. Cancellation must never be mistaken for a
                # request to activate the promoted database.
                return {
                    "session_id": session_id,
                    "status": "failed",
                    "message": (
                        "WhatsApp session data has already been applied and can no longer be "
                        "cancelled. Try again to finish activation."
                    ),
                    "retryable": True,
                }
            return await self._finish_close_locked(session, "cancel")

    async def _cleanup(self) -> None:
        async with self._lock:
            await self._cleanup_locked()

    async def _cleanup_locked(self) -> None:
        self._purge_outcomes()
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if session.state in {"pending", "prepared"}
            and time.monotonic() >= session.deadline
        ]
        for session_id in expired:
            session = self._sessions[session_id]
            await self._finish_close_locked(session, "expire")

    async def _fail_session_locked(
        self,
        session: WhatsAppConnectSession,
        exc: BaseException,
    ) -> dict[str, Any]:
        return await self._finish_close_locked(
            session,
            "fail",
            result_message=f"WhatsApp QR login failed: {exc}",
        )

    async def _finish_close_locked(
        self,
        session: WhatsAppConnectSession,
        intent: Literal["prepare", "cancel", "expire", "fail"],
        *,
        result_message: str = "",
    ) -> dict[str, Any]:
        """Close a login client without letting one bad client poison the store."""
        session.close_intent = intent
        if result_message:
            session.close_result_message = result_message
        try:
            await self._close_session(session)
        except Exception as exc:
            session.state = "close_failed"
            session.close_error = str(exc)
            session.deadline = time.monotonic() + _SESSION_TTL_SECONDS
            return self._close_failed_payload(session)

        session.close_error = ""
        if intent == "prepare":
            session.state = "prepared"
            session.deadline = time.monotonic() + _SESSION_TTL_SECONDS
            return self._prepared_payload(session)

        self._remove_database(session.pending_path)
        self._sessions.pop(session.id, None)
        if intent == "cancel":
            payload = {
                "session_id": session.id,
                "status": "cancelled",
                "message": "WhatsApp login cancelled.",
            }
        elif intent == "expire":
            payload = self._expired_payload(session.id)
        else:
            payload = {
                "session_id": session.id,
                "status": "failed",
                "message": session.close_result_message or "WhatsApp QR login failed.",
            }
        self._remember_outcome(payload)
        return payload

    async def _retry_close_locked(self, session: WhatsAppConnectSession) -> dict[str, Any]:
        intent = session.close_intent or "fail"
        return await self._finish_close_locked(
            session,
            intent,
            result_message=session.close_result_message,
        )

    def _remember_outcome(self, payload: dict[str, Any]) -> None:
        session_id = str(payload["session_id"])
        self._outcomes[session_id] = (
            time.monotonic() + _TERMINAL_TTL_SECONDS,
            dict(payload),
        )

    def _replay_outcome(self, session_id: str) -> dict[str, Any] | None:
        outcome = self._outcomes.get(session_id)
        if outcome is None:
            return None
        payload = dict(outcome[1])
        payload["_terminal_replay"] = True
        return payload

    def _purge_outcomes(self) -> None:
        now = time.monotonic()
        for session_id, (deadline, _payload) in list(self._outcomes.items()):
            if now >= deadline:
                self._outcomes.pop(session_id, None)

    @staticmethod
    async def _connect(
        channel: WhatsAppChannel,
        client: Any,
        result: asyncio.Future[None],
    ) -> None:
        try:
            await channel.connect_start_client(client, result)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not result.done():
                result.set_exception(exc)

    @staticmethod
    async def _wait_for_qr(session: WhatsAppConnectSession) -> None:
        while not session.qr_url and not session.result.done():
            await asyncio.sleep(0.05)

    @staticmethod
    async def _close_session(session: WhatsAppConnectSession) -> None:
        if session.closed:
            return
        if not session.result.done():
            session.result.cancel()
        elif not session.result.cancelled():
            with suppress(Exception):
                session.result.exception()
        if not session.connect_task.done():
            session.connect_task.cancel()
        with suppress(Exception, asyncio.CancelledError):
            await session.connect_task
        await session.client.stop()
        session.closed = True

    @staticmethod
    def _build_channel() -> tuple[WhatsAppChannel, Path]:
        from nanobot.bus.queue import MessageBus
        from nanobot.channels.whatsapp.runtime import WhatsAppChannel

        section = getattr(load_config().channels, "whatsapp", None)
        if section is not None and hasattr(section, "model_dump"):
            config = section.model_dump(mode="json", by_alias=True)
        elif isinstance(section, dict):
            config = dict(cast(dict[str, Any], section))
        else:
            config = {}
        channel = WhatsAppChannel(config, MessageBus())
        return channel, channel.connect_database_path()

    @staticmethod
    def _local_state_present(path: Path) -> bool:
        try:
            return path.is_file() and path.stat().st_size > 0
        except OSError:
            return False

    @classmethod
    def _commit_database(cls, pending: Path, target: Path) -> None:
        if not cls._local_state_present(pending):
            raise RuntimeError("WhatsApp connected but did not create a local session database")
        target.parent.mkdir(parents=True, exist_ok=True)
        recovery_marker = recovery_marker_path(target)
        try:
            with recovery_marker.open("x", encoding="utf-8") as marker_file:
                marker_file.write(
                    "WhatsApp database promotion was interrupted. Reconcile the preserved "
                    "SQLite files before removing this marker.\n"
                )
                marker_file.flush()
                os.fsync(marker_file.fileno())
        except FileExistsError as exc:
            raise WhatsAppDatabaseRecoveryError(
                recovery_required_message(target)
                or "WhatsApp database recovery is already required."
            ) from exc
        backup = target.with_name(f".{target.name}.{secrets.token_urlsafe(8)}.backup")
        backups: list[tuple[Path, Path]] = []
        promoted: list[tuple[Path, Path]] = []

        try:
            for target_file, backup_file in cls._database_files(target, backup):
                if target_file.exists():
                    os.replace(target_file, backup_file)
                    backups.append((target_file, backup_file))
            for pending_file, target_file in cls._database_files(pending, target):
                if pending_file.exists():
                    os.replace(pending_file, target_file)
                    promoted.append((pending_file, target_file))
        except Exception as exc:
            rollback_errors: list[OSError] = []
            unrecovered_targets: set[Path] = set()
            for pending_file, target_file in reversed(promoted):
                try:
                    os.replace(target_file, pending_file)
                except OSError as rollback_exc:
                    rollback_errors.append(rollback_exc)
                    unrecovered_targets.add(target_file)
            for target_file, backup_file in reversed(backups):
                if target_file in unrecovered_targets:
                    # The newly promoted file is still live at target_file. Do
                    # not overwrite it with the old backup: both generations
                    # are required for an operator to recover the SQLite family.
                    continue
                try:
                    os.replace(backup_file, target_file)
                except OSError as rollback_exc:
                    rollback_errors.append(rollback_exc)
            if rollback_errors:
                raise WhatsAppDatabaseRecoveryError(
                    "WhatsApp session database promotion and rollback failed. "
                    f"Preserved recovery files beside {target}: {rollback_errors[0]}"
                ) from exc
            try:
                recovery_marker.unlink()
            except OSError as marker_exc:
                raise WhatsAppDatabaseRecoveryError(
                    "WhatsApp session database rollback completed, but its recovery marker "
                    f"could not be cleared: {marker_exc}"
                ) from marker_exc
            raise
        else:
            for _target_file, backup_file in backups:
                with suppress(OSError):
                    backup_file.unlink()
            try:
                recovery_marker.unlink()
            except OSError as exc:
                raise WhatsAppDatabaseRecoveryError(
                    "WhatsApp session database was promoted, but its recovery marker "
                    f"could not be cleared: {exc}"
                ) from exc

    @classmethod
    def _remove_database(cls, path: Path) -> None:
        for candidate, _ in cls._database_files(path, path):
            with suppress(OSError):
                candidate.unlink()

    @staticmethod
    def _database_files(source: Path, target: Path) -> tuple[tuple[Path, Path], ...]:
        return (
            (source, target),
            (source.with_name(source.name + "-shm"), target.with_name(target.name + "-shm")),
            (source.with_name(source.name + "-wal"), target.with_name(target.name + "-wal")),
        )

    @staticmethod
    def _pending_payload(session: WhatsAppConnectSession) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "session_id": session.id,
            "status": "pending",
            "interval_ms": 2000,
            "expires_at_ms": int((session.created_wall + _SESSION_TTL_SECONDS) * 1000),
            "message": "Waiting for the WhatsApp scan.",
        }
        if session.qr_url:
            payload["qr_url"] = session.qr_url
        return payload

    @classmethod
    def _session_payload(cls, session: WhatsAppConnectSession) -> dict[str, Any]:
        if session.state == "recovery_required":
            return cls._recovery_payload(session)
        if session.state == "close_failed":
            return cls._close_failed_payload(session)
        if session.state in {"prepared", "promoted"}:
            return cls._prepared_payload(session)
        return cls._pending_payload(session)

    @staticmethod
    def _close_failed_payload(session: WhatsAppConnectSession) -> dict[str, Any]:
        detail = f": {session.close_error}" if session.close_error else ""
        return {
            "session_id": session.id,
            "status": "failed",
            "message": (
                f"Could not close the WhatsApp login database safely{detail}. "
                "Try again to retry cleanup, or cancel the connection."
            ),
            "retryable": True,
        }

    @staticmethod
    def _prepared_payload(session: WhatsAppConnectSession) -> dict[str, Any]:
        return {
            "session_id": session.id,
            "status": "prepared",
            "message": (
                "Applying the WhatsApp connection."
                if session.state == "promoted"
                else "Finishing the WhatsApp connection."
            ),
            "_requires_finalize": True,
        }

    @staticmethod
    def _promoted_payload(session: WhatsAppConnectSession) -> dict[str, Any]:
        return {
            "session_id": session.id,
            "status": "succeeded",
            "message": "WhatsApp session data is ready.",
            "_requires_complete": True,
        }

    @staticmethod
    def _recovery_payload(session: WhatsAppConnectSession) -> dict[str, Any]:
        return {
            "session_id": session.id,
            "status": "failed",
            "message": session.recovery_message or (
                "WhatsApp session files require manual recovery. Do not restart or enable "
                "WhatsApp until the database files have been reconciled."
            ),
            "recovery_required": True,
            "restart_blocked": True,
            "requires_restart": False,
            "_recovery_required": True,
        }

    @staticmethod
    def _expired_payload(session_id: str) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "status": "expired",
            "message": "This WhatsApp login has expired. Start again.",
        }


__all__ = ["WhatsAppConnectStore", "WhatsAppDatabaseRecoveryError"]
