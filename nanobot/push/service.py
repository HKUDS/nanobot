"""Push service: orchestrates dual-channel delivery and TurnCompleted subscription.

The service subscribes to RuntimeEventBus for TurnCompleted events. When a turn
finishes and the user has registered push devices, it sends notifications via
FCM + Xiaomi (whichever is configured).

To avoid duplicate notifications: if the user has an active WebSocket connection
for the same chat_id, push is skipped (they already saw the reply in-app).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol

from loguru import logger

from nanobot.bus.runtime_events import (
    RuntimeEventBus,
    TurnCompleted,
)
from nanobot.push.senders import FCMSender, PushSender, XiaomiSender
from nanobot.push.store import DeviceStore


class ConnectionChecker(Protocol):
    """Interface to check if a user has an active WebSocket connection."""

    def is_connected(self, chat_id: str) -> bool:
        """Return True if the user has an active WS connection for this chat."""
        ...


class PushService:
    """Manages push notification delivery for turn completion events."""

    def __init__(
        self,
        *,
        bus: RuntimeEventBus | None = None,
        store: DeviceStore | None = None,
        fcm_sender: PushSender | None = None,
        xiaomi_sender: PushSender | None = None,
        connection_checker: Any | None = None,
    ) -> None:
        self._bus = bus
        self._store = store or DeviceStore()
        self._fcm = fcm_sender or FCMSender()
        self._xiaomi = xiaomi_sender or XiaomiSender()
        self._connection_checker = connection_checker
        self._unsubscribe: Any = None

    def start(self) -> None:
        """Subscribe to TurnCompleted events on the runtime bus."""
        if self._bus is not None:
            self._unsubscribe = self._bus.subscribe(self._on_turn_completed, TurnCompleted)
            logger.info("push service started (fcm={}, xiaomi={})", self._fcm.is_configured, self._xiaomi.is_configured)

    def stop(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

    async def _on_turn_completed(self, event: TurnCompleted) -> None:
        """Handle a completed turn: send push if user is offline."""
        chat_id = event.context.chat_id
        metadata = event.context.metadata or {}

        # Skip if user has active WebSocket for this chat
        if self._connection_checker is not None:
            try:
                if self._connection_checker.is_chat_connected(chat_id):
                    logger.debug("push skip: user online on chat_id={}", chat_id)
                    return
            except Exception:
                pass

        # Extract gateway token from metadata to look up devices
        user_token = metadata.get("gateway_token", "")
        if not user_token:
            return

        devices = self._store.get_devices(user_token)
        if not devices:
            return

        title = "贾维斯"
        body = "助手回复完成，点击查看"
        data = {"chat_id": chat_id, "from_push": "true"}

        for device_id, device_info in devices.items():
            if self._fcm.is_configured and device_info.get("fcm_token"):
                await self._fcm.send(
                    target=device_info["fcm_token"],
                    title=title,
                    body=body,
                    data=data,
                )
            if self._xiaomi.is_configured and device_info.get("xiaomi_reg_id"):
                await self._xiaomi.send(
                    target=device_info["xiaomi_reg_id"],
                    title=title,
                    body=body,
                    data=data,
                )

    def register_device(
        self,
        user_token: str,
        device_id: str,
        *,
        fcm_token: str | None = None,
        xiaomi_reg_id: str | None = None,
        platform: str = "android",
    ) -> None:
        """Register a device's push tokens."""
        self._store.register(
            user_token,
            device_id,
            fcm_token=fcm_token,
            xiaomi_reg_id=xiaomi_reg_id,
            platform=platform,
        )

    def unregister_device(self, user_token: str, device_id: str) -> None:
        self._store.unregister(user_token, device_id)


# Singleton instance
_push_service: PushService | None = None


def get_push_service() -> PushService:
    """Get or create the singleton PushService."""
    global _push_service
    if _push_service is None:
        _push_service = PushService()
    return _push_service


def init_push_service(
    *,
    bus: RuntimeEventBus | None = None,
    connection_checker: ConnectionChecker | None = None,
) -> PushService:
    """Initialize the push service with a runtime bus."""
    global _push_service
    _push_service = PushService(bus=bus, connection_checker=connection_checker)
    _push_service.start()
    return _push_service
