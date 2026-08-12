"""WhatsApp-owned interactive QR connection flow."""

from __future__ import annotations

import asyncio
import os
import secrets
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from nanobot.channels.connect import ChannelConnectError, QueryParams, query_first
from nanobot.config.loader import load_config

if TYPE_CHECKING:
    from nanobot.channels.whatsapp.runtime import WhatsAppChannel


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


class WhatsAppConnectStore:
    """In-memory WhatsApp linked-device sessions for the WebUI."""

    def __init__(self) -> None:
        self._sessions: dict[str, WhatsAppConnectSession] = {}

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
        await self._cleanup()
        channel, target_path = self._build_channel()
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
            deadline=time.monotonic() + 600,
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
        await self._cleanup()
        session = self._sessions.get(session_id)
        if session is None:
            return {
                "session_id": session_id,
                "status": "expired",
                "message": "This WhatsApp login has expired. Start again.",
            }
        if not session.result.done():
            return self._pending_payload(session)

        self._sessions.pop(session_id, None)
        try:
            session.result.result()
            await self._close_session(session)
            self._commit_database(session.pending_path, session.target_path)
        except Exception as exc:
            await self._close_session(session)
            self._remove_database(session.pending_path)
            return {
                "session_id": session_id,
                "status": "failed",
                "message": f"WhatsApp QR login failed: {exc}",
            }
        return {
            "session_id": session_id,
            "status": "succeeded",
            "message": "WhatsApp is connected.",
        }

    async def cancel(self, session_id: str) -> dict[str, Any]:
        session = self._sessions.pop(session_id, None)
        if session is not None:
            await self._close_session(session)
            self._remove_database(session.pending_path)
        return {
            "session_id": session_id,
            "status": "cancelled",
            "message": "WhatsApp login cancelled.",
        }

    async def _cleanup(self) -> None:
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if time.monotonic() >= session.deadline
        ]
        for session_id in expired:
            session = self._sessions.pop(session_id)
            await self._close_session(session)
            self._remove_database(session.pending_path)

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
        if not session.result.done():
            session.result.cancel()
        if not session.connect_task.done():
            session.connect_task.cancel()
        with suppress(Exception, asyncio.CancelledError):
            await session.connect_task
        with suppress(Exception):
            await session.client.stop()

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
        for pending_file, target_file in cls._database_files(pending, target):
            if pending_file.exists():
                os.replace(pending_file, target_file)
            elif target_file != target and target_file.exists():
                target_file.unlink()

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
            "expires_at_ms": int((session.created_wall + 600) * 1000),
            "message": "Waiting for the WhatsApp scan.",
        }
        if session.qr_url:
            payload["qr_url"] = session.qr_url
        return payload


__all__ = ["WhatsAppConnectStore"]
