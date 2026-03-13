
import asyncio
from loguru import logger
from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import LuffaConfig

try:
    from luffa_bot import AsyncLuffaClient, set_robot_key
    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False
    AsyncLuffaClient = None  # type: ignore
    set_robot_key = None     # type: ignore
    logger.warning(
        "luffa_bot not found — Luffa channel disabled. "
        "Run: pip install luffa-bot-python-sdk"
    )


class LuffaChannel(BaseChannel):
    """
    Luffa channel that receives and sends messages via luffa-bot-python-sdk.

    receive() is a long-poll that returns List[IncomingEnvelope].

    Each IncomingEnvelope:
        uid      — sender / group UID
        count    — number of messages
        messages — List[IncomingMessage]
        type     — 0 = DM, non-zero = group

    Each IncomingMessage:
        text     — plain-text body
        atList   — List[AtMention]
        urlLink  — optional URL
        msgId    — unique message ID
        uid      — sender UID
    """

    name = "luffa"

    def __init__(self, config: LuffaConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: LuffaConfig = config
        self._client: "AsyncLuffaClient | None" = None
        self._connected = False
        # Set _running so stop() is safe even if start() was never called
        self._running = False


    async def start(self) -> None:
        """
        Start the Luffa channel.

        IMPORTANT: This method blocks for the lifetime of the channel.
        The caller MUST launch it as a task:

            asyncio.create_task(channel.start())   ✓
            await channel.start()                  ✗  blocks forever
        """
        if not _SDK_AVAILABLE:
            logger.error(
                "luffa_bot is not installed. "
                "Run: pip install luffa-bot-python-sdk"
            )
            return

        robot_key = (self.config.token or "").strip()
        if not robot_key:
            logger.error(
                "Luffa robot_key is missing. "
                "Set channels.luffa.token in config.json "
                "(copy the key from robot.luffa.im)."
            )
            return

        if set_robot_key is not None:
            set_robot_key(robot_key)
            logger.debug("Luffa module-level robot_key set.")

        self._running = True
        await self._start_polling()

    async def stop(self) -> None:
        """Stop the Luffa channel."""
        self._running = False
        self._connected = False

        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception as exc:
                logger.warning("Error closing Luffa client: {}", exc)
            self._client = None

        logger.info("Luffa channel stopped.")

    async def send(self, msg: OutboundMessage) -> None:
        """Send an outbound message to Luffa."""
        if not self._client or not self._connected:
            logger.warning("Luffa channel not connected — cannot send message.")
            return

        is_group = bool((msg.metadata or {}).get("is_group"))

        try:
            if is_group:
                await self._client.send_to_group(uid=msg.chat_id, payload=msg.content)
            else:
                await self._client.send_to_user(uid=msg.chat_id, payload=msg.content)
            logger.debug("Luffa sent to {} (group={})", msg.chat_id, is_group)
        except Exception as exc:
            logger.error("Error sending Luffa message to {}: {}", msg.chat_id, exc)

    async def _start_polling(self) -> None:
        """
        Poll via AsyncLuffaClient.receive() with auto-reconnect.
        receive() is a long-poll — it blocks until envelopes arrive.
        """
        robot_key = self.config.token.strip()
        logger.info("Starting Luffa polling (robot_key={}…)", robot_key[:8])

        logger.info(
            "Luffa allow_from={} — if this is [] no messages will be dispatched!",
            self.config.allow_from,
        )

        while self._running:
            try:
                self._client = AsyncLuffaClient(robot_key)
                self._connected = True
                logger.info("Luffa client connected.")

                consecutive_errors = 0

                while self._running:
                    try:
                        envelopes = await self._client.receive()
                        logger.debug(
                            "Luffa receive() returned {} envelope(s): {}",
                            len(envelopes) if envelopes else 0,
                            envelopes,
                        )

                        consecutive_errors = 0

                        for envelope in (envelopes or []):
                            try:
                                await self._handle_envelope(envelope)
                            except Exception as exc:
                                logger.error("Error handling Luffa envelope: {}", exc)

                    except asyncio.CancelledError:
                        return
                    except Exception as exc:
                        consecutive_errors += 1
                        logger.warning(
                            "Luffa receive error #{}: {} — {}",
                            consecutive_errors, type(exc).__name__, exc,
                        )
                        # 5 consecutive auth/config errors → reconnect
                        if consecutive_errors >= 5:
                            logger.error(
                                "5 consecutive receive errors — reconnecting. "
                                "Check robot_key and network connectivity."
                            )
                            break
                        await asyncio.sleep(2)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._connected = False
                self._client = None
                logger.warning("Luffa connection error: {}", exc)

                if self._running:
                    logger.info("Reconnecting in 5 seconds…")
                    await asyncio.sleep(5)

    

    async def _handle_envelope(self, envelope) -> None:
        """
        Dispatch every IncomingMessage inside an IncomingEnvelope.

        IncomingEnvelope.type values:
            0 / None / "user"  → DM
            anything else      → group
        """
        envelope_uid  = getattr(envelope, "uid",  None) or ""
        envelope_type = getattr(envelope, "type", 0)
        is_group = envelope_type not in (0, "0", "user", None)
        messages = getattr(envelope, "messages", None) or []

        logger.debug(
            "Luffa envelope uid={!r} type={!r} is_group={} messages={}",
            envelope_uid, envelope_type, is_group, len(messages),
        )

        for message in messages:
            await self._dispatch_message(message, envelope_uid=envelope_uid, is_group=is_group)

    async def _dispatch_message(self, message, *, envelope_uid: str, is_group: bool) -> None:
        """
        Extract fields from IncomingMessage and hand off to NanoBot.

        IncomingMessage fields: text, uid, msgId, atList, urlLink
        """
        sender_id = getattr(message, "uid", None) or envelope_uid or ""
        chat_id   = envelope_uid or sender_id
        content   = getattr(message, "text", None) or ""
        msg_id    = getattr(message, "msgId", None)

        
        logger.debug(
            "Luffa raw message: sender={!r} chat={!r} content={!r} msgId={!r}",
            sender_id, chat_id, content, msg_id,
        )

        if not content:
            logger.debug("Skipping non-text Luffa message (msgId={})", msg_id)
            return

        
        allowed = self._is_allowed(str(sender_id))
        if not allowed:
            logger.warning(
                "Luffa message from {!r} DROPPED — not in allow_from={}. "
                "Add the UID or use '*' to allow everyone.",
                sender_id, self.config.allow_from,
            )
            return

        logger.info(
            "Luffa message from {} | chat={} | group={} | msgId={}",
            sender_id, chat_id, is_group, msg_id,
        )

        await self._handle_message(
            sender_id=str(sender_id),
            chat_id=str(chat_id),
            content=content,
            metadata={
                "message_id": msg_id,
                "is_group": is_group,
                "at_list": [
                    {"name": getattr(at, "name", None), "did": getattr(at, "did", None)}
                    for at in (getattr(message, "atList", None) or [])
                ],
                "url_link": getattr(message, "urlLink", None),
            },
        )

    
    def _is_allowed(self, sender_id: str) -> bool:
        """Return True if sender is on the allow list (or list contains '*')."""
        return "*" in self.config.allow_from or sender_id in self.config.allow_from