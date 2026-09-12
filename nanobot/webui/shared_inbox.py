"""Owner-only Telegram/WebUI views, without a second LLM conversation or log mirror.

The WebUI gateway is one operator trust domain, not a multi-user account server.
Only its authenticated WebUI audience may use these reserved chat IDs. Concrete
Telegram sessions are reused; legacy global unified history is never adopted.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, cast

from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import StreamedResponseEvent
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import SessionTurnPersisted, TurnCompleted
from nanobot.runtime_context import public_history_message
from nanobot.session.history_visibility import is_hidden_history_message
from nanobot.webui.notification_store import DeliveryState, NotificationStore
from nanobot.webui.session_identity import webui_session_key

if TYPE_CHECKING:
    from nanobot.channels.telegram.technical_config import TelegramTechnicalConfig
    from nanobot.session.manager import SessionManager

MAIN_CHAT_ID = "shared-main"
NOTIFICATIONS_CHAT_ID = "shared-notifications"
SHARED_CHAT_IDS = frozenset({MAIN_CHAT_ID, NOTIFICATIONS_CHAT_ID})
MAX_RECEIPTS = 500


class SharedInbox:
    def __init__(
        self, config: TelegramTechnicalConfig, sessions: SessionManager, bus: MessageBus,
        *, main_token: str = "",
    ) -> None:
        # Match the sender's effective bot, but retain no credential in this read model.
        self._notification_bot_id = (config.token or main_token).split(":", 1)[0]
        self.config = config.model_copy(deep=True, update={"token": ""})
        self.active = True
        self.sessions = sessions
        self.bus = bus
        self._mirrored_turns: dict[str, None] = {}
        self.main_session_key = f"telegram:{config.main_chat_id}"
        self._path = sessions.sessions_dir / "telegram-notification-receipts.json"
        self.notifications = NotificationStore(
            self._path, owner=config.main_chat_id, target=config.chat_id,
        )
        self._lock = asyncio.Lock()
        self._socket: Any = None

    def matches_config(self, config: TelegramTechnicalConfig, *, main_token: str = "") -> bool:
        bot_id = (config.token or main_token).split(":", 1)[0]
        return (config.enabled == self.config.enabled and config.shared_inbox
                and config.main_chat_id == self.config.main_chat_id
                and config.chat_id == self.config.chat_id
                and bot_id == self._notification_bot_id)

    def session_key(self, channel: str, chat_id: str) -> str:
        if self.active and channel == "websocket" and chat_id == MAIN_CHAT_ID:
            return self.main_session_key
        return f"{channel}:{chat_id}"

    def bind_websocket(self, channel: Any) -> None:
        self._socket = channel

    async def refresh(self, chat_id: str) -> None:
        if self.active and self._socket is not None:
            await self._socket.send_session_updated(chat_id)

    async def observe_runtime(self, event: Any) -> None:
        if not self.active or not isinstance(event, (SessionTurnPersisted, TurnCompleted)) or event.context.session_key != self.main_session_key:
            return
        await self.refresh(MAIN_CHAT_ID)
        if (isinstance(event, SessionTurnPersisted) and event.context.channel == "websocket"
                and event.context.chat_id == MAIN_CHAT_ID and event.turn_id not in self._mirrored_turns):
            self._mirrored_turns[event.turn_id] = None
            if len(self._mirrored_turns) > 256:
                self._mirrored_turns.pop(next(iter(self._mirrored_turns)))
            data = self.sessions.read_session_file(self.main_session_key)
            history: list[dict[str, Any]] = data.get("messages", []) if data else []
            last = history[-1] if history else {}
            if (last.get("role") != "assistant" or last.get("tool_calls")
                    or last.get("_command") or is_hidden_history_message(last)):
                return
            content = public_history_message(last).get("content")
            if isinstance(content, str) and content:
                # One final answer, never raw command output or a second history write.
                await self.bus.publish_outbound(OutboundMessage(
                    channel="telegram", chat_id=self.config.main_chat_id,
                    content=content, metadata={"_shared_inbox_mirror": True},
                ))

    def _receipts(self) -> list[dict[str, Any]]:
        return self.notifications.rows()

    def _save_receipt(self, text: str, message_id: int | str) -> None:
        self.notifications.record(text, message_id, "delivered")

    async def record_notification(
        self, text: str, identity: str, state: DeliveryState = "pending",
    ) -> None:
        if not self.active:
            return
        async with self._lock:
            await asyncio.to_thread(self.notifications.record, text, identity, state)
        await self.refresh(NOTIFICATIONS_CHAT_ID)

    async def observe_outbound(
        self, msg: OutboundMessage, state: DeliveryState = "pending",
    ) -> None:
        from nanobot.channels.telegram.user_notifications import notification_receipt_id

        if (not self.active or msg.channel != "telegram"
                or msg.chat_id != self.config.main_chat_id
                or (msg.event is not None and not isinstance(msg.event, StreamedResponseEvent))):
            return
        identity = notification_receipt_id(msg.metadata, msg.content)
        if identity is not None:
            await self.record_notification(msg.content, identity, state)

    async def mark_read(self, identities: list[str]) -> int:
        if not self.active:
            return 0
        changed = await asyncio.to_thread(self.notifications.mark_read, identities)
        if changed:
            await self.refresh(NOTIFICATIONS_CHAT_ID)
        return changed

    async def delivered(self, text: str, message_id: int | str) -> None:
        # Called only after a confirmed Telegram send. Persistence failure must
        # never retry that send (which would duplicate already delivered content).
        if not self.active:
            return
        async with self._lock:
            await asyncio.to_thread(self._save_receipt, text, message_id)
        await self.refresh(NOTIFICATIONS_CHAT_ID)

    def rows(self) -> list[dict[str, Any]]:
        if not self.active:
            return []
        result: list[dict[str, Any]] = []
        for chat_id, title, stream in ((NOTIFICATIONS_CHAT_ID, "Powiadomienia", "notifications"),
                                      (MAIN_CHAT_ID, "Czat główny", "main")):
            feed_error = False
            try:
                messages = self.messages(chat_id)
            except (OSError, ValueError):
                if stream != "notifications":
                    raise
                messages = []
                feed_error = True
            last = messages[-1] if messages else None
            timestamp = datetime.fromtimestamp(last["createdAt"] / 1000, timezone.utc).isoformat() if last else None
            result.append({"key": webui_session_key(chat_id), "title": title,
                           "shared_stream": stream, "read_only": stream == "notifications",
                           "unread_count": sum(not row.get("read", True) for row in messages)
                           if stream == "notifications" else 0,
                           "profile_name": self.config.profile_name,
                           "updated_at": timestamp, "created_at": timestamp,
                           "message_count": len(messages),
                           "preview": "Nie można odczytać powiadomień" if feed_error else last["content"][:160] if last else "",
                           **({"feed_error": "notification_store_unavailable"} if feed_error else {})})
        return result

    def messages(self, chat_id: str) -> list[dict[str, Any]]:
        if not self.active:
            return []
        if chat_id == NOTIFICATIONS_CHAT_ID:
            return self._receipts()
        data = self.sessions.read_session_file(self.main_session_key)
        raw: list[Any] = data.get("messages", []) if isinstance(data, dict) else []
        messages: list[dict[str, Any]] = []
        for index, raw_item in enumerate(raw):
            if not isinstance(raw_item, dict):
                continue
            item = cast(dict[str, Any], raw_item)
            if item.get("role") not in {"user", "assistant"} or item.get("tool_calls"):
                continue
            if is_hidden_history_message(item) or item.get("_command"):
                continue
            item = public_history_message(item)
            text = item.get("content")
            if not isinstance(text, str) or not text:
                continue
            try:
                timestamp = int(datetime.fromisoformat(item.get("timestamp", "")).timestamp() * 1000)
            except (ValueError, TypeError):
                timestamp = 0
            messages.append({"id": f"shared-main:{index}", "role": item["role"],
                             "content": text, "createdAt": timestamp})
        return messages

    def thread(self, chat_id: str) -> dict[str, Any]:
        from nanobot.webui.transcript import WEBUI_TRANSCRIPT_SCHEMA_VERSION

        return {"schemaVersion": WEBUI_TRANSCRIPT_SCHEMA_VERSION, "sessionKey": webui_session_key(chat_id),
                "messages": self.messages(chat_id), "completed_turn_ids": [],
                "has_pending_tool_calls": False, "active_turn_id": None}
