"""Connection-owned, in-memory WebUI chat lifecycle."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nanobot.bus.events import (
    INBOUND_META_RUNTIME_CONTROL,
    RUNTIME_CONTROL_TRANSIENT_SESSION_DISCARD,
    InboundMessage,
)

if TYPE_CHECKING:
    from nanobot.bus.queue import MessageBus
    from nanobot.session.manager import SessionManager
    from nanobot.webui.media_gateway import WebUIMediaGateway


TEMPORARY_CHAT_ID_PREFIX = "temporary-"
TEMPORARY_COMMANDS = frozenset({"/model", "/stop"})


def has_temporary_chat_prefix(value: object) -> bool:
    return isinstance(value, str) and value.startswith(TEMPORARY_CHAT_ID_PREFIX)


class TemporaryChats:
    """Keep temporary session ownership and cleanup behind one boundary."""

    def __init__(
        self,
        sessions: SessionManager | None,
        media: WebUIMediaGateway,
        bus: MessageBus,
    ) -> None:
        self._sessions = sessions
        self._media = media
        self._bus = bus
        self._by_owner: dict[object, str] = {}
        self._owners: dict[str, object] = {}
        self._attachments: dict[str, list[str]] = {}

    def chat_id_for(self, owner: object) -> str | None:
        return self._by_owner.get(owner)

    def claim(self, owner: object, chat_id: str) -> str | None:
        if self._sessions is None:
            return "temporary_chat_unavailable"
        current_owner = self._owners.get(chat_id)
        if current_owner is not None and current_owner is not owner:
            return "temporary_chat_not_owned"
        current_chat = self._by_owner.get(owner)
        if current_chat is not None and current_chat != chat_id:
            return "temporary_chat_in_use"
        self._by_owner[owner] = chat_id
        self._owners[chat_id] = owner
        self._sessions.get_or_create_transient(f"websocket:{chat_id}")
        return None

    def remember_attachments(self, chat_id: str, paths: list[str]) -> None:
        self._attachments.setdefault(chat_id, []).extend(paths)

    async def discard(self, owner: object, chat_id: str) -> str | None:
        current_owner = self._owners.get(chat_id)
        if current_owner is None:
            return None
        if current_owner is not owner:
            return "temporary_chat_not_owned"
        self._owners.pop(chat_id, None)
        self._by_owner.pop(owner, None)
        session_key = f"websocket:{chat_id}"
        assert self._sessions is not None
        self._sessions.discard_transient(session_key)
        self._media.discard_inbound_attachments(self._attachments.pop(chat_id, []))
        await self._bus.publish_inbound(InboundMessage(
            channel="websocket",
            sender_id="webui",
            chat_id=chat_id,
            content="",
            metadata={
                INBOUND_META_RUNTIME_CONTROL: RUNTIME_CONTROL_TRANSIENT_SESSION_DISCARD,
            },
        ))
        return None
