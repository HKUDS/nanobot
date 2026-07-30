"""Connection-owned lifecycle for WebUI Temporary Chat sessions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from websockets.asyncio.server import ServerConnection

from nanobot.session.manager import SessionManager
from nanobot.session.webui_turns import clear_websocket_turns


class TemporaryChatLifecycleError(RuntimeError):
    """A stable WebSocket protocol error raised by the temporary-chat lifecycle."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class TemporaryChatLifecycle:
    """Own temporary session identity, cancellation, and cleanup ordering."""

    def __init__(
        self,
        *,
        sessions: SessionManager | None,
        cancel_active_turn: Callable[[str], Awaitable[int]] | None,
        attach: Callable[[ServerConnection, str], None],
        detach: Callable[[ServerConnection, str], None],
        clear_stream_buffers: Callable[[str], None],
    ) -> None:
        self._sessions = sessions
        self._cancel_active_turn = cancel_active_turn
        self._attach = attach
        self._detach = detach
        self._clear_stream_buffers = clear_stream_buffers
        self._owners: dict[str, ServerConnection] = {}

    def claim(self, owner: ServerConnection, chat_id: str) -> str:
        """Claim *chat_id* for *owner* and return its in-memory session key."""
        if self._sessions is None or self._cancel_active_turn is None:
            raise TemporaryChatLifecycleError("temporary_chat_unavailable")
        current = self._owners.get(chat_id)
        if current is not None and current is not owner:
            raise TemporaryChatLifecycleError("temporary_chat_not_owned")

        session_key = f"websocket:{chat_id}"
        self._sessions.get_or_create_transient(session_key)
        self._owners[chat_id] = owner
        self._attach(owner, chat_id)
        return session_key

    async def discard(self, owner: ServerConnection, chat_id: str) -> None:
        """Discard an owned chat; an unused chat is already discarded."""
        current = self._owners.get(chat_id)
        if current is None:
            return
        if current is not owner:
            raise TemporaryChatLifecycleError("temporary_chat_not_owned")
        await self._discard_owned(owner, chat_id)

    async def discard_owner(self, owner: ServerConnection) -> None:
        """Discard every temporary chat held by a disconnected owner."""
        chat_ids = (
            chat_id
            for chat_id, current in self._owners.items()
            if current is owner
        )
        for chat_id in tuple(chat_ids):
            await self._discard_owned(owner, chat_id)

    async def _discard_owned(self, owner: ServerConnection, chat_id: str) -> None:
        self._owners.pop(chat_id, None)
        self._detach(owner, chat_id)

        session_key = f"websocket:{chat_id}"
        assert self._sessions is not None
        assert self._cancel_active_turn is not None
        self._sessions.discard_transient(session_key)
        try:
            await self._cancel_active_turn(session_key)
        finally:
            clear_websocket_turns(chat_id)
            self._clear_stream_buffers(chat_id)
