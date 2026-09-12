"""Lossy, outbound-only Telegram operational notifications (never chat messages)."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import timedelta
from typing import TYPE_CHECKING

from loguru import logger
from telegram import Bot
from telegram.error import RetryAfter
from telegram.request import HTTPXRequest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import ProgressEvent
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import SessionTurnStarted, TurnCompleted
from nanobot.events import (
    AgentEvent,
    ContextCompactionEvent,
    RecoveryStateEvent,
    RetryStatusEvent,
)

if TYPE_CHECKING:
    from nanobot.channels.telegram.technical_config import TelegramTechnicalConfig

QUEUE_LIMIT = 64
MIN_SEND_INTERVAL = 3.0  # Also respects Telegram's group limit (~20 messages/minute).
SEND_TIMEOUT = 10.0
FAILURE_COOLDOWN = 30.0
MAX_TOOL_EVENTS = 32
_TOOL_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,63}\Z")


def _state(value: str, allowed: set[str]) -> str:
    return value if value in allowed else "updated"


class TelegramTechnicalNotifier:
    """Project typed events immediately; retain only bounded, redacted strings.

    A dedicated SDK connection pool and worker isolate the main Telegram channel
    even when using the same bot token. No polling, inbound bus publication,
    raw-event persistence, tool invocation, or failed-item retry occurs here.
    An optional callback records only sanitized, successfully delivered receipts.
    """

    def __init__(
        self,
        config: TelegramTechnicalConfig,
        bus: MessageBus,
        *,
        main_token: str,
        proxy: str | None,
    ) -> None:
        self.config = config
        self._bus = bus
        self._token = config.token or main_token
        self._shares_main_bot = config.uses_main_bot(main_token)
        self._proxy = proxy
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=QUEUE_LIMIT)
        self._task: asyncio.Task[None] | None = None
        self._active = False
        self._unsubscribe = lambda: None
        self.dropped = 0
        self.failed = 0
        self.sent = 0
        self.on_delivered: Callable[[str, int], Awaitable[None]] | None = None

    def start(self) -> None:
        if not self.config.enabled or self._task is not None:
            return
        self._active = True
        self._unsubscribe = self._bus.subscribe(self._observe_runtime)
        self._task = asyncio.create_task(self._run(), name="telegram-technical-outbound")

    async def stop(self) -> None:
        self._active = False
        self._unsubscribe()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._discard_pending()

    def _discard_pending(self) -> None:
        while not self._queue.empty():
            self._queue.get_nowait()
            self._queue.task_done()
            self.dropped += 1

    def _offer(self, text: str) -> None:
        if not self._active:
            return
        try:
            self._queue.put_nowait(text)
        except asyncio.QueueFull:
            self.dropped += 1  # Drop newest; never create a task per event.

    def _is_target_route(self, channel: str, chat_id: str) -> bool:
        # Separate bots can legitimately address the same user ID in distinct DMs.
        # Technical delivery never enters the bus, so cannot recursively mirror.
        reserved = self._shares_main_bot or self.config.chat_id.startswith("-")
        return reserved and channel == "telegram" and chat_id == self.config.chat_id

    def _is_source_route(self, channel: str, chat_id: str) -> bool:
        if not self.config.main_chat_id:
            return True  # Backward-compatible operator-wide feed without a shared inbox.
        return (channel == "telegram" and chat_id == self.config.main_chat_id) or (
            self.config.shared_inbox and channel == "websocket" and chat_id == "shared-main"
        )

    def observe_outbound(self, msg: OutboundMessage) -> None:
        if not self._active or not self._is_source_route(msg.channel, msg.chat_id) or self._is_target_route(msg.channel, msg.chat_id):
            return
        event = msg.event
        if isinstance(event, ProgressEvent) and self.config.include_tool_events:
            # Do not parse the human hint: it contains arguments. Provider/native
            # tool lifecycle payloads share this name/phase contract.
            for item in (event.tool_events or [])[:MAX_TOOL_EVENTS]:
                name, phase = item.get("name"), item.get("phase")
                if phase not in ("start", "end", "error"):
                    continue
                safe_name = name if isinstance(name, str) and _TOOL_NAME.fullmatch(name) else "tool"
                self._offer(f"Tool {safe_name}: {phase}")
            self.dropped += max(0, len(event.tool_events or []) - MAX_TOOL_EVENTS)
        elif self.config.include_status_events:
            if isinstance(event, ContextCompactionEvent):
                self._offer("Context: " + _state(event.phase, {
                    "started", "succeeded", "failed", "cancelled",
                }))
            elif isinstance(event, RetryStatusEvent):
                self._offer("Request: " + _state(event.state, {
                    "waiting", "recovered", "cleared", "exhausted",
                }))
            elif isinstance(event, RecoveryStateEvent):
                # Reasons/status strings are not a closed contract: never copy them.
                self._offer("Recovery: updated")

    def _observe_runtime(self, event: AgentEvent) -> None:
        if not self.config.include_status_events:
            return
        if not isinstance(event, SessionTurnStarted | TurnCompleted):
            return
        if (not self._is_source_route(event.context.channel, event.context.chat_id)
                or self._is_target_route(event.context.channel, event.context.chat_id)):
            return
        if isinstance(event, SessionTurnStarted):
            self._offer("Turn: started")
        else:
            self._offer("Turn: " + _state(event.outcome, {
                "completed", "failed", "cancelled", "interrupted",
            }))

    def _build_bot(self) -> Bot:
        def request() -> HTTPXRequest:
            return HTTPXRequest(
                connection_pool_size=1, pool_timeout=1.0,
                connect_timeout=5.0, read_timeout=5.0, write_timeout=5.0,
                proxy=self._proxy,
            )
        # get_updates_request is initialized by PTB, but never polled.
        return Bot(token=self._token, request=request(), get_updates_request=request())

    async def _run(self) -> None:
        bot: Bot | None = None
        try:
            bot = self._build_bot()
            async with asyncio.timeout(SEND_TIMEOUT):
                await bot.initialize()
            while True:
                text = await self._queue.get()
                cooldown = MIN_SEND_INTERVAL
                try:
                    async with asyncio.timeout(SEND_TIMEOUT):
                        receipt = await bot.send_message(
                            chat_id=int(self.config.chat_id), text=text,
                            disable_notification=True,
                        )
                    self.sent += 1
                    if self.on_delivered is not None:
                        try:
                            await self.on_delivered(text, receipt.message_id)
                        except Exception:
                            logger.warning("Telegram notification receipt could not be saved")
                except Exception as exc:
                    self.failed += 1
                    cooldown = FAILURE_COOLDOWN
                    if isinstance(exc, RetryAfter):
                        retry_after = exc.retry_after
                        seconds = (
                            retry_after.total_seconds()
                            if isinstance(retry_after, timedelta) else float(retry_after)
                        )
                        cooldown = max(cooldown, seconds)
                    if self.failed == 1:
                        logger.warning("Telegram technical delivery failed; dropping and cooling down")
                finally:
                    self._queue.task_done()
                await asyncio.sleep(cooldown)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.failed += 1
            logger.warning("Telegram technical sender unavailable; check credentials/proxy and restart")
        finally:
            self._active = False
            self._unsubscribe()
            self._discard_pending()
            if bot is not None:
                with suppress(Exception):
                    async with asyncio.timeout(SEND_TIMEOUT):
                        await bot.shutdown()
